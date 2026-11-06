"""Actual selected-cell PyDESeq2 -> ORA/GSEA, bounded synthetic scientific fixtures."""
import hashlib
import numpy as np
import pytest
from app.adapters.bio_engine.manifest import Writer
from tests.numeric.bio_insights_fixtures import source,config,payload,rows

@pytest.fixture(autouse=True)
def postgres_schema():yield None


def selected_result(tmp_path):
    from app.adapters.bio_insights_engine.pipeline import run
    rng=np.random.default_rng(753)
    matrix=rng.negative_binomial(10,.35,size=(24,80)).astype('int64')+1
    matrix[12:,:8]*=4;matrix[:,79]=0
    processed=source(tmp_path,matrix,source_id='p',donors=[f'd{i//4%3}' for i in range(24)],conditions=['A']*12+['B']*12,
        batches=['x' if i%4<2 else 'y' for i in range(24)])
    processed['metadata']['assay']='single_cell'
    # DE must ignore processed feature selection and retain the raw gene axis.
    member=processed['members']['feature_mask'];np.save(member['path'],np.arange(80)<2)
    from pathlib import Path
    member.update(sha256=hashlib.sha256(Path(member['path']).read_bytes()).hexdigest(),size_bytes=Path(member['path']).stat().st_size)
    annotation_dir=tmp_path/'annotation';annotation_dir.mkdir();w=Writer(annotation_dir)
    assignments=dict(rows=[dict(barcode=f'b{i}',label_id='T' if i%2==0 else 'B',status='assigned') for i in range(24)])
    w.json('assignments',assignments)
    annotation=dict(source_kind='bio_annotation_version',source_id='a',role='annotation',sha256='b'*64,
        metadata=dict(processed_dataset_version_id='p',labels=[dict(id='T',name='T cell'),dict(id='B',name='B cell')],assignments=assignments),
        members={m['key']:m for m in w.artifacts})
    cfg=config(24,mode='donor_paired',source_id='p')
    cfg['single_cell_selection']=dict(processed_source_id='p',annotation_source_id='a',label_ids=['T'],labels_confirmed=True,label_basis='Synthetic assigned labels, not biological evidence')
    for group in (cfg['contrasts'][0]['numerator'],cfg['contrasts'][0]['denominator']):
        group['observation_keys']=[k for k in group['observation_keys'] if int(k['barcode'][1:])%2==0]
    output=tmp_path/'de';output.mkdir()
    result=run(dict(payload(cfg,[processed,annotation]),output_directory=str(output)))
    return matrix,cfg,result


def test_selected_raw_integer_pseudobulk_keeps_real_donors_and_tested_background(tmp_path):
    from app.adapters.bio_insights_engine.enrichment import run_enrichment
    from tests.numeric.test_bio_ora import resource_source
    matrix,cfg,result=selected_result(tmp_path)
    w=type('W',(),dict(artifacts=result['outputs']))
    aggregates=rows(w,'aggregation_units');members=rows(w,'aggregation_members');bulk=rows(w,'pseudobulk_counts')
    assert len(aggregates)==6 and len(members)==12
    assert result['summary']['actual_units'][0]['complete_pairs']==3
    assert len(rows(w))==80
    for unit in aggregates:
        indices=[int(r['barcode'][1:]) for r in members if r['unit_id']==unit['unit_id']]
        assert len(indices)==2 and all(i%2==0 for i in indices)
        actual={r['feature_id']:int(r['counts']) for r in bulk if r['unit_id']==unit['unit_id']}
        assert [actual[f'g{i}'] for i in range(80)]==matrix[indices].sum(0).tolist()
    assert next(r for r in rows(w) if r['feature_id']=='g79')['tested']=='False'
    fixed=dict(source_kind='bio_insight_result_version',source_id='result1',role='result',sha256='c'*64,
        members={m['key']:m for m in result['outputs']},metadata=dict(plan_config=cfg,species_taxon_id=9606,
            namespace='ensembl',reference_version='GRCh38.1',summary_json=result['summary'],inference_scope=result['inference_scope']))
    resource=resource_source(tmp_path,terms=[dict(term_id='early',name='Early synthetic genes',namespace='fixture',genes=[f'g{i}' for i in range(8)]),
        dict(term_id='late',name='Late synthetic genes',namespace='fixture',genes=[f'g{i}' for i in range(65,79)])])
    for kind in ('ora','gsea_prerank'):
        common=dict(kind=kind,resource_source_ids=['resource1'],min_size=2,max_size=30)
        c=({**common,'result_source_ids':['result1'],'contrast_ids':['c1'],'q_threshold':0.,'minimum_absolute_effect':0.}
            if kind=='ora' else {**common,'result_source_id':'result1','contrast_id':'c1','ranking_column':'statistic','permutation_num':100,'seed':0})
        output=tmp_path/kind;output.mkdir();writer=Writer(output)
        enriched=run_enrichment(dict(schema_version=1,kind='bio_enrichment',config=c,identity={},sources=[fixed,resource]),writer)
        if kind=='ora':
            assert enriched['summary']['empty_foregrounds']==1
            assert {int(r['N']) for r in rows(writer,'enrichment_results')}=={79}
            assert all(r['n']=='0' for r in rows(writer,'enrichment_results'))
        else:
            ranking=rows(writer,'gsea_ranking')
            assert 'g79' not in {r['feature_id'] for r in ranking}
            assert len(ranking)<=79 and len(ranking)>60
            assert enriched['methods']['upstream_inference_scope']=='donor_inference'
