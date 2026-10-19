"""Actual Linux worker restart and retained model receipts with a synthetic provider."""
import json
import os
import time

import pytest

from app.core.config import local_config
from app.core.paths import PROJECT_ROOT
from app.db.database import database_connection
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_literature import project
from tests.integration.test_literature_assistance import create, budgets
from tests.queue.test_real_worker import worker_stack

pytestmark = pytest.mark.skipif(os.environ.get('PAPERASSIST_RUN_QUEUE_TESTS') != '1',
                               reason='Explicit isolated Linux queue test disabled.')


def wait_task(client, identity, expected):
    until = time.monotonic() + 100
    while time.monotonic() < until:
        response = client.get('/api/v1/tasks/' + identity)
        assert response.status_code == 200, response.text
        task = response.json()
        if task['status'] == expected:
            return task
        assert task['status'] != 'failed', task
        time.sleep(.2)
    pytest.fail('The isolated assistance task did not reach ' + expected)


def test_linux_authorization_wait_and_restart_keep_single_model_publication(client, postgres_schema, tmp_path):
    identity = postgres_schema.schema.removeprefix('pa_test_')
    stack = worker_stack.prepare(PROJECT_ROOT, local_config(), test_id=identity, assets=tmp_path / 'data')
    receipt_dir = PROJECT_ROOT / 'script/.runtime/stage05-batch02'
    try:
        worker_stack.compose(stack, ['build', 'worker'], timeout=1200)
        pid = project(client)
        closed = create(client, pid, key='queue-default-closed')
        worker_stack.compose(stack, ['up', '-d', '--wait', '--wait-timeout', '90'], timeout=180)
        waiting = wait_task(client, closed['id'], 'waiting_confirmation')
        assert waiting['error_code'] == 'literature_assistance_not_authorized'
        with database_connection() as db:
            assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0
        worker_stack.compose(stack, ['stop', '--timeout', '45', 'worker'], timeout=100)
        task = create(client, pid, key='queue-synthetic-assistance')
        budgets(client, task)
        override = tmp_path / 'assistance-worker.json'

        def boot(mode):
            override.write_text(json.dumps({'services': {'worker': {
                'command': ['python', '/app/tests/queue/literature_assistance_bootstrap.py', 'worker'],
                'environment': {'PYTHONPATH': '/app', 'PAPERASSIST_OFFLINE_ASSISTANCE_PHASE': mode},
                'volumes': [{'type': 'bind', 'source': str(PROJECT_ROOT / 'backend/tests'),
                             'target': '/app/tests', 'read_only': True}],
            }}}), encoding='utf-8')
            worker_stack.compose(stack, ['--file', str(override), 'up', '-d', '--wait', '--wait-timeout', '90'], timeout=180)

        boot('pending')
        until = time.monotonic() + 60
        persisted = None
        while time.monotonic() < until:
            with database_connection() as db:
                persisted = db.execute('SELECT id,provider_response_id FROM model_calls WHERE task_id=%s',
                                       (task['id'],)).fetchone()
            if persisted and persisted['provider_response_id']:
                break
            time.sleep(.2)
        assert persisted and persisted['provider_response_id']
        worker_stack.compose(stack, ['stop', '--timeout', '45', 'worker'], timeout=100)
        boot('complete')
        result = wait_task(client, task['id'], 'succeeded')
        assert result['retry_count'] == 1
        with database_connection(write=True) as db:
            db.execute('UPDATE task_outbox SET published_at=NULL,available_at=clock_timestamp() WHERE task_id=%s',
                       (task['id'],))
        until = time.monotonic() + 20
        while time.monotonic() < until:
            with database_connection() as db:
                pending = db.execute('SELECT count(*) AS n FROM task_outbox WHERE task_id=%s AND published_at IS NULL',
                                     (task['id'],)).fetchone()['n']
            if not pending:
                break
            time.sleep(.2)
        assert pending == 0
        with database_connection() as db:
            calls = db.execute('SELECT id FROM model_calls WHERE task_id=%s', (task['id'],)).fetchall()
            assert [r['id'] for r in calls] == [persisted['id']]
            assert db.execute("SELECT count(*) AS n FROM task_events WHERE task_id=%s AND event_type='succeeded'",
                              (task['id'],)).fetchone()['n'] == 1
            assert db.execute('SELECT result_json FROM literature_assistance_requests WHERE task_id=%s',
                              (task['id'],)).fetchone()['result_json']['mesh_candidates'][0]['verified'] is False
            assert db.execute('SELECT count(*) AS n FROM literature_claim_reviews').fetchone()['n'] == 0
            from app.maintenance.database_audit import audit_database
            audit = audit_database(db)
            assert audit['ok'], {'schema': audit['schema_issues'],
                                 'invalid': [c for c in audit['data_checks'] if c['invalid']]}
    finally:
        worker_stack.stop(stack)
        receipt_dir.mkdir(parents=True, exist_ok=True)
        (receipt_dir / ('assistance-queue-' + identity + '.json')).write_text(json.dumps({
            'schema': postgres_schema.schema, 'project': stack.project,
            'containers': worker_stack.owned_containers(stack), 'volumes_retained': True,
            'real_ncbi': False, 'paid_calls': False, 'model_provider': 'synthetic_fixture',
        }, indent=2), encoding='utf-8')
