"""Bounded pool startup, independent of frozen task model configuration."""
from datetime import datetime, timezone
import json
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.domain.admin_configuration.contracts import Basic
from app.db.database import database_connection, get_database_config
from tests.api.test_admin_operations import accounts, admin, seed_task
from tests.api.test_admin_configurations import baseline, saved, validated, switch


def test_concurrency_closed_shape_and_legacy_default():
    assert Basic().worker_concurrency == 1
    assert Basic(worker_concurrency=2).worker_concurrency == 2
    for value in (0, 3, True, '2'):
        with pytest.raises(ValidationError):
            Basic(worker_concurrency=value)


def test_approved_desired_startup_and_pending_are_distinct(admin, accounts, monkeypatch, tmp_path):
    from app.workers.config import startup_configuration, concurrency_ceiling
    from app.domain import runtime_status as runtime
    monkeypatch.setenv('PAPERASSIST_RUNTIME_CONTROL_DIR', str(tmp_path))
    monkeypatch.setenv('PAPERASSIST_RUNTIME_NAMESPACE', 'batch04-test')
    (tmp_path/'maintenance.json').write_text(json.dumps(dict(runtime.binding(),mode='normal',
        updated_at=datetime.now(timezone.utc).isoformat(),retry_after_seconds=30)),encoding='utf-8')
    monkeypatch.setenv('PAPERASSIST_WORKER_CONCURRENCY_CEILING', '2')
    assert concurrency_ceiling() == 2
    assert startup_configuration()['concurrency'] == 1
    one=baseline(admin); two=saved(admin,one,'basic','worker_concurrency',2)
    validated(admin,two); assert switch(admin,two,0,'concurrency-two').status_code == 200
    project, task=seed_task(accounts[0]['id'])
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET task_type='parse_file',status='queued',current_attempt=0,error_code=NULL WHERE id=%s",(task,))
    with database_connection() as db:
        before=dict(db.execute('SELECT input_snapshot,status,revision FROM tasks WHERE id=%s',(task,)).fetchone())
    startup=startup_configuration()
    assert startup['concurrency'] == 2 and startup['configuration_sha256'] == two['sha256']
    runtime.record_worker_startup(startup)
    now=datetime.now(timezone.utc)
    observation=dict(runtime.binding(),observed_at=now.isoformat(),worker_startup_id=startup['startup_id'],
        services={n:dict(status='healthy',observed_at=now.isoformat()) for n in ('worker','dispatcher','broker')},external_limits=None)
    runtime.write_status(runtime.collect(observation,now=now))
    assert admin.get('/api/v1/admin/runtime/status').json()['concurrency']['pending_restart'] is False
    validated(admin,one); assert switch(admin,one,1,'concurrency-one').status_code == 200
    body=admin.get('/api/v1/admin/runtime/status').json()['concurrency']
    assert body['desired'] == 1 and body['effective'] == 2 and body['pending_restart'] is True
    with database_connection() as db:
        assert dict(db.execute('SELECT input_snapshot,status,revision FROM tasks WHERE id=%s',(task,)).fetchone()) == before
    monkeypatch.setenv('PAPERASSIST_WORKER_CONCURRENCY_CEILING','3')
    with pytest.raises(ValueError): concurrency_ceiling()


def test_deployment_requires_explicit_second_process_permission(admin, monkeypatch):
    from app.workers.config import startup_configuration
    monkeypatch.setenv('PAPERASSIST_WORKER_CONCURRENCY_CEILING','1')
    one=baseline(admin);two=saved(admin,one,'basic','worker_concurrency',2)
    validation=admin.post('/api/v1/admin/configurations/'+two['id']+'/validate',json={}).json()
    assert validation['status']=='failed'
    assert validation['domains']['basic']['errors']==['worker_concurrency_exceeds_deployment']
    assert switch(admin,two,0,'blocked-two').status_code==409
    assert startup_configuration()['concurrency']==1
    monkeypatch.setenv('PAPERASSIST_WORKER_CONCURRENCY_CEILING','2')
    validated(admin,two)
    assert switch(admin,two,0,'allowed-two').status_code==200
    assert startup_configuration()['concurrency']==2
    monkeypatch.setenv('PAPERASSIST_WORKER_CONCURRENCY_CEILING','1')
    assert startup_configuration()['concurrency']==1


def test_worker_entry_uses_exact_loaded_startup_args(monkeypatch):
    from app.workers import __main__ as entry
    from app.workers import celery_app
    from app.db import database
    fake=Mock()
    monkeypatch.setattr(entry,'load_secrets',lambda:None)
    monkeypatch.setattr(entry,'queue_config',lambda:None)
    monkeypatch.setattr(entry,'startup_configuration',lambda:dict(concurrency=2,startup_id='test',configuration_id=None,configuration_sha256=None))
    monkeypatch.setattr(entry,'record_worker_startup',lambda value:None)
    monkeypatch.setattr(celery_app,'get_app',lambda:fake)
    monkeypatch.setattr(entry.socket,'gethostname',lambda:'isolated-test')
    assert entry.main(['worker']) == 0
    fake.worker_main.assert_called_once_with(['worker','--loglevel=WARNING','--concurrency=2','--pool=prefork','--hostname=celery@isolated-test'])
