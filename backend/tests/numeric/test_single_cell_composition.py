"""Fixture numerical checks; these do not replace real propeller or donor-data checks."""
import os
os.environ["MPLBACKEND"]="Agg"
import json
import numpy as np
import pytest
from app.adapters.bio_engine.manifest import Writer
from tests.numeric.bio_insights_fixtures import source,payload,rows
from tests.domain.test_single_cell_composition import config

@pytest.fixture(autouse=True)
def postgres_schema():yield None


def fixture(tmp_path):
    processed=source(tmp_path,np.ones((12,3),dtype='int64'),source_id='p',donors=['d0','d1','d2']*4,
        conditions=['A']*6+['B']*6,batches=['b']*12)
    processed['metadata']['assay']='single_cell'
    w=Writer(tmp_path)
    assignments=dict(rows=[dict(barcode=f'b{i}',label_id='T' if i%2==0 else None,status='assigned' if i%2==0 else 'unknown') for i in range(12)])
    w.json('assignments',assignments)
    annotation=dict(source_kind='bio_annotation_version',source_id='a',sha256='b'*64,role='annotation',
        metadata=dict(processed_dataset_version_id='p',labels=[dict(id='T',name='T')],assignments=assignments),
        members={m['key']:m for m in w.artifacts})
    return [processed,annotation]


def test_descriptive_pipeline_preserves_denominator_and_publishes_no_pvalues(tmp_path):
    from app.adapters.bio_insights_engine.pipeline import run
    sources=fixture(tmp_path);output=tmp_path/'out';output.mkdir()
    result=run(dict(payload(config(),sources),output_directory=str(output)))
    assert result['inference_scope']=='sample_exploratory'
    assert result['summary']['total_cells']==12
    assert result['summary']['inference_status']=='not_requested'
    assert result['summary']['unit_count']==6
    assert result['methods']['label_names']=={'T':'T'}
    assert (output/'composition_plot.png').is_file()
    table=rows(type('W',(),dict(artifacts=result['outputs'])),'composition_results')
    assert all(not r['p_value'] for r in table)
    assert all(r['inference_status']=='not_requested' for r in table)
    assert sum(int(r['cell_count']) for r in rows(type('W',(),dict(artifacts=result['outputs'])),'composition_counts'))==12


def test_pseudobulk_rejects_manual_selection_outside_confirmed_label(tmp_path):
    from app.adapters.bio_insights_engine.comparison import run_comparison
    from tests.numeric.bio_insights_fixtures import config as de_config
    sources=fixture(tmp_path)
    cfg=de_config(n=12,mode='donor_paired',source_id='p');cfg['single_cell_selection']={k:config()[k] for k in ('processed_source_id','annotation_source_id','label_ids','labels_confirmed','label_basis')}
    output=tmp_path/'out';output.mkdir()
    with pytest.raises(ValueError,match='single_cell_selection_membership_mismatch'):run_comparison(payload(cfg,sources),Writer(output))


def test_parent_rejects_composition_denominator_tampering(tmp_path):
    from app.adapters.bio_insights_engine.pipeline import run
    from app.adapters.bio_insights_process import validate_result
    from tests.domain.bio_insight_validation_fixtures import put,refresh
    sources=fixture(tmp_path);output=tmp_path/'out';output.mkdir();p=dict(payload(config(),sources),output_directory=str(output))
    result=run(p)
    validate_result(result,output,p)
    result['_root']=str(output)
    data=rows(type('W',(),dict(artifacts=result['outputs'])),'composition_counts')
    data[0]['denominator_cells']='999'
    put(result,'composition_counts',(list(data[0]),data),'tsv');refresh(result);result.pop('_root')
    with pytest.raises(Exception):validate_result(result,output,p)


def test_single_cell_transport_drops_redundant_label_member_lists_only(tmp_path):
    from app.adapters.bio_insights_engine.transport import project_transport_payload
    sources=fixture(tmp_path)
    sources[1]['metadata']['labels'][0]['cell_ids']=['b'+str(i) for i in range(12)]
    sources[1]['metadata']['geometry']=dict(regions=[],evidence=[dict(note='manual')])
    original=payload(config(),sources)
    projected=project_transport_payload(original)
    assert 'cell_ids' not in projected['sources'][1]['metadata']['labels'][0]
    assert 'assignments' not in projected['sources'][1]['metadata']
    from app.adapters.bio_insights_engine.transport import hydrate_single_cell_annotations
    hydrated=hydrate_single_cell_annotations(projected)
    assert hydrated['sources'][1]['metadata']['assignments']==sources[1]['metadata']['assignments']
    assert 'cell_ids' in original['sources'][1]['metadata']['labels'][0]

def test_single_condition_description_has_one_denominator_and_no_difference_or_ratio(tmp_path):
    from app.adapters.bio_insights_engine.pipeline import run
    from app.adapters.bio_insights_process import validate_result
    sources=fixture(tmp_path);cfg=config();cfg['numerator']='A';output=tmp_path/'single';output.mkdir()
    p=dict(payload(cfg,sources),output_directory=str(output));result=run(p)
    validate_result(result,output,p)
    assert result['summary']['total_cells']==6
    assert result['summary']['condition_count']==1
    assert result['summary']['actual_units'][0]['spots_numerator']==0
    table=rows(type('W',(),dict(artifacts=result['outputs'])),'composition_results')
    assert all(r['proportion_difference']==r['proportion_ratio']==r['p_value']=='' for r in table)
    assert all(r['reason']=='single_condition_description' for r in table)


def test_annotation_transport_rehydrates_only_verified_declared_member_after_projection(tmp_path):
    from app.adapters.bio_insights_engine.transport import project_transport_payload,hydrate_single_cell_annotations
    sources=fixture(tmp_path);p=payload(config(),sources)
    wire=project_transport_payload(p)
    assert 'assignments' not in wire['sources'][1]['metadata']
    restored=hydrate_single_cell_annotations(wire)
    assert restored['sources'][1]['metadata']['assignments']==sources[1]['metadata']['assignments']
    assert 'assignments' not in wire['sources'][1]['metadata']
    assert project_transport_payload(restored)==wire
    member=sources[1]['members']['assignments']
    from pathlib import Path
    Path(member['path']).write_bytes(b'{"rows":[]}')
    with pytest.raises(ValueError,match='input_member'):hydrate_single_cell_annotations(wire)
