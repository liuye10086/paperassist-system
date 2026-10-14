"""Opt-in local OCR publication and recovery through the real Linux Worker."""
from hashlib import sha256
import json
import os
from pathlib import Path
import time

import pytest

from app.db.database import database_connection
from tests.api.test_analysis import client  # noqa: F401
from tests.helpers.document_samples import document_bytes
from tests.queue.test_documents_queue import assert_no_model_calls, version_list
from tests.queue.test_file_parse_queue import create_batch, upload_item, wait_task, workbook_bytes
from tests.queue.test_real_worker import isolated_worker_stack, worker_stack  # noqa: F401

pytestmark = pytest.mark.skipif(os.environ.get('PAPERASSIST_RUN_QUEUE_TESTS') != '1',
                               reason='Explicit isolated Linux OCR queue test is disabled.')
FIXTURES = Path(__file__).parents[1] / 'fixtures' / 'ocr'


def test_linux_image_and_selected_pdf_pages_keep_existing_versions(client, isolated_worker_stack):
    stack = isolated_worker_stack
    inputs = [('printed.png', (FIXTURES / 'printed-zh-en.png').read_bytes()),
              ('mixed.pdf', (FIXTURES / 'mixed-three-pages.pdf').read_bytes()),
              ('broken.jpg', b'not an image'), ('data.xlsx', workbook_bytes(7)),
              ('research.docx', document_bytes())]
    base, batch = create_batch(client, inputs)
    uploaded = [upload_item(client, base, batch, index, content)
                for index, (_, content) in enumerate(inputs)]
    for item, (_, content) in zip(uploaded, inputs):
        assert client.get(base + '/files/' + item['file_id'] + '/download').content == content
    worker_stack.compose(stack, ['up', '-d', '--wait', '--wait-timeout', '90'], timeout=180)
    tasks = [wait_task(client, item['task']['id'], timeout=240) for item in uploaded]
    assert [task['status'] for task in tasks] == ['succeeded', 'succeeded', 'failed', 'succeeded', 'succeeded'], tasks
    assert tasks[2]['error_code'] == 'invalid_document'
    image_base = base + '/files/' + uploaded[0]['file_id']
    image_version = version_list(client, image_base)['items'][0]
    image_content = client.get(image_version['download_url']).content
    image_document = json.loads(image_content)
    assert image_document['kind'] == 'ocr_document'
    assert image_document['selected_pages'] == [1]
    assert image_document['counts']['text_blocks'] > 0
    assert all(block['review_status'] == 'unreviewed' for page in image_document['pages'] for block in page['text_blocks'])
    detail = client.get(image_base + '/document-versions/' + image_version['id']).json()
    for image in detail['images']:
        response = client.get(image['download_url'])
        assert response.status_code == 200
        assert sha256(response.content).hexdigest() == image['sha256']
    pdf_base = base + '/files/' + uploaded[1]['file_id']
    text_version = version_list(client, pdf_base)['items'][0]
    text_content = client.get(text_version['download_url']).content
    assert json.loads(text_content)['kind'] == 'pdf_document'
    assert client.get(base + '/files/' + uploaded[3]['file_id'] + '/preview').json()['sheets'][0]['preview_rows'][0][0] == 7
    word_version = version_list(client, base + '/files/' + uploaded[4]['file_id'])['items'][0]
    assert client.get(word_version['download_url']).json()['kind'] == 'docx_document'

    worker_stack.compose(stack, ['stop', '--timeout', '45', 'worker'], timeout=100)
    request = {'expected_latest_version': 1, 'page_numbers': [2, 3]}
    headers = {'Idempotency-Key': 'ocr-selected-pages-after-restart'}
    response = client.post(pdf_base + '/document-versions/ocr', json=request, headers=headers)
    assert response.status_code == 202, response.text
    second = response.json()
    assert second['version'] == 2 and second['status'] == 'queued'
    replay = client.post(pdf_base + '/document-versions/ocr', json=request, headers=headers)
    assert replay.status_code == 200 and replay.json()['id'] == second['id']
    assert client.get(text_version['download_url']).content == text_content
    worker_stack.compose(stack, ['up', '-d', '--wait', '--wait-timeout', '90'], timeout=180)
    assert wait_task(client, second['task_id'], timeout=240)['status'] == 'succeeded'
    second = version_list(client, pdf_base)['items'][0]
    document = client.get(second['download_url']).json()
    assert document['kind'] == 'ocr_document' and document['source_pages'] == 3
    assert document['selected_pages'] == [2, 3]
    assert [page['page_number'] for page in document['pages']] == [2, 3]
    assert document['pages'][0]['text_blocks']
    assert document['pages'][1]['text_status'] == 'no_text'
    assert not document['pages'][1]['text_blocks']
    page = client.get(second['pages_url'], params={'page': 1})
    assert page.status_code == 200 and page.json()['items'][0]['page_number'] == 2
    page = client.get(second['pages_url'], params={'page': 2})
    assert page.status_code == 200 and page.json()['items'][0]['page_number'] == 3
    assert client.get(text_version['download_url']).content == text_content
    assert client.get(image_version['download_url']).content == image_content
    for item, (_, content) in zip(uploaded, inputs):
        assert client.get(base + '/files/' + item['file_id'] + '/download').content == content
    latest_batch = client.get(base + '/file-batches/' + batch['id']).json()
    assert [item['task']['id'] for item in latest_batch['items']] == [item['task']['id'] for item in uploaded]
    assert [item['status'] for item in latest_batch['items']] == ['parsed', 'parsed', 'failed', 'parsed', 'parsed']
    assert_no_model_calls()


def test_ocr_publication_death_recovers_once_and_preserves_candidate(client, isolated_worker_stack, tmp_path):
    stack = isolated_worker_stack
    override = tmp_path / 'ocr-crash-worker.json'
    override.write_text(json.dumps({'services': {'worker': {
        'command': ['python', '/app/file_parse_bootstrap.py', 'worker'],
        'volumes': [{'type': 'bind', 'source': str(Path(__file__).with_name('file_parse_bootstrap.py').resolve()),
                     'target': '/app/file_parse_bootstrap.py', 'read_only': True}],
    }}}), encoding='utf-8')
    worker_stack.compose(stack, ['--file', str(override), 'up', '-d', '--wait', '--wait-timeout', '90'], timeout=180)
    content = (FIXTURES / 'printed-zh-en.png').read_bytes()
    base, batch = create_batch(client, [('recover.png', content)])
    uploaded = upload_item(client, base, batch, 0, content)
    task_id = uploaded['task']['id']
    marker = tmp_path / 'data' / '.test-parse-worker-crashed'
    deadline = time.monotonic() + 240
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
    # Use the actual lease timeout, with no synthetic DB timestamp edits.
    task = wait_task(client, task_id, timeout=300)
    assert task['status'] == 'succeeded' and task['current_attempt'] == 2, task
    file_base = base + '/files/' + uploaded['file_id']
    first = version_list(client, file_base)['items'][0]
    published = client.get(first['download_url']).content
    assert json.loads(published)['kind'] == 'ocr_document'
    assert candidates[0].read_bytes() == candidate_content
    assert client.get(file_base + '/download').content == content
    with database_connection(write=True) as db:
        attempts = db.execute('SELECT status FROM task_attempts WHERE task_id=%s ORDER BY attempt_no', (task_id,)).fetchall()
        assert [row['status'] for row in attempts] == ['failed', 'succeeded']
        assert db.execute('SELECT count(*) AS n FROM file_parse_results WHERE task_id=%s', (task_id,)).fetchone()['n'] == 1
        db.execute('UPDATE task_outbox SET published_at=NULL,available_at=clock_timestamp() WHERE task_id=%s', (task_id,))
    time.sleep(4)
    assert client.get('/api/v1/tasks/' + task_id).json()['current_attempt'] == 2
    assert version_list(client, file_base)['total'] == 1
    assert client.get(first['download_url']).content == published
    assert_no_model_calls()
