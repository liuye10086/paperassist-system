"""Explicit real-process proof for explanation polling and paid-submit fencing."""
import json
import os
from pathlib import Path
import time

import pytest

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
                               reason='Explicit isolated Linux explanation queue test is disabled.')


def test_explanation_slices_and_real_crash_recovery(client, cloud, writer, isolated_worker_stack, tmp_path, monkeypatch):
    stack = isolated_worker_stack
    # Only synthetic test values. The test stack separately guarantees an empty secret file.
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
    # The shared writer fixture is only for historical Word inputs here. New
    # acceptance must read the actual test policy file, not its fixture shortcut.
    monkeypatch.setattr('app.domain.explanation_policy.get_execution_policy', read_policy_file)
    cases = {}
    for mode in ('normal', 'reserved', 'unknown', 'receipt'):
        base, _, _, figure, url = ready(client)
        project_id = base.split('/')[4]
        with database_connection() as db:
            user_id = db.execute('SELECT owner_id FROM projects WHERE id=%s', (project_id,)).fetchone()['owner_id']
        service = ModelUsageService(user_id)
        budget = service.get_budget('user', user_id)
        if budget['limit_micro_usd'] is None:
            service.set_budget('user', user_id, 10000000, 0)
        service.set_budget('project', project_id, 10000000, 0)
        response = client.post(url, json={'expected_revision': figure['setup_revision'], 'figure_id': figure['id']},
                               headers={'Idempotency-Key': 'queue-' + mode})
        assert response.status_code == 202, response.text
        task = response.json()['task']
        assert task['status'] == 'queued'
        cases[mode] = (task['id'], url)
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0
        for task_id, _ in cases.values():
            frozen = db.execute('SELECT input_snapshot FROM tasks WHERE id=%s', (task_id,)).fetchone()['input_snapshot']['explanation_policy']
            assert frozen['policy']['max_output_tokens'] == 10000
            assert frozen['policy']['price']['version'] == 'test-price'
            assert frozen['input_token_allowance'] == 100000
    # A saved legacy explanation supplies an independent Word task.
    *_, figure, explanation, word_url = report_ready(client)
    accepted = client.post(word_url, json={'expected_revision': figure['setup_revision'],
        'figure_id': figure['id'], 'explanation_id': explanation['id']})
    assert accepted.status_code == 202, accepted.text
    word_id = accepted.json()['task']['id']
    override = tmp_path / 'explanation-worker.json'
    override.write_text(json.dumps({'services': {'worker': {
        'command': ['python', '/app/explanation_bootstrap.py', 'worker'],
        'volumes': [{'type': 'bind', 'source': str(Path(__file__).with_name('explanation_bootstrap.py').resolve()),
                     'target': '/app/explanation_bootstrap.py', 'read_only': True}],
    }}}), encoding='utf-8')
    worker_stack.compose(stack, ['--file', str(override), 'up', '-d', '--wait', '--wait-timeout', '90'], timeout=180)
    word_finished_while_pending = False
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        states = {mode: client.get('/api/v1/tasks/' + task_id).json() for mode, (task_id, _) in cases.items()}
        word = client.get('/api/v1/tasks/' + word_id).json()
        assert all(state['status'] != 'failed' for state in states.values()), states
        if word['status'] == 'succeeded' and states['normal']['status'] == 'running':
            word_finished_while_pending = True
            (tmp_path / 'data' / '.release-normal').write_text('release', encoding='ascii')
        if (all(states[mode]['status'] == 'succeeded' for mode in ('normal', 'reserved', 'receipt'))
                and states['unknown']['status'] == 'waiting_confirmation'):
            break
        time.sleep(0.5)
    assert word_finished_while_pending
    assert states['normal']['status'] == 'succeeded' and states['normal']['current_attempt'] == 1
    for mode in ('reserved', 'receipt'):
        assert states[mode]['status'] == 'succeeded' and states[mode]['current_attempt'] == 2
    assert states['unknown']['reason_code'] == 'submission_unknown'
    for mode, (task_id, url) in cases.items():
        methods = (tmp_path / 'data' / ('.calls-' + task_id)).read_text().splitlines()
        assert methods.count('POST') == 1
        assert methods.count('GET') >= 1 if mode != 'unknown' else methods == ['POST']
        saved = client.get(url).json()['explanation']
        assert bool(saved) == (mode != 'unknown')
        with database_connection() as db:
            calls = db.execute('SELECT * FROM model_calls WHERE task_id=%s', (task_id,)).fetchall()
            assert len(calls) == 1
            reservations = db.execute('SELECT status FROM budget_reservations WHERE call_id=%s', (calls[0]['id'],)).fetchall()
            assert len(reservations) == 3
            assert {row['status'] for row in reservations} == ({'held'} if mode == 'unknown' else {'settled'})
            if saved:
                assert saved['provenance']['model_call_id'] == calls[0]['id']
    unknown_id = cases['unknown'][0]
    assert client.post('/api/v1/tasks/' + unknown_id + '/retry',
                       json={'expected_revision': states['unknown']['revision']}).status_code == 409
