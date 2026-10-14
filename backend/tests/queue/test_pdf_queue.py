"""Opt-in PDF publication tests using the existing isolated Linux queue stack."""
import hashlib
import json
import os
from pathlib import Path
import time

import pytest

from app.db.database import database_connection
from tests.api.test_analysis import client  # noqa: F401
from tests.helpers.document_samples import document_bytes
from tests.helpers.pdf_samples import TEXT, pdf_bytes
from tests.queue.test_documents_queue import assert_no_model_calls, version_list
from tests.queue.test_file_parse_queue import create_batch, upload_item, wait_task, workbook_bytes
from tests.queue.test_real_worker import isolated_worker_stack, worker_stack  # noqa: F401

pytestmark = pytest.mark.skipif(os.environ.get('PAPERASSIST_RUN_QUEUE_TESTS') != '1',
                               reason='Explicit isolated Linux PDF queue test is disabled.')

PDF_FIXTURES = Path(__file__).parents[1] / 'fixtures' / 'pdf'


def test_linux_mixed_pdf_batch_and_stopped_worker_reparse(client, isolated_worker_stack):
    stack = isolated_worker_stack
    original = (PDF_FIXTURES / 'text-tables-cid.pdf').read_bytes()
    inputs = [('same.pdf', original), ('research.docx', document_bytes()),
              ('data.xlsx', workbook_bytes(7)), ('same.pdf', b'not a PDF'),
              ('101-pages.pdf', pdf_bytes([TEXT] * 101))]
    project_base, batch = create_batch(client, inputs)
    uploaded = [upload_item(client, project_base, batch, index, content)
                for index, (_, content) in enumerate(inputs)]
    assert len({item['file_id'] for item in uploaded}) == len(inputs)
    for item, (_, content) in zip(uploaded, inputs):
        response = client.get(project_base + '/files/' + item['file_id'] + '/download')
        assert response.status_code == 200
        assert hashlib.sha256(response.content).digest() == hashlib.sha256(content).digest()
    worker_stack.compose(stack, ['up', '-d', '--wait', '--wait-timeout', '90'], timeout=180)
    tasks = [wait_task(client, item['task']['id']) for item in uploaded]
    assert [task['status'] for task in tasks] == ['succeeded', 'succeeded', 'succeeded', 'failed', 'failed'], tasks
    assert [task['error_code'] for task in tasks[3:]] == ['invalid_document', 'document_too_large']
    base = project_base + '/files/' + uploaded[0]['file_id']
    first = version_list(client, base)['items'][0]
    assert first['version'] == 1 and first['status'] == 'succeeded'
    saved = client.get(first['download_url'])
    assert saved.status_code == 200
    first_hash = hashlib.sha256(saved.content).digest()
    structure = saved.json()
    assert structure['kind'] == 'pdf_document'
    assert structure['counts']['tables'] >= 1
    assert any('合成研究资料' in block['text'] for page in structure['pages'] for block in page['text_blocks'])
    assert all(table['candidate'] for page in structure['pages'] for table in page['tables'])
    page = client.get(first['pages_url'], params={'page': 1})
    assert page.status_code == 200 and page.json()['items'][0]['page_number'] == 1
    word_base = project_base + '/files/' + uploaded[1]['file_id']
    word = version_list(client, word_base)['items'][0]
    assert client.get(word['download_url']).json()['kind'] == 'docx_document'
    excel_base = project_base + '/files/' + uploaded[2]['file_id']
    assert client.get(excel_base + '/preview').json()['sheets'][0]['preview_rows'][0][0] == 7

    worker_stack.compose(stack, ['stop', '--timeout', '45', 'worker'], timeout=100)
    request = {'expected_latest_version': 1}
    headers = {'Idempotency-Key': 'pdf-reparse-after-restart'}
    response = client.post(base + '/document-versions', json=request, headers=headers)
    assert response.status_code == 202, response.text
    second = response.json()
    assert second['version'] == 2 and second['status'] == 'queued'
    assert client.get('/api/v1/tasks/' + second['task_id']).json()['status'] == 'queued'
    assert hashlib.sha256(client.get(first['download_url']).content).digest() == first_hash
    replay = client.post(base + '/document-versions', json=request, headers=headers)
    assert replay.status_code == 200 and replay.json()['id'] == second['id']
    worker_stack.compose(stack, ['up', '-d', '--wait', '--wait-timeout', '90'], timeout=180)
    assert wait_task(client, second['task_id'])['status'] == 'succeeded'
    assert version_list(client, base)['total'] == 2
    assert hashlib.sha256(client.get(first['download_url']).content).digest() == first_hash
    assert hashlib.sha256(client.get(base + '/download').content).digest() == hashlib.sha256(original).digest()
    latest_batch = client.get(project_base + '/file-batches/' + batch['id']).json()
    assert [item['status'] for item in latest_batch['items']] == ['parsed', 'parsed', 'parsed', 'failed', 'failed']
    assert [item['task']['id'] for item in latest_batch['items']] == [item['task']['id'] for item in uploaded]
    assert_no_model_calls()


def test_pdf_publication_death_recovers_once_and_retains_candidate(client, isolated_worker_stack, tmp_path):
    stack = isolated_worker_stack
    override = tmp_path / 'pdf-crash-worker.json'
    override.write_text(json.dumps({'services': {'worker': {
        'command': ['python', '/app/file_parse_bootstrap.py', 'worker'],
        'volumes': [{'type': 'bind', 'source': str(Path(__file__).with_name('file_parse_bootstrap.py').resolve()),
                     'target': '/app/file_parse_bootstrap.py', 'read_only': True}],
    }}}), encoding='utf-8')
    worker_stack.compose(stack, ['--file', str(override), 'up', '-d', '--wait', '--wait-timeout', '90'], timeout=180)
    content = (PDF_FIXTURES / 'text-tables-cid.pdf').read_bytes()
    project_base, batch = create_batch(client, [('crash.pdf', content)])
    uploaded = upload_item(client, project_base, batch, 0, content)
    task_id = uploaded['task']['id']
    marker = tmp_path / 'data' / '.test-parse-worker-crashed'
    deadline = time.monotonic() + 45
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(.2)
    assert marker.exists(), client.get('/api/v1/tasks/' + task_id).json()
    assert marker.read_text(encoding='ascii') == 'before_commit'
    with database_connection() as db:
        task = db.execute('SELECT * FROM tasks WHERE id=%s', (task_id,)).fetchone()
        assert task['status'] == 'running' and task['current_attempt'] == 1
        result = db.execute('SELECT * FROM file_parse_results WHERE task_id=%s', (task_id,)).fetchone()
        assert result['result_json'] is None
        parse_id = result['id']
    candidates = list((tmp_path / 'data' / 'documents' / parse_id).glob('*.json'))
    assert len(candidates) == 1
    candidate_content = candidates[0].read_bytes()
    task = wait_task(client, task_id, timeout=110)  # Actual sixty-second lease recovery.
    assert task['status'] == 'succeeded' and task['current_attempt'] == 2, task
    base = project_base + '/files/' + uploaded['file_id']
    first = version_list(client, base)['items'][0]
    assert client.get(first['download_url']).content == candidate_content
    assert candidates[0].read_bytes() == candidate_content
    assert list(candidates[0].parent.glob('*.json')) == candidates
    assert client.get(base + '/download').content == content
    with database_connection(write=True) as db:
        attempts = db.execute('SELECT status FROM task_attempts WHERE task_id=%s ORDER BY attempt_no', (task_id,)).fetchall()
        assert [row['status'] for row in attempts] == ['failed', 'succeeded']
        assert db.execute('SELECT count(*) AS n FROM file_parse_results WHERE task_id=%s', (task_id,)).fetchone()['n'] == 1
        db.execute('UPDATE task_outbox SET published_at=NULL,available_at=clock_timestamp() WHERE task_id=%s', (task_id,))
    time.sleep(4)
    assert client.get('/api/v1/tasks/' + task_id).json()['current_attempt'] == 2
    assert version_list(client, base)['total'] == 1
    assert client.get(first['download_url']).content == candidate_content
    assert_no_model_calls()
