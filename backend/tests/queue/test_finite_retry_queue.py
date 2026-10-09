"""Real delayed outbox delivery, worker restart, and recovery without a second POST."""
from datetime import datetime
import json
import os
from pathlib import Path
import time

import pytest
from tests.queue.external_confirmation import confirm

from app.db.database import database_connection
from app.domain.explanation_content import VERSION
from app.domain.explanation_policy import get_execution_policy as read_policy_file
from app.domain.model_usage.service import ModelUsageService
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_boxplot import cloud  # noqa: F401
from tests.integration.test_explanations import ready, writer  # noqa: F401
from tests.integration.test_reports import report_ready
from tests.queue.test_real_worker import isolated_worker_stack, worker_stack  # noqa: F401

pytestmark = pytest.mark.skipif(os.environ.get('PAPERASSIST_RUN_QUEUE_TESTS') != '1',
                               reason='Explicit isolated Linux finite retry test is disabled.')


def wait_state(client, task_id, predicate, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        task = client.get('/api/v1/tasks/' + task_id).json()
        if predicate(task):
            return task
        time.sleep(0.25)
    pytest.fail(f'Isolated task did not reach expected state: {task}')


def test_finite_retry_survives_restart_and_manual_recovery(client, cloud, writer,
        isolated_worker_stack, tmp_path, monkeypatch):
    stack = isolated_worker_stack
    policy = {'policy': {'model': 'test-model', 'prompt_version': VERSION, 'max_output_tokens': 10000,
        'output_format': 'analysis_explanation_v1', 'price': {'version': 'test-price', 'model': 'test-model',
        'input_micro_usd_per_million': 100, 'cached_input_micro_usd_per_million': 50,
        'output_micro_usd_per_million': 200}}, 'input_token_allowance': 100000,
        'task_limit_micro_usd': 1000000}
    path = tmp_path / 'policy.json'
    path.write_text(json.dumps(policy), encoding='utf-8')
    monkeypatch.setenv('PAPERASSIST_EXPLANATION_POLICY_FILE', str(path))
    monkeypatch.setenv('OPENAI_API_KEY', 'isolated-test-key')
    monkeypatch.delenv('OPENAI_API_KEY_FILE', raising=False)
    monkeypatch.setattr('app.domain.explanation_policy.get_execution_policy', read_policy_file)
    base, _, _, figure, url = ready(client)
    project_id = base.split('/')[4]
    with database_connection() as db:
        user_id = db.execute('SELECT owner_id FROM projects WHERE id=%s', (project_id,)).fetchone()['owner_id']
    service = ModelUsageService(user_id)
    service.set_budget('user', user_id, 10000000, 0)
    service.set_budget('project', project_id, 10000000, 0)
    accepted = client.post(url, json={'expected_revision': figure['setup_revision'], 'figure_id': figure['id'],
                           'external_processing': confirm(client, url)},
                          headers={'Idempotency-Key': 'queue-finite-retry'})
    assert accepted.status_code == 202, accepted.text
    task_id = accepted.json()['task']['id']
    override = tmp_path / 'finite-retry-worker.json'
    override.write_text(json.dumps({'services': {'worker': {
        'command': ['python', '/app/explanation_bootstrap.py', 'worker'],
        'volumes': [{'type': 'bind', 'source': str(Path(__file__).with_name('explanation_bootstrap.py').resolve()),
                     'target': '/app/explanation_bootstrap.py', 'read_only': True}],
    }}}), encoding='utf-8')
    worker_stack.compose(stack, ['--file', str(override), 'up', '-d', '--wait', '--wait-timeout', '90'], timeout=180)
    first = wait_state(client, task_id, lambda t: t.get('retry_count') == 1, 60)
    assert first['status'] == 'running'
    with database_connection() as db:
        call_id = db.execute('SELECT id FROM model_calls WHERE task_id=%s', (task_id,)).fetchone()['id']
    # Restart a real process while the task has released its lease for backoff.
    worker_stack.compose(stack, ['--file', str(override), 'restart', '--timeout', '10', 'worker'], timeout=60)
    # A Word task must remain runnable during network backoff.
    *_, word_figure, explanation, word_url = report_ready(client)
    word_response = client.post(word_url, json={'expected_revision': word_figure['setup_revision'],
        'figure_id': word_figure['id'], 'explanation_id': explanation['id']})
    assert word_response.status_code == 202, word_response.text
    word_id = word_response.json()['task']['id']
    wait_state(client, word_id, lambda t: t['status'] == 'succeeded', 45)
    assert client.get('/api/v1/tasks/' + task_id).json()['status'] == 'running'
    failed = wait_state(client, task_id, lambda t: t['status'] == 'failed', 180)
    assert failed['retry_count'] == 3 and failed['error_code'] == 'model_provider_unavailable'
    assert failed['current_attempt'] == 1
    methods = (tmp_path / 'data' / ('.calls-' + task_id)).read_text().splitlines()
    assert methods == ['POST', 'GET', 'GET', 'GET', 'GET']
    timestamps = [datetime.fromisoformat(value) for value in
                  (tmp_path / 'data' / ('.retry-times-' + task_id)).read_text().splitlines()]
    for left, right, delay in zip(timestamps, timestamps[1:], (10, 30, 90)):
        assert (right - left).total_seconds() >= delay
    with database_connection() as db:
        rows = db.execute('''SELECT e.retry_count,e.retry_delay_seconds,
                EXTRACT(EPOCH FROM (o.published_at-e.created_at)) AS actual_delay
            FROM task_events e JOIN task_outbox o ON o.task_id=e.task_id AND o.task_revision=e.task_revision
            WHERE e.task_id=%s AND e.retry_delay_seconds IS NOT NULL ORDER BY e.seq''', (task_id,)).fetchall()
        assert [(r['retry_count'], r['retry_delay_seconds']) for r in rows] == [(1, 10), (2, 30), (3, 90)]
        # Dispatcher reuses available_at for broker publication retry. Its
        # confirmed publication time must still respect the task's saved delay.
        assert all(r['actual_delay'] >= r['retry_delay_seconds'] for r in rows)
        assert db.execute('SELECT count(*) AS n FROM task_outbox WHERE task_id=%s AND task_revision=%s',
                          (task_id, failed['revision'])).fetchone()['n'] == 0
        assert {r['status'] for r in db.execute('SELECT status FROM budget_reservations WHERE call_id=%s',
                                               (call_id,))} == {'held'}
    history = client.get('/api/v1/tasks/' + task_id + '/events?limit=100').json()['items']
    errors = [event for event in history if event.get('error_code') == 'model_provider_unavailable']
    assert len(errors) == 4 and errors[-1]['event_type'] == 'failed'
    assert {event['error_category'] for event in errors} == {'temporary'}
    # An explicit recovery starts a new cycle on the exact saved response.
    (tmp_path / 'data' / '.release-finite-retry').write_text('release', encoding='ascii')
    resumed = client.post('/api/v1/tasks/' + task_id + '/retry', json={'expected_revision': failed['revision']})
    assert resumed.status_code == 202, resumed.text
    assert resumed.json()['retry_count'] == 0
    succeeded = wait_state(client, task_id, lambda t: t['status'] == 'succeeded', 45)
    assert succeeded['retry_count'] == 0 and succeeded['current_attempt'] == 2
    methods = (tmp_path / 'data' / ('.calls-' + task_id)).read_text().splitlines()
    assert methods.count('POST') == 1 and methods.count('GET') == 5
    with database_connection() as db:
        calls = db.execute('SELECT id FROM model_calls WHERE task_id=%s', (task_id,)).fetchall()
        assert [row['id'] for row in calls] == [call_id]
        reservations = db.execute('SELECT status FROM budget_reservations WHERE call_id=%s', (call_id,)).fetchall()
        assert len(reservations) == 3 and {row['status'] for row in reservations} == {'settled'}
        previous = db.execute('SELECT error_code FROM task_attempts WHERE task_id=%s AND attempt_no=1',
                              (task_id,)).fetchone()
        assert previous['error_code'] == 'model_provider_unavailable'
    final_history = client.get('/api/v1/tasks/' + task_id + '/events?limit=100').json()['items']
    assert [event for event in final_history if event.get('error_code') == 'model_provider_unavailable'] == errors
