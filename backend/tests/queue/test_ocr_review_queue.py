"""Opt-in real isolated OCR review queue, durable waits and Worker restart.

Only the parent OCR parser is replaced with an explicitly synthetic fixture.
Dispatcher, RabbitMQ, task claim, checkpoints, decisions and publication are real.
"""
from hashlib import sha256
import json
import os
from pathlib import Path
import time

import pytest

from app.db.database import database_connection
from tests.api.test_analysis import client  # noqa: F401
from tests.queue.test_file_parse_queue import create_batch, upload_item, wait_task
from tests.queue.test_real_worker import isolated_worker_stack, worker_stack  # noqa: F401

pytestmark = pytest.mark.skipif(os.environ.get('PAPERASSIST_RUN_QUEUE_TESTS') != '1',
                               reason='Explicit isolated OCR review queue test is disabled.')
FIXTURES = Path(__file__).parents[1] / 'fixtures' / 'ocr'


def bootstrap(stack, tmp_path):
    override = tmp_path / 'ocr-review-worker.json'
    override.write_text(json.dumps({'services': {'worker': {
        'command': ['python', '/app/ocr_review_bootstrap.py', 'worker'],
        'volumes': [
            {'type': 'bind', 'source': str(Path(__file__).with_name('ocr_review_bootstrap.py').resolve()),
             'target': '/app/ocr_review_bootstrap.py', 'read_only': True},
            {'type': 'bind', 'source': str((Path(__file__).parents[1] / 'helpers' / 'ocr_samples.py').resolve()),
             'target': '/app/ocr_samples.py', 'read_only': True},
        ],
    }}}), encoding='utf-8')
    worker_stack.compose(stack, ['--file', str(override), 'up', '-d', '--wait', '--wait-timeout', '90'], timeout=180)
    return override


def wait_review(client, task_id, *, edit_revision=None, timeout=105):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get('/api/v1/tasks/' + task_id + '/ocr-review')
        assert response.status_code == 200, response.text
        view = response.json()
        assert view['task']['status'] != 'failed', view
        if (view['task']['status'] == 'waiting_confirmation'
                and (edit_revision is None or view['edit_revision'] == edit_revision)):
            return view
        time.sleep(.2)
    pytest.fail('The isolated OCR review Worker did not reach confirmation in time.')


def decide(client, view, key, operation='approve', edits=None):
    body = dict(operation=operation, wait_id=view['wait']['id'], checkpoint_id=view['checkpoint_id'],
                expected_task_revision=view['task']['revision'], input_version=view['task']['input_version'])
    if operation == 'revise':
        body['edits'] = edits
    response = client.post('/api/v1/tasks/' + view['task']['id'] + '/ocr-review/decision', json=body,
                           headers={'Idempotency-Key': key})
    assert response.status_code == 202, response.text
    return response.json(), body


def assert_released(task_id):
    with database_connection() as db:
        attempt = db.execute('SELECT * FROM task_attempts WHERE task_id=%s ORDER BY attempt_no DESC LIMIT 1',
                             (task_id,)).fetchone()
        assert attempt['status'] == 'waiting_confirmation'
        assert attempt['finished_at'] is not None
        assert attempt['lease_owner'] is None and attempt['lease_expires_at'] is None


def model_budgets():
    with database_connection() as db:
        return db.execute('SELECT * FROM model_budgets ORDER BY id').fetchall()


def download(client, url):
    response = client.get(url)
    assert response.status_code == 200, response.text
    return response.content


def test_review_wait_releases_worker_and_partial_draft_survives_restart(client, isolated_worker_stack, tmp_path):
    stack = isolated_worker_stack
    budgets_before = model_budgets()
    original = (FIXTURES / 'printed-zh-en.png').read_bytes()
    base, batch = create_batch(client, [('synthetic-review.png', original)])
    item = upload_item(client, base, batch, 0, original)
    assert item['task']['status'] == 'queued'
    override = bootstrap(stack, tmp_path)
    parent_task = wait_task(client, item['task']['id'])
    assert parent_task['status'] == 'succeeded' and parent_task['current_attempt'] == 1, parent_task
    file_base = base + '/files/' + item['file_id']
    parent = client.get(file_base + '/document-versions').json()['items'][0]
    parent_bytes = download(client, parent['download_url'])
    parent_document = json.loads(parent_bytes)
    assert parent_document['kind'] == 'ocr_document'
    blocks = [block for page in parent_document['pages'] for block in page['text_blocks']]
    assert len(blocks) == 3
    response = client.post(file_base + '/ocr-reviews', json={'parse_id': parent['id']},
                           headers={'Idempotency-Key': 'queue-review'})
    assert response.status_code == 202, response.text
    task_id = response.json()['id']
    view = wait_review(client, task_id)
    source = view['source']
    assert source['parse_id'] == parent['id'] and source['parse_version'] == parent['version']
    assert source['source_sha256'] == sha256(original).hexdigest()
    assert source['document_sha256'] == sha256(parent_bytes).hexdigest()
    assert view['edits'] == [] and view['summary']['unreviewed_blocks'] == 3
    assert_released(task_id)

    # The Worker has concurrency=1: a later parent parse proves the human wait returned.
    later_response = client.post(file_base + '/document-versions', json={'expected_latest_version': 1},
                                 headers={'Idempotency-Key': 'later-parent'})
    assert later_response.status_code == 202, later_response.text
    later = later_response.json()
    assert wait_task(client, later['task_id'])['status'] == 'succeeded'
    assert wait_review(client, task_id)['source'] == source

    partial = [{'block_id': blocks[0]['id'], 'action': 'accept_original'}]
    decide(client, view, 'save-partial', 'revise', partial)
    saved = wait_review(client, task_id, edit_revision=view['edit_revision'] + 1)
    assert saved['edits'] == partial
    assert saved['summary']['reviewed_blocks'] == 1 and saved['summary']['unreviewed_blocks'] == 2
    assert_released(task_id)
    partial_bytes = download(client, saved['preview_download_url'])
    worker_stack.compose(stack, ['stop', '--timeout', '45', 'worker'], timeout=100)
    stopped = client.get('/api/v1/tasks/' + task_id + '/ocr-review').json()
    assert stopped['source'] == source and stopped['edits'] == partial
    assert stopped['wait'] == saved['wait'] and stopped['checkpoint_id'] == saved['checkpoint_id']
    assert download(client, stopped['preview_download_url']) == partial_bytes
    worker_stack.compose(stack, ['--file', str(override), 'up', '-d', '--wait', '--wait-timeout', '90'], timeout=180)
    reopened = wait_review(client, task_id, edit_revision=saved['edit_revision'])
    assert reopened['source'] == source and reopened['edits'] == partial
    assert reopened['wait'] == saved['wait'] and reopened['checkpoint_id'] == saved['checkpoint_id']
    assert download(client, reopened['preview_download_url']) == partial_bytes

    edits = partial + [
        {'block_id': blocks[1]['id'], 'action': 'replace_text', 'text': '0012 mg / mL'},
        {'block_id': blocks[2]['id'], 'action': 'unreadable'},
    ]
    decide(client, reopened, 'save-complete', 'revise', edits)
    complete = wait_review(client, task_id, edit_revision=reopened['edit_revision'] + 1)
    assert complete['source'] == source
    assert complete['summary'] == dict(total_blocks=3, reviewed_blocks=3, unreviewed_blocks=0,
                                       accepted_blocks=1, corrected_blocks=1, unreadable_blocks=1, no_text_pages=[])
    approved_bytes = download(client, complete['preview_download_url'])
    candidate = json.loads(approved_bytes)
    assert candidate['kind'] == 'ocr_review_document' and candidate['parent_source'] == source
    assert [block['original'] for block in candidate['blocks']] == blocks
    assert [block['effective_text'] for block in candidate['blocks']] == [blocks[0]['text'], '0012 mg / mL', None]
    worker_stack.compose(stack, ['stop', '--timeout', '45', 'worker'], timeout=100)
    approved, body = decide(client, complete, 'approve-complete')
    assert approved['status'] == 'queued'
    worker_stack.compose(stack, ['--file', str(override), 'up', '-d', '--wait', '--wait-timeout', '90'], timeout=180)
    done = wait_task(client, task_id)
    assert done['status'] == 'succeeded', done
    result = client.get('/api/v1/tasks/' + task_id + '/ocr-review').json()['result']
    assert result['parent_parse_id'] == parent['id'] and result['parent_parse_version'] == parent['version']
    assert result['source'] == source and result['summary'] == complete['summary']
    assert download(client, result['download_url']) == approved_bytes
    versions = client.get(file_base + '/ocr-review-versions', params={'parse_id': parent['id']}).json()
    assert versions['total'] == 1 and versions['items'][0]['id'] == result['id']
    detail = client.get(file_base + '/ocr-review-versions/' + result['id'])
    assert detail.status_code == 200 and detail.json()['edits'] == edits
    replay = client.post('/api/v1/tasks/' + task_id + '/ocr-review/decision', json=body,
                         headers={'Idempotency-Key': 'approve-complete'})
    assert replay.status_code == 202 and replay.json() == approved
    with database_connection(write=True) as db:
        assert db.execute('SELECT count(*) AS n FROM ocr_review_versions WHERE task_id=%s', (task_id,)).fetchone()['n'] == 1
        db.execute('UPDATE task_outbox SET published_at=NULL,available_at=clock_timestamp() WHERE task_id=%s', (task_id,))
    time.sleep(4)
    assert client.get('/api/v1/tasks/' + task_id).json()['current_attempt'] == done['current_attempt']
    assert client.get(file_base + '/ocr-review-versions', params={'parse_id': parent['id']}).json()['total'] == 1
    assert download(client, result['download_url']) == approved_bytes
    assert download(client, parent['download_url']) == parent_bytes
    assert download(client, file_base + '/download') == original
    assert len((tmp_path / 'data' / '.ocr-review-fixture-calls').read_text(encoding='utf-8').splitlines()) == 2
    assert not (tmp_path / 'data' / '.unexpected-ocr-review-network').exists()
    with database_connection() as db:
        for table in ('model_calls', 'budget_reservations', 'usage_events'):
            assert db.execute(f'SELECT count(*) AS n FROM {table}').fetchone()['n'] == 0
    assert model_budgets() == budgets_before
