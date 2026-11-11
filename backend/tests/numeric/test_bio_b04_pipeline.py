import hashlib
import json
from pathlib import Path

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def bulk_payload(tmp_path, monkeypatch, conditions, repeats, *, age_offset=0, age_unit=1, **config_options):
    from app.adapters.bio_engine import tabular_assays as engine
    from app.domain.bioinformatics.tabular_contracts import BioImportRequestV3

    monkeypatch.setattr(engine, '_figure', lambda *_: None)
    paired = config_options.get('design') == 'paired'
    samples = [f'{condition}{i}' for condition in conditions for i in range(repeats)]
    features = [f'g{i:02d}' for i in range(60)]
    rng = np.random.default_rng(1729)
    counts = rng.negative_binomial(12, .06, size=(len(features), len(samples))) + 2
    counts[0, :repeats] *= 4
    counts[1, repeats:2*repeats] *= 4
    features += ['low', 'only_one', 'qc_excluded']
    counts = np.vstack([counts, np.ones(len(samples),dtype=int), [100,*([0]*(len(samples)-1))], counts[-1]])
    matrix = 'feature_id,'+','.join(samples)+'\n'+''.join(f'{gene},'+','.join(map(str, row))+'\n' for gene, row in zip(features, counts))
    metadata = 'sample_id,condition,biological_unit_id,pair_id,batch,age,sex\n'
    for j, condition in enumerate(conditions):
        for i in range(repeats):
            sample=f'{condition}{i}'
            age = age_offset + age_unit * (30 + i*i + j*i)
            metadata += f'{sample},{condition},{i if paired else sample},p{i},batch{(i+j)%2},{age},{"M" if (i+2*j)%3 else "F"}\n'
    files = []
    for role, body in (('quantitative_matrix', matrix), ('sample_metadata', metadata)):
        path = tmp_path/(role+'.csv')
        path.write_bytes(body.encode())
        files.append(dict(id=role, role=role, filename=path.name, path=str(path),
            size_bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    config = BioImportRequestV3(workflow_version='bio_import_v3', file_ids=[f['id'] for f in files], name='B04 fixture',
        assay='bulk_rna_counts', expected_dataset_revision=0,
        tables=[dict(file_id=f['id'], role=f['role'], format='csv') for f in files],
        feature_id_column='feature_id', sample_columns=samples, scale=dict(kind='raw_counts',unit='counts',
            upstream_method='synthetic',namespace='ensembl',reference_version='synthetic'))
    rawdir=tmp_path/'raw';rawdir.mkdir()
    imported=engine.import_tabular(dict(config=config.model_dump(),files=files,output_directory=str(rawdir)))
    raw=dict(manifest=imported['manifest'],members={m['key']:m for m in imported['outputs']})
    processed=tmp_path/'processed';processed.mkdir()
    result=engine.run_tabular(dict(raw=raw,config={'exclude_features':['qc_excluded']},identity={'code_digest':'a'*64},
        mode='compute',output_directory=str(processed)))
    members={m['key']:m for m in result['outputs']}
    observations=[{**r,'processed_version_id':'p','retained':r['kept']=='True'} for r in engine._rows(members['samples'])]
    source=dict(source_kind='bio_processed_dataset_version',source_id='p',sha256='d'*64,role='processed',
        project_id='project',locator={'kind':'object'},raw=raw,members=members,
        metadata=dict(canonical_dataset_id='raw-p',observation_level='sample',assay='bulk_rna_counts',
            namespace='ensembl',reference_version='synthetic',species_taxon_id=None,feature_ids=features,
            retained_feature_ids=features[:-1],layers=result['manifest']['layers'],manifest=result['manifest'],
            observations=observations,scale=config.scale.model_dump()))
    config=dict(kind='comparison',schema_version=2,mode='bulk_counts',design='independent',method='deseq2_wald',
        analysis_layer='raw_counts',bulk_model='shared_wald_v1',namespace='ensembl',reference_version='synthetic',
        inference_unit='biological',inference_goal='inference',independence_confirmed=True,
        independence_basis='synthetic units',design_basis='prespecified synthetic comparison',data_driven_grouping=False,
        minimum_total_counts=10,minimum_sample_counts=10) | config_options
    return dict(schema_version=1,kind='bio_comparison',identity={'plan_version_id':'fixed'},config=config,sources=[source])


def contrast(numerator, denominator, n):
    return dict(contrast_id=f'{numerator}_{denominator}',name=f'{numerator}/{denominator}',groups=[
        dict(label=label,sample_keys=[dict(processed_version_id='p',sample_id=f'{label}{i}') for i in range(n)])
        for label in (numerator,denominator)])


def run_and_check(payload, tmp_path):
    from app.adapters.bio_insights_engine.pipeline import run
    from app.adapters.bio_insights_process import validate_result

    out=tmp_path/'output';out.mkdir()
    payload['output_directory']=str(out)
    result=run(payload)
    validate_result(result,out,payload)
    return result,out,{m['key']:m for m in result['outputs']}


def test_centered_continuous_covariate_keeps_full_fit_under_offset_and_unit_change(tmp_path, monkeypatch):
    pytest.importorskip('pydeseq2')
    from app.adapters.bio_engine.tabular_assays import _rows

    comparison = contrast('B', 'A', 4)
    model = dict(contrasts=[comparison], family_contrast_ids=[comparison['contrast_id']],
                 covariates=[dict(field='age', kind='continuous', name='Age')],
                 continuous_transform='centered_range_v2')
    tables = []
    for name, options in [('original', {}), ('shifted', {'age_offset': 1_000_000, 'age_unit': 60})]:
        directory = tmp_path / name
        directory.mkdir()
        payload = bulk_payload(directory, monkeypatch, 'AB', 4, **model, **options)
        _, _, members = run_and_check(payload, directory)
        tables.append(_rows(members['comparison_results']))
    assert tables[0] == tables[1]
    assert any(row['test_status'] == 'tested' for row in tables[0])


def test_shared_bulk_pipeline_fits_once_and_reverses_effects(tmp_path, monkeypatch):
    pytest.importorskip('pydeseq2')
    from pydeseq2.dds import DeseqDataSet
    from app.adapters.bio_engine.tabular_assays import _rows
    from app.adapters.bio_insights_process import validate_result
    from app.core.exceptions import StorageError
    from test_bio_tabular_validation import rehash_result

    contrasts=[contrast('A','B',2),contrast('B','A',2),contrast('C','A',2)]
    payload=bulk_payload(tmp_path,monkeypatch,'ABC',2,contrasts=contrasts,
        family_contrast_ids=[c['contrast_id'] for c in contrasts],condition_reference='B')
    payload['config']['design']='multiple'
    original=DeseqDataSet.deseq2
    calls=[]
    def count_fit(self):
        calls.append(self.n_obs)
        return original(self)
    monkeypatch.setattr(DeseqDataSet,'deseq2',count_fit)
    result,out,members=run_and_check(payload,tmp_path)
    assert calls==[6]
    diagnostics=json.loads(Path(members['model_diagnostics']['path']).read_bytes())
    assert len(diagnostics)==1 and diagnostics[0]['contrast_ids']==['A_B','B_A','C_A']
    assert diagnostics[0]['contrast_vectors']['C_A']==[0,-1,1]
    assert len(_rows(members['model_counts']))==62
    assert len(_rows(members['size_factors']))==6
    assert _rows(members['feature_exclusions'])[0]['feature_id']=='qc_excluded'
    table={(row['contrast_id'],row['feature_id']):row for row in _rows(members['comparison_results'])}
    forward=table['A_B','g00'];reverse=table['B_A','g00']
    assert (forward['numerator'],forward['denominator'])==('A','B')
    assert (reverse['numerator'],reverse['denominator'])==('B','A')
    assert float(forward['effect_value'])>1
    assert float(forward['effect_value'])==pytest.approx(-float(reverse['effect_value']))
    assert float(forward['p_value'])==pytest.approx(float(reverse['p_value']),rel=1e-12,abs=0)
    assert table['A_B','low']['reason']=='minimum_total_counts'
    assert table['A_B','only_one']['reason']=='minimum_sample_counts'
    diagnostics[0]['contrast_vectors']['C_A']=[0,0,1]
    rehash_result(result,'model_diagnostics',json.dumps(diagnostics))
    with pytest.raises(StorageError):
        validate_result(result,out,payload)
    assert calls==[6]


def test_paired_batch_and_structured_covariates_fit_and_reconcile(tmp_path, monkeypatch):
    pytest.importorskip('pydeseq2')
    from app.adapters.bio_engine.tabular_assays import _rows

    payload=bulk_payload(tmp_path,monkeypatch,'AB',6,design='paired',batch_adjustment=True,
        contrasts=[contrast('B','A',6)],family_contrast_ids=['B_A'],covariates=[
            dict(field='age',kind='continuous',name='Age'),dict(field='sex',kind='categorical',name='Sex',reference_level='M')])
    result,_,members=run_and_check(payload,tmp_path)
    diagnostic=result['methods']['model_diagnostics'][0]
    assert diagnostic['formula']=='~ donor + batch + covariate_1 + covariate_2 + condition'
    assert diagnostic['rank']==10 and diagnostic['residual_degrees_freedom']==2
    assert diagnostic['terms'][3]['reference_level']=='M'
    assert result['summary']['actual_units'][0]['complete_pairs']==6
    assert len(_rows(members['model_sample_metadata']))==12
    assert any(row['test_status']=='tested' for row in _rows(members['comparison_results']))
