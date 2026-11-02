"""Actual schema-2 sample comparison into existing ORA/GSEA; synthetic only."""
import hashlib
import json
import pytest
from bio_insights_fixtures import rows


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def sample_result(tmp_path, monkeypatch):
    from app.adapters.bio_engine import tabular_assays as tabular
    from app.adapters.bio_insights_engine.pipeline import run
    from app.domain.bioinformatics.tabular_contracts import BioImportRequestV3
    monkeypatch.setattr(tabular, '_figure', lambda *args: None)
    samples = ['B0', 'B1', 'B2', 'B3', 'A0', 'A1', 'A2', 'A3']
    features = [f'f{i:02d}' for i in range(20)]
    matrix = 'feature_id,' + ','.join(samples) + '\n'
    for i, feature in enumerate(features):
        values = [30+i+(10-i if s[0]=='B' else 0)+int(s[1]) for s in samples]
        matrix += feature + ',' + ','.join(map(str, values)) + '\n'
    metadata = 'sample_id,condition,biological_unit_id,sample_role\n' + ''.join(f'{s},{s[0]},{s},biological\n' for s in samples)
    files = []
    for role, content in [('quantitative_matrix', matrix), ('sample_metadata', metadata)]:
        path = tmp_path/(role+'.csv'); path.write_text(content, encoding='utf-8')
        files.append(dict(id=role, role=role, path=str(path), filename=path.name, size_bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    config = BioImportRequestV3(workflow_version='bio_import_v3', file_ids=[f['id'] for f in files], name='synthetic sample enrichment',
        assay='normalized_expression', expected_dataset_revision=0, tables=[dict(file_id=f['id'], role=f['id'], format='csv') for f in files],
        feature_id_column='feature_id', sample_columns=samples, scale=dict(kind='normalized', unit='synthetic normalized expression',
        upstream_method='deterministic engineering fixture, not a biological dataset', namespace='fixture_gene', reference_version='synthetic-v1', species_taxon_id=9606)).model_dump()
    rawdir=tmp_path/'raw'; rawdir.mkdir(); imported=tabular.import_tabular(dict(config=config, files=files, output_directory=str(rawdir)))
    raw=dict(manifest=imported['manifest'], members={m['key']:m for m in imported['outputs']})
    folder=tmp_path/'processed'; folder.mkdir()
    processed=tabular.run_tabular(dict(raw=raw, config={'normalization':'already_normalized'}, identity={}, mode='compute', output_directory=str(folder)))
    members={m['key']:m for m in processed['outputs']}
    source=dict(source_kind='bio_processed_dataset_version', source_id='p', role='processed', sha256='a'*64, project_id='project', locator={'kind':'object'}, raw=raw, members=members,
        metadata=dict(canonical_dataset_id='raw', observation_level='sample', assay='normalized_expression', namespace='fixture_gene', reference_version='synthetic-v1', species_taxon_id=9606,
        feature_ids=features, retained_feature_ids=features, layers=processed['manifest']['layers'], manifest=processed['manifest'], scale=config['scale'],
        observations=[{**r,'processed_version_id':'p','retained':r['kept']=='True'} for r in tabular._rows(members['samples'])]))
    comparison=dict(kind='comparison', schema_version=2, mode='continuous', design='independent', method='welch_t', analysis_layer='analysis',
        contrasts=[dict(contrast_id='B_A', name='B/A', groups=[dict(label=g,sample_keys=[dict(processed_version_id='p',sample_id=s) for s in samples if s[0]==g]) for g in ('B','A')])],
        family_contrast_ids=['B_A'], namespace='fixture_gene', reference_version='synthetic-v1', species_taxon_id=9606, inference_unit='biological',
        independence_confirmed=True, independence_basis='synthetic units only', design_basis='predeclared fixture', inference_goal='exploratory', data_driven_grouping=False)
    out=tmp_path/'comparison';out.mkdir()
    result=run(dict(schema_version=1,kind='bio_comparison',identity={'plan_version_id':'plan'},config=comparison,sources=[source],output_directory=str(out)))
    return dict(source_kind='bio_insight_result_version',source_id='result1',role='result',sha256='b'*64,members={m['key']:m for m in result['outputs']},
        metadata=dict(plan_config=comparison,species_taxon_id=9606,namespace='fixture_gene',reference_version='synthetic-v1',summary_json=result['summary'],inference_scope=result['inference_scope']))


@pytest.mark.parametrize('kind',['ora','gsea_prerank'])
def test_actual_sample_result_enrichment_complete_axes_and_scope(tmp_path,monkeypatch,kind):
    from test_bio_ora import resource_source,execute
    source=sample_result(tmp_path,monkeypatch)
    resource=resource_source(tmp_path,namespace='fixture_gene',terms=[dict(term_id='positive',name='fixture positive',namespace='BP',genes=[f'f{i:02d}' for i in range(5)]),
        dict(term_id='negative',name='fixture negative',namespace='BP',genes=[f'f{i:02d}' for i in range(15,20)])])
    common=dict(kind=kind,resource_source_ids=['resource1'],min_size=2,max_size=10)
    config=({**common,'result_source_ids':['result1'],'contrast_ids':['B_A'],'direction':'both','q_threshold':.05,'minimum_absolute_effect':0.}
        if kind=='ora' else {**common,'result_source_id':'result1','contrast_id':'B_A','ranking_column':'statistic','permutation_num':100,'seed':0})
    result,writer=execute(tmp_path,config,[source,resource])
    actual=rows(writer,'enrichment_results')
    assert len(actual)==2 and all(r['source_inference_scope']=='sample_exploratory' for r in actual)
    assert result['inference_scope']=='derived'
    if kind=='ora':
        assert all(int(r['N'])==20 for r in actual)
        assert result['methods']['upstream'][0]['inference_scope']=='sample_exploratory'
    else:
        ranking=rows(writer,'gsea_ranking')
        assert len(ranking)==20 and {r['feature_id'] for r in ranking}=={f'f{i:02d}' for i in range(20)}
        assert result['methods']['upstream_inference_scope']=='sample_exploratory'
