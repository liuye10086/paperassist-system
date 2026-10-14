"""Real Linux datasets, immutable history and fenced publication recovery."""
import hashlib
import json
import os
from pathlib import Path
import time
from uuid import uuid4

import pytest

from app.db.database import database_connection
from tests.api.test_analysis import add_file, client  # noqa: F401
from tests.queue.test_real_worker import isolated_worker_stack, worker_stack  # noqa: F401

pytestmark = pytest.mark.skipif(os.environ.get('PAPERASSIST_RUN_QUEUE_TESTS') != '1',
                               reason='Explicit isolated Linux dataset queue test is disabled.')


def wait_task(client, task_id, timeout=85):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get('/api/v1/tasks/' + task_id)
        assert response.status_code == 200, response.text
        task = response.json()
        if task['status'] in ('succeeded', 'failed'):
            return task
        time.sleep(.2)
    pytest.fail('Dataset task did not reach a terminal state within its isolated deadline.')


def source_state(file_id):
    with database_connection() as db:
        return dict(db.execute('SELECT * FROM files WHERE id=%s', (file_id,)).fetchone())


def create_version(client, base, expected, key=None):
    response = client.post(base + '/structure-versions',
                           headers={'Idempotency-Key': key or str(uuid4())},
                           json={'expected_latest_version': expected})
    assert response.status_code == 202, response.text
    return response.json()


def get_version(client, base, version_id):
    response = client.get(base + '/structure-versions/' + version_id)
    assert response.status_code == 200, response.text
    return response.json()


def downloaded_dataset(client, base, dataset):
    response = client.get(base + '/dataset-versions/' + dataset['id'] + '/download')
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['schema_version'] == 1 and payload['epoch'] == '1900'
    assert payload['sheet']['name'] == dataset['sheet_name']
    return response.content, payload['sheet']


def test_real_dataset_versions_keep_full_rows_and_old_preview_through_broker_restart(client, isolated_worker_stack):
    stack = isolated_worker_stack
    rows = [['测量值', '组别']] + [[value, 'A' if value % 2 else 'B'] for value in range(1, 31)]
    base, file = add_file(client, rows)
    before = source_state(file['id'])
    original = client.get(base + '/download').content
    preview = client.get(base + '/preview').content
    assert len(json.loads(preview)['sheets'][0]['preview_rows']) == 20

    key = str(uuid4())
    first = create_version(client, base, 0, key)
    repeated = client.post(base + '/structure-versions', headers={'Idempotency-Key': key},
                           json={'expected_latest_version': 0})
    assert repeated.status_code == 200 and repeated.json()['id'] == first['id']
    assert first['datasets'] == [] and first['task']['status'] == 'queued'
    assert client.get(base + '/preview').content == preview
    worker_stack.compose(stack, ['up', '-d', '--wait', '--wait-timeout', '90'], timeout=180)
    task = wait_task(client, first['task']['id'])
    assert task['status'] == 'succeeded' and task['current_attempt'] == 1, task
    first = get_version(client, base, first['id'])
    assert first['version'] == 1 and first['parent_id'] is None and len(first['datasets']) == 3
    first_data = first['datasets'][0]
    first_bytes, sheet = downloaded_dataset(client, base, first_data)
    assert sheet['row_count'] == 31 and sheet['nonempty_data_row_count'] == 30
    assert next(cell for cell in sheet['cells'] if cell['coordinate'] == 'A31')['value'] == '30'
    assert all(field['unit'] == {'status': 'unconfirmed', 'value': None} for field in sheet['fields'])
    page = client.get(base + '/dataset-versions/' + first_data['id'] + '/rows',
                      params={'start_row': 21, 'limit': 20})
    assert page.status_code == 200, page.text
    assert page.json()['rows'][-1]['row'] == 31

    worker_stack.compose(stack, ['stop', '--timeout', '45', 'worker', 'rabbitmq'], timeout=100)
    second = create_version(client, base, 1)
    assert second['version'] == 2 and second['parent_id'] == first['id']
    assert downloaded_dataset(client, base, first_data)[0] == first_bytes
    worker_stack.compose(stack, ['up', '-d', '--wait', '--wait-timeout', '90'], timeout=180)
    task = wait_task(client, second['task']['id'])
    assert task['status'] == 'succeeded' and task['current_attempt'] == 1, task
    second = get_version(client, base, second['id'])
    assert len(second['datasets']) == 3
    assert second['datasets'][0]['parent_id'] == first_data['id']
    assert downloaded_dataset(client, base, second['datasets'][0])[1] == sheet
    assert downloaded_dataset(client, base, first_data)[0] == first_bytes
    assert source_state(file['id']) == before
    assert client.get(base + '/preview').content == preview
    assert client.get(base + '/download').content == original
    workspace = client.get('/api/v1/tasks/' + second['task']['id'] + '/workspace')
    assert workspace.status_code == 200, workspace.text
    assert workspace.json()['source']['analysis_run_id'] is None
    with database_connection() as db:
        assert not db.execute('SELECT id FROM model_calls').fetchall()
        assert not db.execute('SELECT 1 FROM budget_reservations').fetchall()
        assert len(db.execute('SELECT id FROM file_structure_versions').fetchall()) == 2
        assert len(db.execute('SELECT id FROM dataset_versions').fetchall()) == 6


def test_dataset_publication_death_rolls_back_all_sheets_and_recovers_once(client, isolated_worker_stack, tmp_path):
    stack = isolated_worker_stack
    override = tmp_path / 'dataset-crash-worker.json'
    override.write_text(json.dumps({'services': {'worker': {
        'command': ['python', '/app/dataset_bootstrap.py', 'worker'],
        'volumes': [{'type': 'bind', 'source': str(Path(__file__).with_name('dataset_bootstrap.py').resolve()),
                     'target': '/app/dataset_bootstrap.py', 'read_only': True}],
    }}}), encoding='utf-8')
    worker_stack.compose(stack, ['--file', str(override), 'up', '-d', '--wait', '--wait-timeout', '90'], timeout=180)
    base, file = add_file(client)
    before = source_state(file['id'])
    version = create_version(client, base, 0)
    task_id = version['task']['id']
    marker = tmp_path / 'data' / '.test-dataset-worker-crashed'
    deadline = time.monotonic() + 45
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(.2)
    assert marker.exists(), client.get('/api/v1/tasks/' + task_id).json()
    assert marker.read_text(encoding='ascii') == 'before_commit'
    with database_connection() as db:
        task = db.execute('SELECT * FROM tasks WHERE id=%s', (task_id,)).fetchone()
        assert task['status'] == 'running' and task['current_attempt'] == 1
        row = db.execute('SELECT manifest_json FROM file_structure_versions WHERE task_id=%s', (task_id,)).fetchone()
        assert row['manifest_json'] is None
        assert not db.execute('SELECT id FROM dataset_versions').fetchall()
    assert source_state(file['id']) == before
    task = wait_task(client, task_id, timeout=105)
    assert task['status'] == 'succeeded' and task['current_attempt'] == 2, task
    completed = get_version(client, base, version['id'])
    assert len(completed['datasets']) == 3
    expected = {item['id']: hashlib.sha256(downloaded_dataset(client, base, item)[0]).hexdigest()
                for item in completed['datasets']}
    with database_connection(write=True) as db:
        attempts = db.execute('SELECT status FROM task_attempts WHERE task_id=%s ORDER BY attempt_no', (task_id,)).fetchall()
        assert [row['status'] for row in attempts] == ['failed', 'succeeded']
        assert len(db.execute('SELECT id FROM dataset_versions').fetchall()) == 3
        db.execute('UPDATE task_outbox SET published_at=NULL,available_at=clock_timestamp() WHERE task_id=%s', (task_id,))
    time.sleep(4)
    assert client.get('/api/v1/tasks/' + task_id).json()['current_attempt'] == 2
    assert {item['id']: hashlib.sha256(downloaded_dataset(client, base, item)[0]).hexdigest()
            for item in get_version(client, base, version['id'])['datasets']} == expected
    assert source_state(file['id']) == before
