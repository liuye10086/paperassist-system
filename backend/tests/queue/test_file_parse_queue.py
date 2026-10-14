"""Opt-in real Linux parsing, durable broker recovery and commit-death tests."""
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import time
from uuid import uuid4

from openpyxl import Workbook
import pytest

from app.db.database import database_connection
from tests.api.test_analysis import client  # noqa: F401
from tests.queue.test_real_worker import isolated_worker_stack, worker_stack  # noqa: F401

pytestmark = pytest.mark.skipif(os.environ.get('PAPERASSIST_RUN_QUEUE_TESTS') != '1',
                               reason='Explicit isolated Linux parse queue test is disabled.')


def workbook_bytes(value=1):
    book = Workbook()
    book.active.title = '合成数据'
    book.active.append(['测量值', '分组'])
    book.active.append([value, 'A'])
    book.active.append([value + 1, 'B'])
    stream = BytesIO()
    book.save(stream)
    book.close()
    return stream.getvalue()


def create_batch(client, inputs):
    project_response = client.post('/api/v1/projects', json={
        'name': '后台解析隔离样本', 'research_topic': '仅合成数据', 'project_type': 'sci',
    })
    assert project_response.status_code == 201
    base = '/api/v1/projects/' + project_response.json()['id']
    items = [{'client_id': str(uuid4()), 'filename': name, 'size_bytes': len(content)}
             for name, content in inputs]
    response = client.post(base + '/file-batches', headers={'Idempotency-Key': str(uuid4())}, json={'items': items})
    assert response.status_code == 201, response.text
    batch = response.json()
    return base, batch


def upload_item(client, base, batch, ordinal, content):
    item = batch['items'][ordinal]
    response = client.post(base + '/file-batches/' + batch['id'] + '/items/' + item['id'],
                           files={'file': (item['filename'], content)})
    assert response.status_code == 202, response.text
    assert response.json()['status'] == 'queued'
    return response.json()


def wait_task(client, task_id, *, timeout=80):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get('/api/v1/tasks/' + task_id)
        assert response.status_code == 200, response.text
        task = response.json()
        if task['status'] in ('succeeded', 'failed'):
            return task
        time.sleep(0.2)
    pytest.fail('Isolated parse task did not reach a terminal state in time.')


def test_linux_mixed_batch_keeps_originals_and_resumes_after_broker_restart(client, isolated_worker_stack):
    stack = isolated_worker_stack
    inputs = [('same.xlsx', workbook_bytes(1)), ('same.xlsx', workbook_bytes(9)),
              ('broken.xlsx', b'not a workbook'), ('unsupported.xls', b'old format')]
    base, batch = create_batch(client, inputs)
    assert batch['items'][3]['status'] == 'rejected'
    uploaded = [upload_item(client, base, batch, ordinal, content)
                for ordinal, (_, content) in enumerate(inputs[:3])]
    assert len({item['file_id'] for item in uploaded}) == 3
    # Queued bytes are downloadable before broker/worker startup, and never parsed by GET.
    for item, (_, content) in zip(uploaded, inputs):
        prefix = base + '/files/' + item['file_id']
        assert client.get(prefix + '/download').content == content
        assert client.get(prefix + '/preview').status_code == 409
    worker_stack.compose(stack, ['up', '-d', '--wait', '--wait-timeout', '90'], timeout=180)
    tasks = [wait_task(client, item['task']['id']) for item in uploaded]
    assert [task['status'] for task in tasks] == ['succeeded', 'succeeded', 'failed'], tasks
    assert tasks[2]['error_code'] == 'invalid_workbook'
    for ordinal, item in enumerate(uploaded[:2]):
        prefix = base + '/files/' + item['file_id']
        preview = client.get(prefix + '/preview')
        assert preview.status_code == 200, preview.text
        assert preview.json()['sheets'][0]['preview_rows'][0][0] == [1, 9][ordinal]
        workspace = client.get('/api/v1/tasks/' + item['task']['id'] + '/workspace')
        assert workspace.status_code == 200, workspace.text
        assert workspace.json()['source']['analysis_run_id'] is None
    current = client.get(base + '/file-batches/' + batch['id']).json()
    assert current['revision'] > batch['revision']
    assert [item['status'] for item in current['items']] == ['parsed', 'parsed', 'failed', 'rejected']
    assert client.get(base + '/tasks').status_code == 200

    worker_stack.compose(stack, ['stop', '--timeout', '45', 'worker', 'rabbitmq'], timeout=100)
    content = workbook_bytes(27)
    second_base, second_batch = create_batch(client, [('later.xlsx', content)])
    item = upload_item(client, second_base, second_batch, 0, content)
    worker_stack.compose(stack, ['up', '-d', '--wait', '--wait-timeout', '90'], timeout=180)
    task = wait_task(client, item['task']['id'])
    assert task['status'] == 'succeeded' and task['current_attempt'] == 1, task
    assert client.get(second_base + '/files/' + item['file_id'] + '/download').content == content
    with database_connection() as db:
        assert not db.execute('SELECT id FROM model_calls').fetchall()
        assert not db.execute('SELECT 1 FROM budget_reservations').fetchall()
        assert len(db.execute('SELECT id FROM file_parse_results WHERE result_json IS NOT NULL').fetchall()) == 3


def test_parse_publication_process_death_rolls_back_and_recovers_once(client, isolated_worker_stack, tmp_path):
    stack = isolated_worker_stack
    override = tmp_path / 'parse-crash-worker.json'
    override.write_text(json.dumps({'services': {'worker': {
        'command': ['python', '/app/file_parse_bootstrap.py', 'worker'],
        'volumes': [{'type': 'bind', 'source': str(Path(__file__).with_name('file_parse_bootstrap.py').resolve()),
                     'target': '/app/file_parse_bootstrap.py', 'read_only': True}],
    }}}), encoding='utf-8')
    worker_stack.compose(stack, ['--file', str(override), 'up', '-d', '--wait', '--wait-timeout', '90'], timeout=180)
    content = workbook_bytes(13)
    base, batch = create_batch(client, [('recover.xlsx', content)])
    item = upload_item(client, base, batch, 0, content)
    task_id = item['task']['id']
    marker = tmp_path / 'data' / '.test-parse-worker-crashed'
    deadline = time.monotonic() + 40
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.2)
    assert marker.exists(), client.get('/api/v1/tasks/' + task_id).json()
    assert marker.read_text(encoding='ascii') == 'before_commit'
    with database_connection() as db:
        task = db.execute('SELECT * FROM tasks WHERE id=%s', (task_id,)).fetchone()
        assert task['status'] == 'running' and task['current_attempt'] == 1
        result = db.execute('SELECT result_json FROM file_parse_results WHERE task_id=%s', (task_id,)).fetchone()
        assert result is not None and result['result_json'] is None
        assert db.execute('SELECT preview_json FROM files WHERE id=%s', (item['file_id'],)).fetchone()['preview_json'] is None
    # Actual 60-second lease and dispatcher; no synthetic DB time edits.
    task = wait_task(client, task_id, timeout=105)
    assert task['status'] == 'succeeded' and task['current_attempt'] == 2, task
    prefix = base + '/files/' + item['file_id']
    assert client.get(prefix + '/download').content == content
    expected_hash = hashlib.sha256(client.get(prefix + '/preview').content).hexdigest()
    with database_connection(write=True) as db:
        attempts = db.execute('SELECT status FROM task_attempts WHERE task_id=%s ORDER BY attempt_no', (task_id,)).fetchall()
        assert [row['status'] for row in attempts] == ['failed', 'succeeded']
        assert len(db.execute('SELECT id FROM file_parse_results WHERE task_id=%s', (task_id,)).fetchall()) == 1
        db.execute('UPDATE task_outbox SET published_at=NULL,available_at=clock_timestamp() WHERE task_id=%s', (task_id,))
    time.sleep(4)
    assert client.get('/api/v1/tasks/' + task_id).json()['current_attempt'] == 2
    assert hashlib.sha256(client.get(prefix + '/preview').content).hexdigest() == expected_hash
    assert client.get(prefix + '/download').content == content
