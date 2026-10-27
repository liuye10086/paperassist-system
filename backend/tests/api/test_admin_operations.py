"""Stage10 contracts exercise real isolated PostgreSQL, never external services."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from app.auth.service import create_user
from app.db.database import database_connection, migration_connection
from app.main import app

PASSWORD = 'stage10-safe-password-2026'


def login(client, account):
    client.headers.update({'X-PaperAssist-Client': 'web', 'Origin': 'http://testserver'})
    result = client.post('/api/v1/auth/login', json={'email': account['email'], 'password': PASSWORD})
    assert result.status_code == 200, result.text
    client.headers['X-CSRF-Token'] = result.json()['csrf_token']
    return client


@pytest.fixture
def accounts():
    return [create_user(f'{name}@stage10.test', PASSWORD, role) for name, role in
            [('admin', 'admin'), ('other-admin', 'admin'), ('ordinary', 'user')]]


@pytest.fixture
def admin(accounts):
    with TestClient(app) as client:
        yield login(client, accounts[0])


def seed_task(user_id, *, synthetic=False):
    project, task = str(uuid4()), str(uuid4())
    now = datetime.now(timezone.utc)
    with database_connection(write=True) as db:
        db.execute('''INSERT INTO projects(id,name,research_topic,project_type,created_at,updated_at,owner_id)
            VALUES(%s,'PRIVATE-PROJECT','PRIVATE-TOPIC','sci',%s,%s,%s)''',
                   (project, now.isoformat(), now.isoformat(), user_id))
        db.execute('''INSERT INTO tasks(id,project_id,user_id,task_type,idempotency_key,input_digest,
            input_snapshot,workflow_version,status,phase,revision,current_attempt,created_at,updated_at,error_code)
            VALUES(%s,%s,%s,'boxplot','seed',%s,%s,'test','failed','compute',3,1,%s,%s,'PRIVATE-ERROR')''',
                   (task, project, user_id, 'a'*64, Jsonb({'private': 'PRIVATE-SNAPSHOT', 'synthetic_fixture': synthetic}), now, now))
        db.execute('''INSERT INTO task_attempts(id,task_id,attempt_no,status,started_at,finished_at)
            VALUES(%s,%s,1,'failed',%s,%s)''', (str(uuid4()), task, now-timedelta(seconds=2), now))
    return project, task


def seed_call(user_id, project, task, *, provenance=None, usage=None, cost=None, tool=False):
    from app.adapters.model_usage_store import ModelUsageStore
    now = datetime.now(timezone.utc)
    call_id = str(uuid4())
    state = {'writing_provider_provenance': provenance} if provenance else {}
    with database_connection(write=True) as db:
        db.execute('''INSERT INTO model_calls(id,user_id,project_id,task_id,attempt_no,call_key,input_digest,
            provider,model,policy_snapshot,price_snapshot,status,usage_status,created_at,updated_at,
            provider_state,estimated_cost_micro_usd,provider_response_id)
            VALUES(%s,%s,%s,%s,1,%s,%s,'openai','fixture-model',%s,%s,'completed','estimated',%s,%s,%s,%s,%s)''',
            (call_id,user_id,project,task,call_id,'a'*64,Jsonb({'tools':['code_interpreter'] if tool else []}),
             Jsonb({}),now,now,Jsonb(state),cost,'PRIVATE-PROVIDER-'+call_id))
        if usage is not None:
            for index in range(2):
                ModelUsageStore.insert_event(db,dict(id=str(uuid4()),call_id=call_id,event_key=str(index),
                    event_digest='b'*64,event_type='observation',provider_usage=usage,price_snapshot={},
                    estimated_cost_micro_usd=cost,usage_status='estimated',reason_code=None,
                    created_at=now+timedelta(seconds=index)))
    return call_id


@pytest.mark.parametrize('path', ['/admin/users','/admin/tasks','/admin/usage','/admin/logs','/admin/audit','/admin/metrics'])
def test_all_admin_reads_require_server_admin(accounts, path):
    with TestClient(app) as client:
        login(client, accounts[2])
        result = client.get('/api/v1'+path)
        assert result.status_code == 403, result.text
        assert result.json()['detail']['code'] == 'permission_denied'


def test_accounts_cas_audit_and_session_revocation_are_atomic(admin, accounts):
    target = accounts[2]
    with TestClient(app) as other:
        login(other,target)
        page = admin.get('/api/v1/admin/users',params={'q':'ordinary'}).json()
        assert page['total'] == 1
        assert set(page['items'][0]) == {'id','email','role','active','admin_revision','updated_at','allowed_actions'}
        body = dict(role='admin',active=True,expected_revision=1,reason='Approved admin promotion')
        changed = admin.patch('/api/v1/admin/users/'+target['id'],json=body)
        assert changed.status_code == 200, changed.text
        assert changed.json()['admin_revision'] == 2
        assert other.get('/api/v1/auth/me').status_code == 401
        assert admin.patch('/api/v1/admin/users/'+target['id'],json=body).status_code == 409
    audits = admin.get('/api/v1/admin/audit',params={'target_user_id':target['id']}).json()['items']
    assert len(audits) == 2  # creation via CLI and the web mutation
    event = next(row for row in audits if row['source']=='web')
    assert event['actor_user_id'] == accounts[0]['id']
    assert event['before_role']=='user' and event['after_role']=='admin'
    assert event['request_id']==changed.headers['X-Request-ID']
    with pytest.raises(Exception):
        with database_connection(write=True) as db:
            db.execute('UPDATE admin_audit_events SET reason=%s WHERE id=%s',('mutate',event['id']))


def test_account_guards_and_cli_audit(admin, accounts):
    body=dict(role='user',active=False,expected_revision=1,reason='Approved disable account')
    assert admin.patch('/api/v1/admin/users/'+accounts[0]['id'],json=body).json()['detail']['code']=='admin_self_change'
    changed=admin.patch('/api/v1/admin/users/'+accounts[1]['id'],json=body)
    assert changed.status_code==200,changed.text
    from app.auth.service import set_user_active
    with pytest.raises(Exception): set_user_active(accounts[0]['email'],False)
    body['reason']='  '
    assert admin.patch('/api/v1/admin/users/'+accounts[2]['id'],json=body).status_code==422
    set_user_active(accounts[2]['email'],False)
    audit=admin.get('/api/v1/admin/audit',params={'target_user_id':accounts[2]['id']}).json()['items'][0]
    assert audit['source']=='cli' and audit['actor_user_id'] is None


def test_task_projection_hides_content_and_owner_routes_remain_owner_scoped(admin, accounts):
    project,task=seed_task(accounts[2]['id'])
    result=admin.get('/api/v1/admin/tasks',params={'user_id':accounts[2]['id'],'status':'failed','task_type':'boxplot'})
    assert result.status_code==200,result.text
    row=result.json()['items'][0]
    assert row['id']==task and row['project_id']==project and row['elapsed_ms']==2000
    assert row['error_code'] is None and row['can_open_workspace'] is False and row['allowed_actions']==[]
    detail=admin.get('/api/v1/admin/tasks/'+task)
    assert detail.status_code==200 and detail.json()['workspace_url'] is None
    assert 'PRIVATE' not in result.text+detail.text
    assert admin.get('/api/v1/tasks/'+task+'/workspace').status_code==404
    assert admin.post('/api/v1/tasks/'+task+'/retry',json={'expected_revision':3}).status_code==404
    assert admin.get('/api/v1/admin/tasks',params={'from':'2026-10-24T00:00:00Z','to':'2026-10-23T00:00:00Z'}).status_code==422


def test_usage_latest_observation_unknowns_and_provenance(admin, accounts):
    user=accounts[2]['id'];project,task=seed_task(user)
    seed_call(user,project,task,provenance='synthetic_fixture',usage={'input_tokens':20,'output_tokens':5},cost=70)
    seed_call(user,project,task,usage={'input_tokens':3},tool=True)
    result=admin.get('/api/v1/admin/usage',params={'user_id':user,'group_by':'task'})
    assert result.status_code==200,result.text
    data=result.json();summary=data['summary']
    assert summary['call_count']==2 and summary['input_tokens']=={'known':23,'unknown_count':0}
    assert summary['output_tokens']=={'known':5,'unknown_count':1}
    assert summary['total_tokens']=={'known':25,'unknown_count':1}
    assert summary['estimated_micro_usd']==70 and summary['estimated_unknown_count']==1
    assert summary['actual_micro_usd'] is None and summary['pending_count']==2
    assert data['by_provenance']['synthetic_fixture']['call_count']==1
    assert data['by_provenance']['unknown']['call_count']==1
    assert data['by_provenance']['openai_live']['call_count']==0
    assert data['groups'][0]['key']==task and data['user_charge_enabled'] is False
    assert 'PRIVATE' not in result.text and 'policy_snapshot' not in result.text


def test_synthetic_task_marker_overrides_claimed_live(admin,accounts):
    user=accounts[2]['id'];project,task=seed_task(user,synthetic=True)
    seed_call(user,project,task,provenance='openai_live')
    result=admin.get('/api/v1/admin/usage').json()
    assert result['by_provenance']['openai_live']['call_count']==0
    assert result['by_provenance']['synthetic_fixture']['call_count']==1


def test_me_usage_owner_filters_and_strict_queries(admin,accounts):
    project,task=seed_task(accounts[2]['id'])
    own_project,own_task=seed_task(accounts[0]['id'])
    assert admin.get('/api/v1/me/usage',params={'user_id':accounts[2]['id']}).status_code==422
    assert admin.get('/api/v1/me/usage',params={'project_id':project}).status_code==404
    assert admin.get('/api/v1/me/usage',params={'task_id':task}).status_code==404
    result=admin.get('/api/v1/me/usage',params={'project_id':own_project,'task_id':own_task})
    assert result.status_code==200,result.text
    assert result.json()['budgets'][0]['limit_micro_usd'] is None
    for query in ({'page':'+1'},{'from':'2026-10-23'},{'model':''},{'group_by':'invalid'},{'unexpected':'private'}):
        assert admin.get('/api/v1/admin/usage',params=query).status_code==422
    assert admin.get('/api/v1/admin/usage',params={'project_id':own_project,'task_id':task}).status_code==422


def test_all_api_telemetry_is_safe_includes_auth_failures_and_task_linkage(admin,accounts):
    _,task=seed_task(accounts[0]['id'])
    response=admin.get('/api/v1/tasks/'+task+'/events')
    assert response.status_code==200,response.text
    with TestClient(app) as anonymous:
        denied=anonymous.get('/api/v1/admin/users?private=PRIVATE-QUERY')
        missing=anonymous.get('/api/v1/PRIVATE-PATH')
    assert response.headers['X-Request-ID']
    events=admin.get('/api/v1/admin/logs',params={'task_id':task}).json()['items']
    assert any(e['request_id']==response.headers['X-Request-ID'] and e['route_template']=='/api/v1/tasks/{task_id}/events' for e in events)
    logs=admin.get('/api/v1/admin/logs',params={'request_id':denied.headers['X-Request-ID']})
    assert logs.json()['items'][0]['status']==401
    missing_log=admin.get('/api/v1/admin/logs',params={'request_id':missing.headers['X-Request-ID']}).json()['items'][0]
    assert missing_log['route_template'] is None
    assert 'PRIVATE' not in logs.text+str(missing_log)
    metrics=admin.get('/api/v1/admin/metrics').json()
    assert metrics['errors']>=2 and metrics['coverage']['historical_missing_is_zero'] is False


def test_telemetry_write_failure_does_not_change_success(admin,monkeypatch):
    from app.domain import admin_operations
    monkeypatch.setattr(admin_operations,'record_request',lambda *args,**kwargs: (_ for _ in ()).throw(RuntimeError('PRIVATE-ERROR')))
    result=admin.get('/api/v1/auth/me')
    assert result.status_code==200 and result.headers['X-Request-ID']


def test_concurrent_account_updates_use_revision_and_audit_once(accounts):
    from app.api.admin import AccountChange
    from app.domain.admin_operations import AdminOperations
    from app.core.exceptions import StorageError
    change=AccountChange(role='admin',active=True,expected_revision=1,reason='Concurrent approved promotion')
    service=AdminOperations(accounts[0]['id'])
    def update(_):
        try:return service.change_user(accounts[2]['id'],change,uuid4().hex)['admin_revision']
        except StorageError as exc:return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(update,range(2)))
    assert sorted(map(str,results))==['2','admin_revision_conflict']
    with database_connection() as db:
        assert db.execute("SELECT count(*) AS n FROM admin_audit_events WHERE source='web'").fetchone()['n']==1


def test_audit_failure_rolls_back_account_change_and_session_revocation(admin,accounts):
    user=accounts[2]
    with TestClient(app) as target:
        login(target,user)
        with migration_connection(write=True) as db:
            db.execute("""CREATE FUNCTION reject_admin_audit_test() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN RAISE EXCEPTION 'synthetic write failure'; END $$""")
            db.execute('CREATE TRIGGER reject_admin_audit_test BEFORE INSERT ON admin_audit_events FOR EACH ROW EXECUTE FUNCTION reject_admin_audit_test()')
        result=admin.patch('/api/v1/admin/users/'+user['id'],json=dict(role='admin',active=True,expected_revision=1,reason='Approved admin promotion'))
        assert result.status_code==500,result.text
        assert target.get('/api/v1/auth/me').status_code==200
        with database_connection() as db:
            row=db.execute('SELECT role,admin_revision FROM users WHERE id=%s',(user['id'],)).fetchone()
            assert row['role']=='user' and row['admin_revision']==1


def parse_task_wait(admin,owner, *, unknown=False):
    from tests.api.test_projects import create_project
    from tests.api.test_file_batches import register
    from app.domain.tasks.service import TaskService
    project=create_project(admin)
    base,batch,item,content=register(admin,project)
    uploaded=admin.post(base+'/'+batch['id']+'/items/'+item['client_id'],files={'file':(item['filename'],content)})
    assert uploaded.status_code==202,uploaded.text
    task=uploaded.json()['task'];service=TaskService(owner)
    task=service.transition(task['id'],expected_revision=task['revision'],status='running')
    task=service.transition(task['id'],expected_revision=task['revision'],
        status='waiting_confirmation' if unknown else 'failed',
        reason_code='submission_unknown' if unknown else 'execution_failed')
    if not unknown:
        with database_connection(write=True) as db:
            db.execute("UPDATE tasks SET error_code='parse_process_failed' WHERE id=%s",(task['id'],))
    return task


def test_own_admin_task_detail_reuses_workspace_and_stale_retry_is_rejected(admin,accounts):
    task=parse_task_wait(admin,accounts[0]['id'])
    detail=admin.get('/api/v1/admin/tasks/'+task['id'])
    assert detail.status_code==200,detail.text
    assert detail.json()['can_open_workspace'] is True and detail.json()['allowed_actions']==['retry']
    response=admin.post('/api/v1/tasks/'+task['id']+'/retry',json={'expected_revision':task['revision']-1})
    assert response.status_code==409,response.text
    assert response.json()['detail']['code']=='task_revision_conflict'
    assert admin.post('/api/v1/tasks/'+task['id']+'/retry',json={'expected_revision':task['revision']}).status_code==202
    with database_connection() as db:assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']==0


def test_unknown_external_state_cannot_retry_through_original_owner_api(admin,accounts):
    _,task=seed_task(accounts[0]['id'])
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET status='waiting_confirmation',reason_code='submission_unknown',input_snapshot=%s WHERE id=%s",
            (Jsonb({'result':{'setup_revision':1},'output_language':'zh-CN'}),task))
    response=admin.post('/api/v1/tasks/'+task+'/retry',json={'expected_revision':3})
    assert response.status_code==409,response.text
    with database_connection() as db:assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']==0


def test_own_admin_resume_keeps_state_revision_and_idempotency_checks(admin,accounts):
    task=parse_task_wait(admin,accounts[0]['id'])
    detail=admin.get('/api/v1/admin/tasks/'+task['id'])
    assert detail.status_code==200,detail.text
    assert detail.json()['allowed_actions']==['retry']
    body=dict(operation='retry',wait_id=None,expected_task_revision=task['revision'],input_version=task['input_version'])
    url='/api/v1/tasks/'+task['id']+'/resume'
    assert admin.post(url,json=body).status_code==422
    first=admin.post(url,json=body,headers={'Idempotency-Key':'stage10-resume'})
    assert first.status_code==202,first.text
    replay=admin.post(url,json=body,headers={'Idempotency-Key':'stage10-resume'})
    assert replay.json()==first.json()
    assert admin.post(url,json=body,headers={'Idempotency-Key':'stage10-other'}).status_code==409
    with database_connection() as db:assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']==0
