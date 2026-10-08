"""Opt-in process-death drill against the isolated real RabbitMQ/Celery stack."""
import hashlib
import json
import os
from pathlib import Path
import time

import pytest

from app.db.database import database_connection
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_boxplot import cloud  # noqa: F401
from tests.integration.test_explanations import writer  # noqa: F401
from tests.integration.test_reports import report_ready
from tests.queue.test_real_worker import isolated_worker_stack, worker_stack  # noqa: F401

pytestmark = pytest.mark.skipif(os.environ.get('PAPERASSIST_RUN_QUEUE_TESTS') != '1',
                               reason='Explicit isolated Linux queue crash test is disabled.')


def test_process_death_after_file_rename_rolls_back_then_recovers(client, cloud, writer, isolated_worker_stack, tmp_path):
    stack = isolated_worker_stack
    override = tmp_path / 'crash-worker.json'
    override.write_text(json.dumps({'services': {'worker': {
        'command': ['python', '/app/worker_crash_bootstrap.py', 'worker'],
        'volumes': [{'type': 'bind', 'source': str(Path(__file__).with_name('worker_crash_bootstrap.py').resolve()),
                     'target': '/app/worker_crash_bootstrap.py', 'read_only': True}],
    }}}), encoding='utf-8')
    worker_stack.compose(stack, ['--file', str(override), 'up', '-d', '--wait', '--wait-timeout', '90'], timeout=180)
    *_, figure, explanation, url = report_ready(client)
    response = client.post(url, json={'expected_revision': figure['setup_revision'], 'figure_id': figure['id'],
                                     'explanation_id': explanation['id']})
    assert response.status_code == 202, response.text
    task_id = response.json()['task']['id']
    marker = tmp_path / 'data' / '.test-worker-crashed'
    deadline = time.monotonic() + 30
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.2)
    assert marker.read_text(encoding='ascii') == 'before_commit'
    with database_connection() as db:
        task = db.execute('SELECT * FROM tasks WHERE id=%s', (task_id,)).fetchone()
        assert task['status'] == 'running' and task['current_attempt'] == 1
        assert not db.execute('SELECT * FROM reports').fetchall()
    # A file exists despite rollback: this is the real filesystem/DB crash window.
    assert len(list((tmp_path / 'data' / 'reports').glob('*.docx'))) == 1
    # Use the actual 60-second lease and dispatcher recovery, without DB clock edits.
    deadline = time.monotonic() + 100
    while time.monotonic() < deadline:
        task = client.get('/api/v1/tasks/' + task_id).json()
        assert task['status'] != 'failed', task
        if task['status'] == 'succeeded':
            break
        time.sleep(0.3)
    assert task['status'] == 'succeeded' and task['current_attempt'] == 2
    report = client.get(url).json()['report']
    download = client.get(url + '/' + report['id'] + '/download')
    assert download.status_code == 200
    digest = hashlib.sha256(download.content).hexdigest()
    assert digest == report['sha256']
    with database_connection() as db:
        attempts = db.execute('SELECT status FROM task_attempts WHERE task_id=%s ORDER BY attempt_no', (task_id,)).fetchall()
        assert [row['status'] for row in attempts] == ['failed', 'succeeded']
        assert len(db.execute('SELECT * FROM reports').fetchall()) == 1
        events = db.execute('SELECT event_type FROM task_events WHERE task_id=%s ORDER BY seq', (task_id,)).fetchall()
        assert [row['event_type'] for row in events] == ['created', 'started', 'failed', 'requeued', 'started', 'succeeded']
    assert len(list((tmp_path / 'data' / 'reports').glob('*.docx'))) == 1
    # Re-publication after success still cannot rewrite the committed document.
    with database_connection(write=True) as db:
        db.execute('UPDATE task_outbox SET published_at=NULL,available_at=clock_timestamp() WHERE task_id=%s', (task_id,))
    time.sleep(4)
    assert hashlib.sha256(client.get(url + '/' + report['id'] + '/download').content).hexdigest() == digest
    assert client.get('/api/v1/tasks/' + task_id).json()['current_attempt'] == 2
