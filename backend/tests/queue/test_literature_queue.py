"""Real RabbitMQ/Linux worker, isolated schema/assets, synthetic retrieval only."""
import json
import os
import shutil
import time

import pytest

from app.core.config import local_config
from app.core.paths import PROJECT_ROOT
from app.db.database import database_connection
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_literature import project,request,create
from tests.queue.test_real_worker import worker_stack

pytestmark = pytest.mark.skipif(os.environ.get('PAPERASSIST_RUN_QUEUE_TESTS')!='1',reason='Explicit isolated Linux queue disabled.')


def wait(client,task_id,status):
    deadline = time.monotonic()+100
    while time.monotonic()<deadline:
        task = client.get('/api/v1/tasks/'+task_id).json()
        if task['status']==status: return task
        assert task['status']!='failed',task
        time.sleep(.2)
    pytest.fail('Isolated literature worker did not reach the expected durable state.')


def test_linux_wait_restart_retry_cache_and_duplicate_delivery(client,postgres_schema,tmp_path,monkeypatch):
    identity = postgres_schema.schema.removeprefix('pa_test_')
    stack = worker_stack.prepare(PROJECT_ROOT,local_config(),test_id=identity,assets=tmp_path/'data')
    evidence = PROJECT_ROOT/'script/.runtime/stage05-batch01'
    evidence.mkdir(parents=True,exist_ok=True)
    try:
        worker_stack.compose(stack,['build','worker'],timeout=1200)
        pid = project(client)
        original = create(client,pid,{**request(),'limit':50}).json()
        worker_stack.compose(stack,['up','-d','--wait','--wait-timeout','90'],timeout=180)
        waiting = wait(client,original['id'],'waiting_confirmation')
        assert waiting['error_code']=='ncbi_not_configured'
        view = client.get('/api/v1/tasks/'+original['id']+'/workspace').json()
        assert view['allowed_actions']==[]
        worker_stack.compose(stack,['stop','--timeout','45','worker'],timeout=100)
        override = tmp_path/'literature-worker.json'
        override.write_text(json.dumps({'services':{'worker':{
            'command':['python','/app/tests/queue/literature_bootstrap.py','worker'],
            'environment':{'PYTHONPATH':'/app'},
            'volumes':[{'type':'bind','source':str(PROJECT_ROOT/'backend/tests'),'target':'/app/tests','read_only':True}]
        }}}),encoding='utf-8')
        monkeypatch.setenv('PAPERASSIST_NCBI_ENABLED','1')
        monkeypatch.setenv('PAPERASSIST_NCBI_EMAIL','synthetic@example.invalid')
        response = client.post('/api/v1/tasks/'+original['id']+'/resume',headers={'Idempotency-Key':'linux-resume'},json={
            'operation':'resume','wait_id':view['wait']['id'],'expected_task_revision':waiting['revision'],
            'input_version':waiting['input_version']})
        assert response.status_code==202,response.text
        worker_stack.compose(stack,['--file',str(override),'up','-d','--wait','--wait-timeout','90'],timeout=180)
        result = wait(client,original['id'],'succeeded')
        assert result['retry_count']==1
        second = create(client,pid,{**request(),'limit':50},key='linux-cache').json()
        wait(client,second['id'],'succeeded')
        with database_connection(write=True) as db:
            db.execute('UPDATE task_outbox SET published_at=NULL,available_at=clock_timestamp() WHERE task_id IN (%s,%s)',
                       (original['id'],second['id']))
        deadline = time.monotonic()+20
        while time.monotonic()<deadline:
            with database_connection() as db:
                pending = db.execute('SELECT count(*) AS n FROM task_outbox WHERE published_at IS NULL').fetchone()['n']
            if not pending: break
            time.sleep(.2)
        assert pending==0
        with database_connection() as db:
            assert db.execute('SELECT count(*) AS n FROM literature_records').fetchone()['n']==25
            assert db.execute('SELECT count(*) AS n FROM project_references').fetchone()['n']==25
            assert db.execute('SELECT count(*) AS n FROM literature_search_hits').fetchone()['n']==50
            assert db.execute('SELECT count(*) AS n FROM literature_fetch_receipts WHERE cached_from_id IS NOT NULL').fetchone()['n']==3
            assert db.execute("SELECT count(*) AS n FROM task_events WHERE event_type='succeeded'").fetchone()['n']==2
            assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']==0
            assert db.execute('SELECT count(*) AS n FROM budget_reservations').fetchone()['n']==0
            from app.maintenance.database_audit import audit_database
            audit = audit_database(db)
            assert audit['ok'],audit['schema_issues']
    finally:
        worker_stack.stop(stack)
        retained = evidence/('queue-assets-'+identity)
        if (tmp_path/'data').exists(): shutil.copytree(tmp_path/'data',retained)
        (evidence/('queue-'+identity+'.json')).write_text(json.dumps(dict(schema=postgres_schema.schema,
            project=stack.project,assets=str(retained),containers=worker_stack.owned_containers(stack),
            volumes_retained=True,real_ncbi=False,model_calls=False),indent=2),encoding='utf-8')
