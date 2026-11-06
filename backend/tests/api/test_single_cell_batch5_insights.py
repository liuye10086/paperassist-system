"""Real isolated-schema HTTP/source/task checks with injected parent computation only."""
import pytest
from tests.api.test_projects import client,create_project
from tests.api.test_single_cell_batch4_flow import parent_result
from tests.domain.test_single_cell_composition import config


def test_composition_http_plan_freezes_sources_and_label_edit_invalidates_only_dependents(client,parent_result,monkeypatch):
    from app.domain.bio_insights.service import BioInsightsService
    from app.db.database import database_connection
    f=parent_result;base=f['base'];parent=f['source'];processed=parent['processed_dataset_version_id']
    mapping=client.post(base+'/bio-observation-maps',json=dict(name='Explicit condition',raw_source=parent['raw_source'],expected_revision=0,
        rows=[dict(barcode='c1',group=dict(status='known',value='A')),dict(barcode='c2',group=dict(status='known',value='B'))]),headers={'Idempotency-Key':'b5-map'})
    assert mapping.status_code==201,mapping.text
    annotation_body=dict(name='Reviewed T',raw_source=parent['raw_source'],processed_dataset_version_id=processed,expected_revision=0,
        labels=[dict(id='T',name='T cell',status='confirmed',cell_ids=['c1'])],evidence=[dict(label_id='T',kind='manual',note='Reviewed markers')])
    annotation=client.post(base+'/bio-annotation-sets',json=annotation_body,headers={'Idempotency-Key':'b5-label'})
    assert annotation.status_code==201,annotation.text
    label=annotation.json();selections=[]
    for kind,source_id,role in [('bio_processed_dataset_version',processed,'processed'),('bio_annotation_version',label['id'],'annotation'),('bio_observation_map_version',mapping.json()['id'],'observation_map')]:
        catalog=client.get(base+'/bio-insights/sources',params=dict(source_kind=kind)).json()
        selected=next(i for i in catalog['items'] if i['source_id']==source_id)
        selections.append(dict(source_kind=kind,source_id=source_id,role=role,sha256=selected['sha256']))
    cfg=config();cfg.update(processed_source_id=processed,annotation_source_id=label['id'])
    body=dict(name='Composition',kind='comparison',decision='confirmed',expected_revision=0,sources=selections,config=cfg)
    preview=client.post(base+'/bio-insight-plans/preview',json=body)
    assert preview.status_code==200,preview.text
    assert preview.json()['executable'] and preview.json()['actual_units'][0]['spots_denominator']==1
    infer=client.post(base+'/bio-insight-plans/preview',json={**body,'config':{**cfg,'mode':'donor_paired'}})
    assert infer.status_code==200,infer.text
    assert not infer.json()['executable'] and 'donor_missing' in {r['code'] for r in infer.json()['blocking_reasons']}
    plan=client.post(base+'/bio-insight-plans',json=body,headers={'Idempotency-Key':'b5-plan'})
    assert plan.status_code==201,plan.text
    monkeypatch.setattr(BioInsightsService,'_runtime_for',lambda self,config:dict(engine_version='bio_insights_v1.0.0',environment_digest='e'*64,code_digest='c'*64,lock_sha256='f'*64))
    plan=plan.json()
    run=client.post(base+'/bio-insight-runs',json=dict(plan_version_id=plan['id'],expected_plan_revision=1,source_digest=plan['source_digest']),headers={'Idempotency-Key':'b5-run'})
    assert run.status_code==202,run.text
    assert run.json()['task']['task_type']=='bio_comparison'
    task_id=run.json()['task_id']
    edit={**annotation_body,'expected_revision':1,'labels':[dict(id='T',name='Edited T',status='uncertain',cell_ids=['c1'])]}
    changed=client.post(base+f"/bio-annotation-sets/{label['set_id']}/versions",json=edit,headers={'Idempotency-Key':'b5-label-edit'})
    assert changed.status_code==201,changed.text
    # Historical run metadata stays readable; source-sensitive plan/execution is rejected.
    stale=client.get(base+f"/bio-insight-plans/{plan['plan_id']}/versions/{plan['id']}")
    assert stale.status_code==409,stale.text
    assert stale.json()['detail']['code']=='bio_insight_source_conflict'
    foreign=f"/api/v1/projects/{create_project(client)['id']}"
    assert client.post(foreign+'/bio-insight-plans/preview',json=body).status_code==404
    with database_connection() as db:
        assert db.execute("SELECT count(*) AS n FROM tasks WHERE project_id=%s AND task_type='bio_analysis'",(parent['project_id'],)).fetchone()['n']==1
        assert db.execute('SELECT status FROM tasks WHERE id=%s',(task_id,)).fetchone()['status']=='queued'
    assert f['modes']==['compute']
