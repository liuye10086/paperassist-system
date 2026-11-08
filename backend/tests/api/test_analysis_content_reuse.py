"""Real isolated PostgreSQL/task/object contracts; synthetic scientific leaves only."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.api.test_projects import client, create_project
from tests.api.test_single_cell_direct_start import ready_single_cell, synthetic_engine


def post_cell(client, fixture, key, **changes):
    body=dict(name='Reuse cells',raw_source=fixture['source'],params={'min_spots':1})
    return client.post(fixture['base']+'/single-cell-analysis-runs',json={**body,**changes},headers={'Idempotency-Key':key})


@pytest.mark.parametrize('state',['queued','running','succeeded'])
def test_direct_content_reuse_preserves_task_recipe_and_alias_recovery(client,ready_single_cell,monkeypatch,state):
    from app.db.database import database_connection
    from app.domain.tasks.execution import run_task
    from app.domain.bioinformatics import analysis_execution,single_cell_settings
    fixture=ready_single_cell
    original=post_cell(client,fixture,'original');assert original.status_code==202,original.text
    original=original.json()
    if state=='running':
        with database_connection(write=True) as db:db.execute("UPDATE tasks SET status='running' WHERE id=%s",(original['task']['id'],))
    elif state=='succeeded':
        monkeypatch.setattr(analysis_execution,'execute_bio_analysis',synthetic_engine(fixture['source'],fixture['runtime'],[]))
        assert run_task(original['task']['id'],original['task']['revision'])['status']=='succeeded'
    with database_connection() as db:
        counts={table:db.execute('SELECT count(*) AS n FROM '+table).fetchone()['n'] for table in ('tasks','task_attempts','task_outbox','bio_analysis_setups','bio_analysis_recipe_versions','bio_processed_dataset_versions')}
        frozen=dict(db.execute('SELECT * FROM tasks WHERE id=%s',(original['task']['id'],)).fetchone())
    reused=post_cell(client,fixture,'alias',name='Different display name')
    assert reused.status_code==202,reused.text
    assert reused.json()['id']==original['id']
    assert reused.json()['recipe_version_id']==original['recipe_version_id']
    recovered=client.get(fixture['base']+'/bio-requests/alias?kind=run')
    assert recovered.status_code==200 and recovered.json()['id']==original['id'],recovered.text
    assert post_cell(client,fixture,'alias',name='Conflicting alias body').status_code==409
    monkeypatch.setattr(single_cell_settings,'runtime_identity',lambda:{'available':False})
    replay=post_cell(client,fixture,'alias',name='Different display name')
    assert replay.status_code==202 and replay.json()['id']==original['id'],replay.text
    with database_connection() as db:
        assert counts=={table:db.execute('SELECT count(*) AS n FROM '+table).fetchone()['n'] for table in counts}
        assert dict(db.execute('SELECT * FROM tasks WHERE id=%s',(original['task']['id'],)).fetchone())==frozen
        receipt=db.execute("SELECT * FROM analysis_request_receipts WHERE request_key='alias'").fetchone()
        assert receipt['target_id']==original['id'] and receipt['request_digest']==recovered.json()['request_digest']


def test_direct_different_keys_are_serialized_by_scientific_content(client,ready_single_cell):
    from app.adapters.storage import ProjectStore
    from app.core.config import get_data_dir
    from app.db.database import database_connection
    from app.domain.bioinformatics.analysis_service import BioAnalysisService
    from app.domain.bioinformatics.single_cell_contracts import SingleCellAnalysisStartRequest
    fixture=ready_single_cell;project=fixture['source']['project_id']
    with database_connection() as db:owner=db.execute('SELECT owner_id FROM projects WHERE id=%s',(project,)).fetchone()['owner_id']
    service=BioAnalysisService(ProjectStore(get_data_dir(),owner_id=owner))
    def submit(key):return service.start_single_cell(project,SingleCellAnalysisStartRequest(name='Concurrent',raw_source=fixture['source'],params={'min_spots':1}),key)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(submit,['concurrent-a','concurrent-b']))
    assert results[0]['id']==results[1]['id']
    for key in ('concurrent-a','concurrent-b'):
        assert client.get(fixture['base']+'/bio-requests/'+key+'?kind=run').json()['id']==results[0]['id']
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM bio_analysis_runs').fetchone()['n']==1
        assert db.execute('SELECT count(*) AS n FROM bio_analysis_recipe_versions').fetchone()['n']==1


def test_direct_changes_create_new_run_but_original_failure_remains_bound(client,ready_single_cell,monkeypatch):
    from app.domain.tasks.execution import run_task
    from app.domain.bioinformatics import analysis_execution
    fixture=ready_single_cell;first=post_cell(client,fixture,'first').json()
    changed=post_cell(client,fixture,'seed-change',params={'min_spots':1,'seed':43})
    assert changed.status_code==202 and changed.json()['id']!=first['id'],changed.text
    def broken(*args,**kwargs):raise RuntimeError('synthetic failure')
    monkeypatch.setattr(analysis_execution,'execute_bio_analysis',broken)
    assert run_task(first['task']['id'],first['task']['revision'])['status']=='failed'
    replay=post_cell(client,fixture,'first');assert replay.json()['id']==first['id']
    retry=post_cell(client,fixture,'retry');assert retry.status_code==202 and retry.json()['id']!=first['id'],retry.text


def test_saved_recipe_content_reuse_keeps_direct_and_manual_modes_separate(client,ready_single_cell):
    fixture=ready_single_cell;direct=post_cell(client,fixture,'direct').json()
    body=dict(raw_source=fixture['source'],recipe_version_id=direct['recipe_version_id'],expected_setup_revision=direct['expected_setup_revision'])
    first=client.post(fixture['base']+'/bio-analysis-runs',json=body,headers={'Idempotency-Key':'manual-first'})
    assert first.status_code==202 and first.json()['id']!=direct['id'],first.text
    alias=client.post(fixture['base']+'/bio-analysis-runs',json=body,headers={'Idempotency-Key':'manual-alias'})
    assert alias.status_code==202 and alias.json()['id']==first.json()['id'],alias.text
    assert client.get(fixture['base']+'/bio-requests/manual-alias?kind=run').json()['id']==first.json()['id']


def test_receipt_scope_immutability_and_runtime_permissions(client,ready_single_cell):
    from app.db.database import database_connection
    from app.adapters.analysis_request_receipts import bind_receipt,read_receipt
    from app.core.exceptions import StorageError
    fixture=ready_single_cell;original=post_cell(client,fixture,'scope-original').json();project=fixture['source']['project_id']
    with database_connection() as db:owner=db.execute('SELECT owner_id FROM projects WHERE id=%s',(project,)).fetchone()['owner_id']
    with database_connection(write=True) as db:
        args=dict(user_id=owner,project_id=project,kind='bio_analysis_run',key='scope-alias',request_digest='a'*64,target_id=original['id'])
        assert bind_receipt(db,**args)['target_id']==original['id']
        assert bind_receipt(db,**args)['target_id']==original['id']
        with pytest.raises(StorageError):bind_receipt(db,**{**args,'request_digest':'b'*64})
        with pytest.raises(StorageError):read_receipt(db,user_id='other',project_id=project,kind='bio_analysis_run',key='scope-alias')
        with pytest.raises(ValueError):read_receipt(db,user_id=owner,project_id=project,kind='unregistered',key='scope-alias')
        assert not db.execute("SELECT has_table_privilege(current_user,'analysis_request_receipts','UPDATE') AS allowed").fetchone()['allowed']
        assert not db.execute("SELECT has_table_privilege(current_user,'analysis_request_receipts','DELETE') AS allowed").fetchone()['allowed']
    other=create_project(client)['id']
    with database_connection(write=True) as db:
        with pytest.raises(StorageError):bind_receipt(db,**{**args,'project_id':other,'key':'cross'})


def test_insight_content_reuse_has_recoverable_alias_and_runtime_identity(client,monkeypatch):
    from tests.api.test_bio_insight_plans import source_file,import_plan
    from app.domain.bio_insights.service import BioInsightsService
    from app.db.database import database_connection
    runtime=dict(engine_version='bio_insights_v1.0.0',environment_digest='e'*64,code_digest='c'*64,lock_sha256='f'*64)
    monkeypatch.setattr(BioInsightsService,'_runtime',lambda self:runtime)
    project=create_project(client)['id'];base=f'/api/v1/projects/{project}';source=source_file(client,project)
    plan=client.post(base+'/bio-insight-plans',json=import_plan(source,'confirmed'),headers={'Idempotency-Key':'plan'}).json()
    body=dict(plan_version_id=plan['id'],expected_plan_revision=1,source_digest=plan['source_digest'])
    def submit(key):return client.post(base+'/bio-insight-runs',json=body,headers={'Idempotency-Key':key})
    first=submit('first');assert first.status_code==202,first.text
    alias=submit('alias');assert alias.status_code==200 and alias.json()['id']==first.json()['id'],alias.text
    assert client.get(base+'/bio-insight-requests/alias?kind=run').json()['id']==first.json()['id']
    runtime['code_digest']='d'*64
    changed=submit('runtime-change');assert changed.status_code==202 and changed.json()['id']!=first.json()['id'],changed.text
    with database_connection() as db:assert db.execute('SELECT count(*) AS n FROM bio_insight_runs').fetchone()['n']==2


def test_report_content_reuse_has_recoverable_alias_and_preserves_root_cas(client):
    from tests.api.test_research_findings import selected_cell
    base,source=selected_cell(client)
    finding=client.post(base+'/research-findings',json={'title':'Reuse source','sources':[source]},headers={'Idempotency-Key':'finding'}).json()
    body=dict(title='Same report',finding_version_id=finding['id'])
    def submit(key,body=body):return client.post(base+'/research-reports',json=body,headers={'Idempotency-Key':key})
    first=submit('first');assert first.status_code==201,first.text
    alias=submit('alias');assert alias.status_code==200 and alias.json()['id']==first.json()['id'],alias.text
    recovery=client.get(base+'/research-requests/alias?kind=report')
    assert recovery.status_code==200 and recovery.json()['id']==first.json()['id'],recovery.text
    current=first.json();next_body={**body,'root_id':current['root_id'],'expected_revision':current['revision'],'title':'Changed report'}
    changed=submit('changed',next_body);assert changed.status_code==201,changed.text
    stale=submit('stale',{**next_body,'title':'Stale concurrent edit'})
    assert stale.status_code==409,stale.text
