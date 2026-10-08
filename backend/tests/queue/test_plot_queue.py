"""Explicit real-process evidence for each paid plot boundary and PNG recovery."""
import hashlib
import json
import os
from pathlib import Path
import time

import pytest

from app.db.database import database_connection
from app.domain.model_usage.service import ModelUsageService
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_boxplot import cloud, prepared  # noqa: F401
from tests.integration.test_explanations import writer  # noqa: F401
from tests.integration.test_reports import report_ready
from tests.queue.test_real_worker import isolated_worker_stack, worker_stack  # noqa: F401

pytestmark = pytest.mark.skipif(os.environ.get('PAPERASSIST_RUN_QUEUE_TESTS') != '1',
                               reason='Explicit isolated Linux plot queue test is disabled.')


def test_plot_effect_boundaries_and_png_crash_recovery(client, cloud, writer, isolated_worker_stack, tmp_path, monkeypatch):
    stack = isolated_worker_stack
    policy = {'policy': {'model': 'test-plot', 'prompt_version': 'openai_boxplot_v1',
        'max_output_tokens': 16000, 'output_format': 'text', 'tools': ['code_interpreter'],
        'price': {'version': 'synthetic-price', 'model': 'test-plot',
            'input_micro_usd_per_million': 100, 'cached_input_micro_usd_per_million': 50,
            'output_micro_usd_per_million': 200}}, 'input_token_allowance': 100000,
        'task_limit_micro_usd': 1000000, 'tool_reserve_micro_usd': 1000,
        'tool_reserve_version': 'synthetic-tool-only'}
    path = tmp_path / 'plot-policy.json'
    path.write_text(json.dumps(policy), encoding='utf-8')
    monkeypatch.setenv('PAPERASSIST_PLOT_POLICY_FILE', str(path))
    monkeypatch.setenv('OPENAI_API_KEY', 'isolated-test-key')
    monkeypatch.delenv('OPENAI_API_KEY_FILE', raising=False)
    cases = {}
    modes = ('normal', 'reserved', 'container_unknown', 'container_ready', 'upload_unknown',
             'upload_ready', 'response_unknown', 'response_ready', 'candidate')
    for mode in modes:
        base, _, result, url = prepared(client)
        project_id = base.split('/')[4]
        with database_connection() as db:
            owner_id = db.execute('SELECT owner_id FROM projects WHERE id=%s', (project_id,)).fetchone()['owner_id']
        service = ModelUsageService(owner_id)
        if service.get_budget('user', owner_id)['limit_micro_usd'] is None:
            service.set_budget('user', owner_id, 10000000, 0)
        service.set_budget('project', project_id, 10000000, 0)
        accepted = client.post(url, json={'expected_revision': result['setup_revision']},
                               headers={'Idempotency-Key': 'plot-queue-' + mode})
        assert accepted.status_code == 202, accepted.text
        task = accepted.json()['task']
        assert task['status'] == 'queued'
        cases[mode] = (task['id'], url)
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0
        assert db.execute("SELECT count(*) AS n FROM tasks WHERE input_snapshot->'boxplot_policy'=%s::jsonb",
                          (json.dumps(policy | {'policy': {**policy['policy'], 'timeout_seconds': 45,
                           'price': {**policy['policy']['price'], 'currency': 'USD',
                                     'cache_write_micro_usd_per_million': None}}}),)).fetchone()['n'] == len(modes)
    # Historical inputs do not introduce extra paid tasks or outbox records.
    *_, figure, explanation, word_url = report_ready(client)
    accepted = client.post(word_url, json={'expected_revision': figure['setup_revision'],
        'figure_id': figure['id'], 'explanation_id': explanation['id']})
    assert accepted.status_code == 202, accepted.text
    word_id = accepted.json()['task']['id']
    override = tmp_path / 'plot-worker.json'
    override.write_text(json.dumps({'services': {'worker': {
        'command': ['python', '/app/plot_bootstrap.py', 'worker'],
        'volumes': [{'type': 'bind', 'source': str(Path(__file__).with_name('plot_bootstrap.py').resolve()),
                     'target': '/app/plot_bootstrap.py', 'read_only': True}],
    }}}), encoding='utf-8')
    worker_stack.compose(stack, ['--file', str(override), 'up', '-d', '--wait', '--wait-timeout', '90'], timeout=180)
    unknown = {mode for mode in modes if mode.endswith('_unknown')}
    succeeded = set(modes) - unknown
    word_finished_while_pending = False
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        states = {mode: client.get('/api/v1/tasks/' + task_id).json() for mode, (task_id, _) in cases.items()}
        assert all(state['status'] != 'failed' for state in states.values()), states
        word = client.get('/api/v1/tasks/' + word_id).json()
        if word['status'] == 'succeeded' and states['normal']['status'] == 'running':
            word_finished_while_pending = True
            (tmp_path / 'data' / '.release-plot-normal').write_text('release', encoding='ascii')
        if (all(states[mode]['status'] == 'succeeded' for mode in succeeded)
                and all(states[mode]['status'] == 'waiting_confirmation' for mode in unknown)):
            break
        time.sleep(0.5)
    assert word_finished_while_pending
    for mode, (task_id, url) in cases.items():
        state = states[mode]
        assert state['status'] == ('waiting_confirmation' if mode in unknown else 'succeeded'), states
        assert state['current_attempt'] == (1 if mode == 'normal' or mode in unknown else 2)
        methods = (tmp_path / 'data' / ('.calls-' + task_id)).read_text().splitlines()
        assert methods.count('POST container') == 1
        assert methods.count('POST upload') == (0 if mode == 'container_unknown' else 1)
        assert methods.count('POST response') == (0 if mode in {'container_unknown', 'upload_unknown'} else 1)
        if mode in unknown:
            assert not any(method.startswith('GET') for method in methods)
            assert state['reason_code'] == 'submission_unknown'
            assert client.post('/api/v1/tasks/' + task_id + '/retry',
                               json={'expected_revision': state['revision']}).status_code == 409
        else:
            assert methods.count('GET response') >= 1
            assert methods.count('GET cfile_png') == methods.count('GET cfile_result') == 1
            if mode == 'candidate':
                assert (tmp_path / 'data' / ('.crash-' + task_id)).exists()
        saved = client.get(url).json()['figure']
        assert bool(saved) == (mode in succeeded)
        with database_connection() as db:
            calls = db.execute('SELECT * FROM model_calls WHERE task_id=%s', (task_id,)).fetchall()
            assert len(calls) == 1
            reservations = db.execute('SELECT status FROM budget_reservations WHERE call_id=%s', (calls[0]['id'],)).fetchall()
            assert len(reservations) == 3 and {row['status'] for row in reservations} == {'held'}
            if mode in unknown:
                assert calls[0]['status'] in {'submitting', 'submission_unknown'}
                assert calls[0]['provider_response_id'] is None
                assert calls[0]['provider_state']['phase'] == {
                    'container_unknown': 'container_creating', 'upload_unknown': 'file_uploading',
                    'response_unknown': 'response_creating'}[mode]
            else:
                assert calls[0]['status'] == 'completed'
            assert calls[0]['usage_status'] == 'pending'
            if saved:
                assert saved['provenance']['model_call_id'] == calls[0]['id']
                content = (tmp_path / 'data' / 'figures' / (saved['id'] + '.png')).read_bytes()
                assert hashlib.sha256(content).hexdigest() == saved['sha256']
                assert len(content) == saved['size_bytes']
                assert db.execute('SELECT figure_candidate FROM tasks WHERE id=%s', (task_id,)).fetchone()['figure_candidate'] is None
