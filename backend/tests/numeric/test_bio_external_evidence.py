"""One bounded pipeline/parent/render slice for typed fixed evidence."""
import json
from pathlib import Path

def test_matrix_pipeline_parent_and_three_fixed_figures(tmp_path):
    from app.adapters.bio_insights_engine.pipeline import run
    from app.adapters.bio_insights_process import validate_result
    from app.domain.bio_insights.evidence_contracts import EvidenceMatrixConfig
    from app.domain.bio_insights.contracts import FigureConfig
    evidence=[]
    for i,group in [(1,'paper'),(2,'paper'),(3,'atlas')]:
        record=dict(evidence_type='mutation_literature' if i==2 else 'expression_atlas' if i==3 else 'disease_literature',object_id='ERBB2',species_taxon_id=9606,condition='metastatic' if i<3 else 'normal',study_id=group,dependency_group=group,shared_dataset_ids=[group],locators=[dict(kind='text',value='ERBB2 HER2',quote='ERBB2 HER2')],statement='source statement',human_review_status='reviewed',result_status='reported',disease_scope='direct')
        evidence.append(dict(source_id='e'+str(i),source_kind='external_evidence_version',sha256=str(i)*64,role='external_evidence',project_id='fixture',locator={'kind':'object'},metadata=dict(typed_evidence=record,locator_verification={'locator_verified':True},source_file_ids=['paper-original' if i<3 else 'atlas-original'],original_sha256=('a' if i<3 else 'b')*64,filename='paper.xml' if i<3 else 'atlas.html'),members={}))
    candidates=[dict(object_id='ERBB2',source_id='protein',feature_id='HER2',namespace='label',species_taxon_id=9606,reference_version='unknown',condition='primary',mapping_evidence_source_id='e1',mapping_locator='Par2',mapping_quote='ERBB2 HER2'),dict(object_id='STAT5A',source_id='mrna',feature_id='STAT5A',namespace='symbol',species_taxon_id=9606,reference_version='unknown',condition='primary')]
    from app.adapters.bio_engine.manifest import Writer
    path=tmp_path/'saved-integration';path.mkdir();w=Writer(path);saved_integration=dict(correlations=[dict(pair_id='STAT5A_saved',coefficient=.5,p_value=None,q_value=None)],nodes=[],edges=[])
    w.json('integration_data',saved_integration)
    upstream=dict(source_id='saved-integration',source_kind='bio_insight_result_version',sha256='f'*64,role='result',project_id='fixture',locator={'kind':'object'},metadata={'kind':'integration'},members={m['key']:m for m in w.artifacts})
    config=EvidenceMatrixConfig(candidates=candidates,evidence_source_ids=['e1','e2','e3'],integration_result_source_ids=['saved-integration']).model_dump(mode='json')
    identity=dict(project_id='fixture',task_id='task',plan_version_id='plan',source_digest='a'*64,engine_version='bio_insights_v1.0.0',code_digest='b'*64,environment_digest='c'*64,lock_sha256='d'*64)
    def execute(kind,config,sources,name):
        dest=tmp_path/name;dest.mkdir();payload=dict(schema_version=1,kind=kind,config=config,sources=sources,identity=identity,output_directory=str(dest));result=run(payload);validate_result(result,dest,payload);return result
    result=execute('bio_candidate',config,evidence+[upstream],'matrix');data=json.loads(next(Path(m['path']).read_bytes() for m in result['outputs'] if m['key']=='evidence_data'))
    assert len(data['matrix'])==6 and len(data['dependency_groups'])==2
    assert len(data['nodes'])==13 and len(data['edges'])==20
    assert data['integration_results'][0]['data']==saved_integration
    assert any(e['source']=='integration:saved-integration' and e['relation']=='saved_result_reference' for e in data['edges'])
    assert {'processed:protein','processed:mrna','matrix:fixed-evidence-cross-product'}<={n['id'] for n in data['nodes']}
    assert len([e for e in data['edges'] if e['relation']=='fixed_axis_selection'])==2
    assert [r['status'] for r in data['matrix']]==['context']*3+['missing']*3
    source=dict(source_id='matrix',source_kind='bio_insight_result_version',sha256='d'*64,role='result',project_id='fixture',locator={'kind':'object'},metadata=dict(kind='candidate',inference_scope='derived',provenance='system_computed'),members={m['key']:m for m in result['outputs']})
    for kind in ('matrix','network','flow'):
        cfg=FigureConfig(result_source_id='matrix',figure_type='evidence_'+kind,formats=['png']).model_dump(mode='json')
        figure=execute('bio_insight_figure',cfg,[source],kind+'-figure');plot=json.loads(next(Path(m['path']).read_bytes() for m in figure['outputs'] if m['key']=='plot_data'))
        if kind=='flow':assert {e['relation'] for e in plot['display_edges']}=={'fixed_axis_selection','candidate_input','external_statement_input','fixed_original_locator','saved_result_reference'}
        assert plot['matrix']==data['matrix'] and plot['edges']==data['edges'] and plot['analysis_recomputed'] is False and plot['causal_edges'] is False
        assert {'figure_png'}<={m['key'] for m in figure['outputs']}
