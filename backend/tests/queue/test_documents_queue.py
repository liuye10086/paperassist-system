"""Opt-in real Linux Word parsing, immutable versions and publication recovery."""
import hashlib
import json
import os
from pathlib import Path
import time

import pytest

from app.db.database import database_connection
from app.maintenance.database_audit import audit_database
from tests.api.test_analysis import client  # noqa: F401
from tests.helpers.document_samples import document_bytes, picture_bytes
from tests.queue.test_file_parse_queue import create_batch, upload_item, wait_task, workbook_bytes
from tests.queue.test_real_worker import isolated_worker_stack, worker_stack  # noqa: F401

pytestmark = pytest.mark.skipif(os.environ.get('PAPERASSIST_RUN_QUEUE_TESTS') != '1',
                               reason='Explicit isolated Linux document queue test is disabled.')


def version_list(client, base):
    response = client.get(base + '/document-versions')
    assert response.status_code == 200, response.text
    return response.json()


def assert_no_model_calls():
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0
        assert db.execute('SELECT count(*) AS n FROM budget_reservations').fetchone()['n'] == 0
        audit = audit_database(db)
        assert audit['ok'], audit


def test_linux_mixed_documents_and_reparse_keep_originals_and_old_versions(client, isolated_worker_stack):
    stack = isolated_worker_stack
    original = document_bytes(warnings=True)
    inputs = [('research.docx', original), ('data.xlsx', workbook_bytes(3)),
              ('broken.docx', b'not a Word document')]
    project_base, batch = create_batch(client, inputs)
    uploaded = [upload_item(client, project_base, batch, index, content)
                for index, (_, content) in enumerate(inputs)]
    worker_stack.compose(stack, ['up', '-d', '--wait', '--wait-timeout', '90'], timeout=180)
    tasks = [wait_task(client, item['task']['id']) for item in uploaded]
    assert [task['status'] for task in tasks] == ['succeeded', 'succeeded', 'failed'], tasks
    assert tasks[2]['error_code'] == 'invalid_document'
    base = project_base + '/files/' + uploaded[0]['file_id']
    first = version_list(client, base)['items'][0]
    assert first['version'] == 1 and first['status'] == 'succeeded'
    saved = client.get(first['download_url'])
    assert saved.status_code == 200
    structure = saved.json()
    assert structure['kind'] == 'docx_document'
    assert structure['counts']['tables'] == 2  # main table and nested table
    assert structure['counts']['images'] == 2
    assert structure['warnings']  # revisions and excluded header are visible limitations
    detail = client.get(base + '/document-versions/' + first['id']).json()
    images = [client.get(image['download_url']) for image in detail['images']]
    assert all(response.status_code == 200 for response in images)
    assert {hashlib.sha256(response.content).hexdigest() for response in images} == {
        hashlib.sha256(picture_bytes()).hexdigest(), hashlib.sha256(picture_bytes('JPEG')).hexdigest()}
    assert client.get(base + '/download').content == original
    rejected_preview = client.get(base + '/preview')
    assert rejected_preview.status_code == 422
    assert rejected_preview.json()['detail']['code'] == 'unsupported_file_type'
    excel_base = project_base + '/files/' + uploaded[1]['file_id']
    assert client.get(excel_base + '/preview').json()['sheets'][0]['preview_rows'][0][0] == 3
    assert client.get(project_base + '/files/' + uploaded[2]['file_id'] + '/download').content == inputs[2][1]

    # API can queue a new version while the Worker is stopped; previous version stays readable.
    worker_stack.compose(stack, ['stop', '--timeout', '45', 'worker'], timeout=100)
    request = {'expected_latest_version': 1}
    headers = {'Idempotency-Key': 'word-reparse-after-restart'}
    response = client.post(base + '/document-versions', json=request, headers=headers)
    assert response.status_code == 202, response.text
    second = response.json()
    assert second['version'] == 2 and second['status'] == 'queued'
    assert client.get(first['download_url']).content == saved.content
    replay = client.post(base + '/document-versions', json=request, headers=headers)
    assert replay.status_code == 200 and replay.json()['id'] == second['id']
    worker_stack.compose(stack, ['up', '-d', '--wait', '--wait-timeout', '90'], timeout=180)
    assert wait_task(client, second['task_id'])['status'] == 'succeeded'
    assert version_list(client, base)['total'] == 2
    assert client.get(first['download_url']).content == saved.content
    assert client.get(base + '/download').content == original
    latest_batch = client.get(project_base + '/file-batches/' + batch['id']).json()
    assert len(latest_batch['items']) == 3
    assert latest_batch['items'][0]['task']['id'] == uploaded[0]['task']['id']
    assert_no_model_calls()


def test_document_publication_death_recovers_once_and_retains_candidate(client, isolated_worker_stack, tmp_path):
    stack = isolated_worker_stack
    override = tmp_path / 'document-crash-worker.json'
    override.write_text(json.dumps({'services': {'worker': {
        'command': ['python', '/app/file_parse_bootstrap.py', 'worker'],
        'volumes': [{'type': 'bind', 'source': str(Path(__file__).with_name('file_parse_bootstrap.py').resolve()),
                     'target': '/app/file_parse_bootstrap.py', 'read_only': True}],
    }}}), encoding='utf-8')
    worker_stack.compose(stack, ['--file', str(override), 'up', '-d', '--wait', '--wait-timeout', '90'], timeout=180)
    content = document_bytes()
    project_base, batch = create_batch(client, [('crash.docx', content)])
    uploaded = upload_item(client, project_base, batch, 0, content)
    task_id = uploaded['task']['id']
    marker = tmp_path / 'data' / '.test-parse-worker-crashed'
    deadline = time.monotonic() + 45
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(.2)
    assert marker.exists(), client.get('/api/v1/tasks/' + task_id).json()
    with database_connection() as db:
        task = db.execute('SELECT * FROM tasks WHERE id=%s', (task_id,)).fetchone()
        assert task['status'] == 'running' and task['current_attempt'] == 1
        result = db.execute('SELECT * FROM file_parse_results WHERE task_id=%s', (task_id,)).fetchone()
        assert result['result_json'] is None
        parse_id = result['id']
    candidates = list((tmp_path / 'data' / 'documents' / parse_id).glob('*.json'))
    assert len(candidates) == 1
    candidate_content = candidates[0].read_bytes()
    task = wait_task(client, task_id, timeout=110)  # use actual sixty-second lease recovery
    assert task['status'] == 'succeeded' and task['current_attempt'] == 2, task
    base = project_base + '/files/' + uploaded['file_id']
    first = version_list(client, base)['items'][0]
    assert client.get(first['download_url']).content == candidate_content
    assert client.get(base + '/download').content == content
    with database_connection(write=True) as db:
        assert db.execute('SELECT count(*) AS n FROM file_parse_results WHERE task_id=%s', (task_id,)).fetchone()['n'] == 1
        db.execute('UPDATE task_outbox SET published_at=NULL,available_at=clock_timestamp() WHERE task_id=%s', (task_id,))
    time.sleep(3)
    assert client.get('/api/v1/tasks/' + task_id).json()['current_attempt'] == 2
    assert version_list(client, base)['total'] == 1
    assert_no_model_calls()
