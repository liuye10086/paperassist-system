import hashlib
import json
import pytest
from pathlib import Path
from tests.api.test_projects import client,create_project
from tests.api.test_bio_insight_plans import source_file,import_plan


def runtime(monkeypatch):
    from app.domain.bio_insights.service import BioInsightsService
    value=dict(engine_version='bio_insights_v1.0.0',environment_digest='e'*64,code_digest='c'*64,lock_sha256='f'*64)
    monkeypatch.setattr(BioInsightsService,'_runtime',lambda self:value)


def create_run(client,monkeypatch):
    runtime(monkeypatch);project=create_project(client)['id'];source=source_file(client,project);base=f'/api/v1/projects/{project}'
    plan=client.post(base+'/bio-insight-plans',json=import_plan(source,'confirmed'),headers={'Idempotency-Key':'publication-plan'})
    assert plan.status_code==201,plan.text
    plan=plan.json()
    run=client.post(base+'/bio-insight-runs',json=dict(plan_version_id=plan['id'],expected_plan_revision=1,source_digest=plan['source_digest']),
                    headers={'Idempotency-Key':'publication-run'})
    assert run.status_code==202,run.text
    return project,run.json()


def synthetic_engine(payload,output):
    # Storage/lifecycle fixture, deliberately not a numerical validation.
    from tests.domain.bio_insight_validation_fixtures import complete_import
    return complete_import(payload,output)


def test_result_publication_is_atomic_replayable_and_download_preserves_zero_na(client,monkeypatch,tmp_path):
    from app.domain.bio_insights.execution import run_bio_insight_task
    project,run=create_run(client,monkeypatch)
    arguments=dict(task_type='bio_result_import',engine=synthetic_engine,staging_directory=tmp_path/'stage')
    result=run_bio_insight_task(run['task_id'],run['task_revision'],**arguments)
    assert result['status']=='succeeded',result
    assert result['result_bio_insight_result_version_id']
    assert run_bio_insight_task(run['task_id'],run['task_revision'],**arguments) is None
    base=f'/api/v1/projects/{project}'
    saved=client.get(base+'/bio-insight-runs/'+run['id']).json()
    assert saved['result_version_id']==result['result_bio_insight_result_version_id']
    response=client.get(base+'/bio-insight-results/'+saved['result_version_id']);assert response.status_code==200,response.text
    artifact=next(m for m in response.json()['members'] if m['key']=='comparison_results')
    download=client.get(artifact['download_url']);assert hashlib.sha256(download.content).hexdigest()==artifact['sha256']
    table=client.get(base+'/bio-insight-results/'+saved['result_version_id']+'/tables/comparison_results?page_size=1').json()
    assert table['total']==2 and table['items'][0]['p_value']=='0' and table['items'][0]['original_q']==''
    workspace=client.get('/api/v1/tasks/'+run['task_id']+'/workspace');assert workspace.status_code==200,workspace.text
    assert workspace.json()['artifacts']['bio_insights']['result_version_id']==saved['result_version_id']


def test_bad_or_expired_result_never_publishes(client,monkeypatch,tmp_path):
    from app.domain.bio_insights.execution import run_bio_insight_task
    from app.db.database import database_connection
    project,run=create_run(client,monkeypatch)
    def stale(payload,output):
        result=synthetic_engine(payload,output)
        with database_connection(write=True) as db:
            db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s",(run['task_id'],))
        return result
    assert run_bio_insight_task(run['task_id'],run['task_revision'],task_type='bio_result_import',engine=stale,staging_directory=tmp_path/'stage') is None
    with database_connection() as db:
        assert db.execute('SELECT result_version_id FROM bio_insight_runs WHERE id=%s',(run['id'],)).fetchone()['result_version_id'] is None
        assert db.execute('SELECT count(*) AS n FROM bio_insight_result_versions WHERE run_id=%s',(run['id'],)).fetchone()['n']==0


@pytest.mark.parametrize('recovery_endpoint',['retry','resume'])
def test_failed_object_write_resumes_frozen_prepared_output_without_recompute(client,monkeypatch,tmp_path,recovery_endpoint):
    from app.domain.bio_insights.execution import run_bio_insight_task
    from app.adapters.bio_insights_store import BioInsightsObjects
    project,run=create_run(client,monkeypatch);original=BioInsightsObjects.write;calls=[]
    def interrupted(self,*args,**kwargs):raise OSError('synthetic disk interruption')
    monkeypatch.setattr(BioInsightsObjects,'write',interrupted)
    arguments=dict(task_type='bio_result_import',staging_directory=tmp_path/'stage')
    result=run_bio_insight_task(run['task_id'],run['task_revision'],engine=synthetic_engine,**arguments)
    assert result['status']=='failed' and result['error_code']=='storage_unavailable',result
    monkeypatch.setattr(BioInsightsObjects,'write',original)
    if recovery_endpoint=='resume':
        from app.db.database import database_connection
        from app.domain.bio_insights.task_contracts import input_version
        with database_connection() as db:
            task=dict(db.execute('SELECT * FROM tasks WHERE id=%s',(run['task_id'],)).fetchone())
        body=dict(operation='retry',wait_id=None,expected_task_revision=result['revision'],input_version=input_version(task))
        headers={'Idempotency-Key':'b04-public-resume-recovery'}
        retry=client.post('/api/v1/tasks/'+run['task_id']+'/resume',json=body,headers=headers)
    else:
        retry=client.post('/api/v1/tasks/'+run['task_id']+'/retry',json={'expected_revision':result['revision']})
    assert retry.status_code==202,retry.text
    def forbidden(*args):calls.append(True);raise AssertionError('must reuse prepared output')
    result=run_bio_insight_task(run['task_id'],retry.json()['revision'],engine=forbidden,**arguments)
    assert result['status']=='succeeded' and calls==[],result
    assert len(list((tmp_path/'stage'/run['task_id']).glob('*/receipt.json')))==2
    if recovery_endpoint=='resume':
        replay=client.post('/api/v1/tasks/'+run['task_id']+'/resume',json=body,headers=headers)
        assert replay.status_code==202 and replay.json()==retry.json()
