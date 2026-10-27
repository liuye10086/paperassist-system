"""Offline runtime receipts and real isolated-DB HTTP admission contracts."""
from datetime import datetime, timedelta, timezone
import json

import pytest
from fastapi.testclient import TestClient

from app.db.database import database_connection, get_database_config
from app.main import app
from tests.api.test_admin_operations import accounts, admin, login, seed_task, seed_call

PUBLIC = '/api/v1/runtime/status'
ADMIN = '/api/v1/admin/runtime/status'


@pytest.fixture
def control(monkeypatch, tmp_path):
    monkeypatch.setenv('PAPERASSIST_RUNTIME_CONTROL_DIR', str(tmp_path))
    monkeypatch.setenv('PAPERASSIST_RUNTIME_NAMESPACE', 'batch04-test')
    config = get_database_config()
    binding = dict(schema_version=1, namespace='batch04-test', environment=config.environment,
                   database_schema=config.schema)
    def write(name, **values):
        payload = dict(binding, **values)
        (tmp_path/name).write_text(json.dumps(payload), encoding='utf-8')
        return payload
    write('maintenance.json', mode='normal', updated_at=datetime.now(timezone.utc).isoformat(), retry_after_seconds=30)
    return write


def test_public_runtime_is_session_independent_and_minimal(control):
    with TestClient(app) as client:
        response = client.get(PUBLIC)
        assert response.status_code == 200, response.text
        assert set(response.json()) == {'status', 'reason', 'observed_at'}
        assert response.json()['status'] == 'service_unavailable'  # no collector receipt


def test_maintenance_blocks_new_business_writes_without_changes_but_allows_reads_and_sessions(admin, accounts, control):
    project, task = seed_task(accounts[0]['id'])
    with database_connection() as db:
        before = dict(db.execute('SELECT input_snapshot,status,revision FROM tasks WHERE id=%s', (task,)).fetchone())
        count = db.execute('SELECT count(*) AS n FROM projects').fetchone()['n']
    control('maintenance.json', mode='maintenance', updated_at=datetime.now(timezone.utc).isoformat(), retry_after_seconds=30)
    assert admin.get(PUBLIC).json()['status'] == 'maintenance'
    assert admin.get('/api/v1/projects').status_code == 200
    assert admin.get('/api/v1/auth/me').status_code == 200
    for path, body in [('/api/v1/projects', dict(name='blocked', research_topic='blocked', project_type='sci')),
                       (f'/api/v1/tasks/{task}/retry', {})]:
        response = admin.post(path, json=body)
        assert response.status_code == 503, response.text
        assert response.json()['detail']['code'] == 'service_maintenance'
        assert response.json()['detail']['request_id'] == response.headers['X-Request-ID']
        assert response.headers['Retry-After'] == '30'
    with database_connection() as db:
        assert dict(db.execute('SELECT input_snapshot,status,revision FROM tasks WHERE id=%s', (task,)).fetchone()) == before
        assert db.execute('SELECT count(*) AS n FROM projects').fetchone()['n'] == count
    with TestClient(app) as other:
        login(other, accounts[2])
        assert other.get('/api/v1/projects/'+project).status_code == 404
        assert other.post('/api/v1/auth/logout').status_code == 204


def test_runtime_admin_auth_and_unknown_receipts(admin, accounts, control):
    with TestClient(app) as client:
        assert client.get(ADMIN).status_code == 401
        login(client, accounts[2])
        assert client.get(ADMIN, params={'role':'admin','queued_count':0}).status_code == 403
        with database_connection(write=True) as db:
            db.execute('UPDATE users SET active=false WHERE id=%s', (accounts[2]['id'],))
        assert client.get(ADMIN).status_code == 401
    result = admin.get(ADMIN)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body['coverage']['status'] == 'unknown'
    assert body['queue'] is None and body['services']['worker']['status'] == 'unknown'
    assert 'PRIVATE-' not in result.text


def test_fresh_collector_receipt_stale_malformed_wrong_environment_and_db_unavailable(admin, control, monkeypatch):
    from app.domain import runtime_status as runtime
    now = datetime.now(timezone.utc)
    observation = control('observations.json', observed_at=now.isoformat(),
        services={name:dict(status='healthy', observed_at=now.isoformat()) for name in ('worker','dispatcher','broker')},
        worker_startup_id=None, external_limits=None)
    receipt = runtime.collect(observation, now=now)
    assert receipt['queue']['queued_count'] == 0
    assert receipt['failures']['denominator'] == 0 and receipt['failures']['ratio'] is None
    assert receipt['budgets']['status'] == 'unknown'
    runtime.write_status(receipt)
    assert admin.get(PUBLIC).json()['status'] == 'normal'
    body = admin.get(ADMIN).json()
    assert body['services']['worker']['status'] == 'healthy'
    assert body['queue']['queued_count'] == 0
    assert body['concurrency']['effective'] is None
    receipt['observed_at'] = (now-timedelta(seconds=46)).isoformat()
    runtime.write_status(receipt)
    assert admin.get(ADMIN).json()['queue'] is None
    assert admin.get(PUBLIC).json()['status'] == 'service_unavailable'
    control('status.json', garbage='PRIVATE-SECRET')
    assert admin.get(ADMIN).json()['coverage']['status'] == 'unknown'
    observation['namespace'] = 'other-environment'
    with pytest.raises(ValueError):
        runtime.collect(observation, now=now)
    # Anonymous state performs no business DB read and remains available on DB failure.
    monkeypatch.setattr(runtime, 'database_connection', lambda **kw: (_ for _ in ()).throw(RuntimeError('PRIVATE-DB')))
    with TestClient(app) as client:
        assert client.get(PUBLIC).json()['status'] == 'service_unavailable'


def test_control_unset_preserves_business_behavior_and_unknown_control_fails_closed(admin, control, monkeypatch):
    control('maintenance.json', mode='normal', updated_at='invalid', retry_after_seconds=30)
    response = admin.post('/api/v1/projects', json=dict(name='blocked',research_topic='blocked',project_type='sci'))
    assert response.status_code == 503
    assert response.json()['detail']['code'] == 'service_unavailable'
    monkeypatch.delenv('PAPERASSIST_RUNTIME_CONTROL_DIR')
    assert admin.get(PUBLIC).json()['status'] == 'normal'
    assert admin.post('/api/v1/projects', json=dict(name='normal',research_topic='normal',project_type='sci')).status_code == 201


def test_collector_db_aggregates_and_nested_stale_values_are_not_healthy(admin, accounts, control):
    from app.domain import runtime_status as runtime
    from uuid import uuid4
    project,task=seed_task(accounts[0]['id'])
    now=datetime.now(timezone.utc)
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET status='queued',current_attempt=0,error_code=NULL,revision=1 WHERE id=%s",(task,))
        db.execute("""INSERT INTO model_budgets(id,user_id,scope_type,scope_key,limit_micro_usd,revision,created_at,updated_at)
            VALUES(%s,%s,'user',%s,500000,1,%s,%s)""",(str(uuid4()),accounts[0]['id'],accounts[0]['id'],now,now))
    observation=control('observations.json',observed_at=now.isoformat(),worker_startup_id=None,external_limits=None,
        services={n:dict(status='healthy',observed_at=now.isoformat()) for n in ('worker','dispatcher','broker')})
    receipt=runtime.collect(observation,now=now)
    assert receipt['queue']['queued_count']==1
    assert receipt['queue']['oldest_pending_age_seconds'] >= 0
    assert receipt['budgets']['status']=='known' and receipt['budgets']['limit_micro_usd']==500000
    receipt['database']['observed_at']=(now-timedelta(seconds=46)).isoformat()
    receipt['services']['worker']['observed_at']=(now-timedelta(seconds=46)).isoformat()
    runtime.write_status(receipt)
    result=admin.get(ADMIN).json()
    assert result['database']['status']=='unknown'
    assert result['services']['worker']['status']=='unknown'
    assert result['queue'] is None and result['budgets'] is None


def test_collector_unavailable_db_does_not_invent_zero_and_observations_cannot_cross_bindings(admin, control, monkeypatch):
    from app.domain import runtime_status as runtime
    now=datetime.now(timezone.utc)
    observation=control('observations.json',observed_at=now.isoformat(),worker_startup_id=None,
        external_limits=dict(observed_at=now.isoformat(),window_seconds=60,observed_calls=3,observed_429=1,coverage='recorded_provider_responses'),
        services={n:dict(status='unknown',observed_at=None) for n in ('worker','dispatcher','broker')})
    with monkeypatch.context() as patch:
        patch.setattr(runtime,'database_connection',lambda **kw: (_ for _ in ()).throw(RuntimeError('PRIVATE-DB')))
        receipt=runtime.collect(observation,now=now)
    assert receipt['database']['status']=='unavailable'
    assert receipt['queue'] is None and receipt['failures'] is None and receipt['budgets'] is None
    runtime.write_status(receipt)
    assert admin.get(PUBLIC).json()['status']=='service_unavailable'
    assert admin.get(ADMIN).json()['external_limits']['observed_429']==1
    receipt['database_schema']='public'
    control('status.json',**{k:v for k,v in receipt.items() if k not in runtime.binding()})
    # Explicit wrong schema content, bypassing trusted writer to simulate a wrong mount.
    directory=runtime.control_directory()
    (directory/'status.json').write_text(json.dumps(receipt),encoding='utf-8')
    assert admin.get(ADMIN).json()['coverage']['status']=='unknown'


def test_budget_aggregates_reuse_effective_accounting_not_original_reserve(admin, accounts, control):
    from app.domain import runtime_status as runtime
    from uuid import uuid4
    project,task=seed_task(accounts[0]['id'])
    call=seed_call(accounts[0]['id'],project,task,cost=2500)
    now=datetime.now(timezone.utc)
    budget=str(uuid4())
    with database_connection(write=True) as db:
        db.execute("""INSERT INTO model_budgets(id,user_id,scope_type,scope_key,limit_micro_usd,revision,created_at,updated_at)
            VALUES(%s,%s,'user',%s,500000,1,%s,%s)""",(budget,accounts[0]['id'],accounts[0]['id'],now,now))
        db.execute("""INSERT INTO budget_reservations(call_id,budget_id,reserved_micro_usd,accounted_micro_usd,status,updated_at)
            VALUES(%s,%s,100000,2500,'settled',%s)""",(call,budget,now))
    observation=control('observations.json',observed_at=now.isoformat(),worker_startup_id=None,external_limits=None,
        services={n:dict(status='unknown',observed_at=None) for n in ('worker','dispatcher','broker')})
    receipt=runtime.collect(observation,now=now)
    assert receipt['budgets']['reserved_micro_usd']==0
    assert receipt['budgets']['accounted_micro_usd']==2500
    assert receipt['failures']['failed']==receipt['failures']['denominator']==1
    assert receipt['failures']['ratio']==1.0


def test_legacy_storage_summary_does_not_claim_effective_worker_pool(admin):
    response=admin.get('/api/v1/admin/storage')
    assert response.status_code==200,response.text
    assert response.json()['worker_concurrency'] is None
    assert response.json()['worker_concurrency_status']=='see_admin_runtime_status'


def test_stale_receipt_preserves_only_valid_last_observation_times(admin, control, monkeypatch):
    from app.domain import runtime_status as runtime
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(runtime, 'now_utc', lambda: now)
    old = (now-timedelta(seconds=46)).isoformat()
    observation = control('observations.json', observed_at=now.isoformat(), worker_startup_id=None,
        external_limits=None, services={name:dict(status='healthy', observed_at=old)
            for name in ('worker', 'dispatcher', 'broker')})
    receipt = runtime.collect(observation, now=now)
    runtime.write_status(receipt)
    nested = admin.get(ADMIN).json()
    assert nested['services']['worker'] == dict(status='unknown', observed_at=old)
    receipt['observed_at'] = old
    receipt['database']['observed_at'] = old
    receipt['services']['dispatcher']['observed_at'] = 'malformed'
    receipt['services']['broker']['observed_at'] = (now+timedelta(seconds=60)).isoformat()
    runtime.write_status(receipt)
    body = admin.get(ADMIN).json()
    assert body['coverage']['status'] == 'unknown'
    assert body['coverage']['observed_at'] == old
    assert body['services']['worker'] == dict(status='unknown', observed_at=old)
    assert body['database'] == dict(status='unknown', observed_at=old)
    for name in ('dispatcher', 'broker'):
        assert body['services'][name] == dict(status='unknown', observed_at=None)
    assert all(body[field] is None for field in ('queue', 'failures', 'budgets', 'disk', 'external_limits'))
    assert body['concurrency']['effective'] is None
    assert admin.get(PUBLIC).json()['status'] == 'service_unavailable'
    for invalid in ('malformed', (now+timedelta(seconds=60)).isoformat()):
        receipt['observed_at'] = invalid
        runtime.write_status(receipt)
        assert admin.get(ADMIN).json()['coverage']['observed_at'] is None
    receipt['observed_at'] = old
    receipt['namespace'] = 'wrong-deployment'
    control('status.json', **{key:value for key,value in receipt.items() if key not in ('schema_version','environment','database_schema')})
    assert admin.get(ADMIN).json()['services']['worker']['observed_at'] is None
