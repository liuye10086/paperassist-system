"""Plot acceptance is local, revision-aware, and never submits paid work."""
from concurrent.futures import ThreadPoolExecutor
import json

import pytest
from tests.api.test_external_processing import confirmation

from app.db.database import database_connection
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_boxplot import cloud, prepared, generate  # noqa: F401
from tests.api.test_explanation_tasks import persistence_counts, transition


def execution_policy():
    from tests.domain.test_explanation_policy import execution_policy as explanation_policy
    value = explanation_policy()
    value['policy'].update(prompt_version='openai_boxplot_v1', output_format='text', tools=['code_interpreter'])
    return {**value, 'tool_reserve_micro_usd': 100, 'tool_reserve_version': 'synthetic-tool-v1'}


@pytest.fixture
def policy(tmp_path, monkeypatch, cloud):
    path = tmp_path / 'plot-policy.json'
    path.write_text(json.dumps(execution_policy()), encoding='utf-8')
    monkeypatch.setenv('PAPERASSIST_PLOT_POLICY_FILE', str(path))
    return execution_policy()


def post(client, url, *, idempotency_key=None, **changes):
    from tests.api.test_external_processing import confirmation
    external = confirmation(client, url)
    return client.post(url, json={'external_processing': external, 'expected_revision': 1, **changes},
                       headers={'Idempotency-Key': idempotency_key} if idempotency_key is not None else {})


def test_post_only_saves_task_and_get_does_not_execute_or_write(client, cloud, policy, monkeypatch):
    from app.domain import boxplot
    _, _, _, url = prepared(client)
    inspected = []
    original = boxplot.inspect_selection
    def inspect(*args, **kwargs):
        inspected.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(boxplot, 'inspect_selection', inspect)
    response = post(client, url)
    assert response.status_code == 202, response.text
    assert inspected == [], 'HTTP must not recompute workbook'
    state = response.json()
    assert state.get('task') and state['task']['status'] == 'queued'
    assert state['task']['task_type'] == 'boxplot'
    assert state['figure'] is None and state['job'] is None
    events = client.get('/api/v1/tasks/' + state['task']['id'] + '/events').json()
    assert client.get(url).json() == state
    assert post(client, url).json()['task'] == state['task']
    assert client.get('/api/v1/tasks/' + state['task']['id'] + '/events').json() == events
    assert cloud.calls == []
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM figure_jobs').fetchone()['n'] == 0
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0
        row = db.execute('SELECT input_snapshot FROM tasks').fetchone()
        assert row['input_snapshot']['boxplot_policy'] == policy
        assert db.execute("SELECT count(*) AS n FROM model_budgets WHERE scope_type='task'").fetchone()['n'] == 1


def test_missing_plot_policy_rejects_new_work_but_existing_task_and_image_still_read(client, cloud, monkeypatch, policy):
    _, _, _, url = prepared(client)
    monkeypatch.setenv('PAPERASSIST_PLOT_POLICY_FILE', '')
    assert post(client, url).status_code == 503
    assert client.get(url).json()['figure'] is None
    generate(client, url)
    saved = client.get(url).json()
    assert saved['figure'] and client.get(url).json() == saved
    assert post(client, url).status_code == 200
    assert post(client, url).json() == saved
    assert not cloud.calls


def test_config_has_only_safe_local_metadata(client, policy):
    response = client.get('/api/v1/ai/plot-config')
    assert response.status_code == 200
    assert response.json()['configured'] is True
    assert set(response.json()) == {'configured', 'model', 'message', 'message_code', 'message_params'}
    assert 'price' not in response.text and 'synthetic-tool' not in response.text


def test_concurrent_same_source_accepts_one_task(client, cloud, policy):
    _, _, _, url = prepared(client)
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: post(client, url), range(4)))
    assert all(response.status_code == 202 for response in responses)
    assert len({response.json()['task']['id'] for response in responses}) == 1
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM tasks').fetchone()['n'] == 1
        assert db.execute('SELECT count(*) AS n FROM task_outbox').fetchone()['n'] == 1
    assert not cloud.calls


def test_different_headers_cannot_race_into_two_paid_tasks(client, policy, monkeypatch):
    from threading import Barrier
    from app.domain import plot_tasks
    original, barrier = plot_tasks.matching_task, Barrier(2)
    def synchronized(*args):
        task = original(*args)
        barrier.wait(timeout=5)
        return task
    monkeypatch.setattr(plot_tasks, 'matching_task', synchronized)
    _, _, _, url = prepared(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda key: client.post(url, json={'expected_revision': 1, 'external_processing': confirmation(client, url)},
            headers={'Idempotency-Key': key}), ['plot-race-a', 'plot-race-b']))
    assert sorted(response.status_code for response in responses) == [202, 409]
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM tasks').fetchone()['n'] == 1
        assert db.execute('SELECT count(*) AS n FROM task_outbox').fetchone()['n'] == 1


def test_existing_header_replays_original_failure_without_new_policy(client, policy, monkeypatch):
    _, _, _, url = prepared(client)
    headers = {'Idempotency-Key': 'plot-original'}
    task = client.post(url, json={'expected_revision': 1, 'external_processing': confirmation(client, url)}, headers=headers).json()['task']
    failed = transition(client, task, 'failed', 'execution_failed', 'plot_invalid_result')
    monkeypatch.setenv('PAPERASSIST_PLOT_POLICY_FILE', '')
    response = client.post(url, json={'expected_revision': 1, 'retry': True, 'external_processing': confirmation(client, url)}, headers=headers)
    assert response.status_code == 200 and response.json()['task'] == failed
    assert client.get(url).json()['task'] == failed
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM tasks').fetchone()['n'] == 1


@pytest.mark.parametrize('legacy', [False, True], ids=['failed-task', 'failed-legacy-job'])
@pytest.mark.parametrize('policy_available', [True, False], ids=['configured', 'unconfigured'])
def test_paid_successor_requires_request_key_before_loading_policy(client, cloud, policy, monkeypatch,
        legacy, policy_available):
    from app.core.exceptions import StorageError
    from app.domain import plot_policy
    from tests.api.test_boxplot import seed_legacy
    _, _, _, url = prepared(client)
    if legacy:
        predecessor_id = seed_legacy(client, url, status='failed')['id']
        predecessor_revision = None
    else:
        original = post(client, url).json()['task']
        failed = transition(client, original, 'failed', 'execution_failed', 'plot_invalid_result')
        predecessor_id = original['id']
        predecessor_revision = failed['revision']
    before = persistence_counts()
    loaded = []
    original_policy = plot_policy.get_execution_policy
    def get_policy():
        loaded.append(True)
        if not policy_available:
            raise StorageError('plot_not_configured', 'synthetic missing policy', 503)
        return original_policy()
    monkeypatch.setattr(plot_policy, 'get_execution_policy', get_policy)
    response = post(client, url, retry=True)
    assert response.status_code == 422, response.text
    assert response.json()['detail']['code'] == 'task_input_invalid'
    assert loaded == []
    assert persistence_counts() == before
    assert not cloud.calls
    if policy_available:
        accepted = post(client, url, retry=True, expected_predecessor_id=predecessor_id,
            expected_predecessor_revision=predecessor_revision, idempotency_key='plot-explicit-paid-successor')
        assert accepted.status_code == 202, accepted.text
        after = persistence_counts()
        assert after['tasks'] == before['tasks'] + 1
        assert after['task_outbox'] == before['task_outbox'] + 1
        assert after['model_budgets'] == before['model_budgets'] + 1
        assert after['model_calls'] == before['model_calls']
        assert after['budget_reservations'] == before['budget_reservations']
        assert loaded == [True] and not cloud.calls


def test_paid_successor_failure_replays_same_key_and_new_key_authorizes_next_task(client, cloud, policy, monkeypatch):
    from app.domain import plot_policy
    _, _, _, url = prepared(client)
    initial = post(client, url).json()['task']
    observed = transition(client, initial, 'failed', 'execution_failed', 'plot_invalid_result')
    accepted = post(client, url, retry=True, expected_predecessor_id=initial['id'],
        expected_predecessor_revision=observed['revision'], idempotency_key='plot-paid-intent-b')
    assert accepted.status_code == 202, accepted.text
    successor = accepted.json()['task']
    assert successor['id'] != initial['id']
    failed = transition(client, successor, 'failed', 'execution_failed', 'plot_invalid_result')
    before = persistence_counts()
    with monkeypatch.context() as patch:
        patch.setattr(plot_policy, 'get_execution_policy', lambda: pytest.fail('Replay loaded a new policy'))
        replay = post(client, url, retry=True, expected_predecessor_id=initial['id'],
            expected_predecessor_revision=observed['revision'], idempotency_key='plot-paid-intent-b')
        assert replay.status_code == 200 and replay.json()['task'] == failed
        assert persistence_counts() == before
    next_response = post(client, url, retry=True, expected_predecessor_id=successor['id'],
        expected_predecessor_revision=failed['revision'], idempotency_key='plot-paid-intent-c')
    assert next_response.status_code == 202, next_response.text
    assert next_response.json()['task']['id'] not in (initial['id'], successor['id'])
    after = persistence_counts()
    assert after['tasks'] == after['task_outbox'] == 3
    assert after['model_calls'] == after['budget_reservations'] == 0
    assert not cloud.calls
    with monkeypatch.context() as patch:
        patch.setattr(plot_policy, 'get_execution_policy', lambda: pytest.fail('Old accepted request loaded a new policy'))
        original = post(client, url, retry=True, expected_predecessor_id=initial['id'],
            expected_predecessor_revision=observed['revision'], idempotency_key='plot-paid-intent-b')
        assert original.status_code == 200 and original.json()['task'] == failed
        assert persistence_counts() == after


def test_keyless_failed_post_resumes_original_without_loading_new_policy(client, cloud, policy, monkeypatch):
    from app.domain import plot_policy
    _, _, _, url = prepared(client)
    initial = post(client, url).json()['task']
    transition(client, initial, 'failed', 'execution_failed', 'task_worker_interrupted')
    monkeypatch.setattr(plot_policy, 'get_execution_policy', lambda: pytest.fail('Resume loaded a new policy'))
    response = post(client, url, retry=True)
    assert response.status_code == 202, response.text
    assert response.json()['task']['id'] == initial['id']
    assert response.json()['task']['status'] == 'queued'
    counts = persistence_counts()
    assert counts['tasks'] == 1 and counts['task_outbox'] == 2 and counts['model_calls'] == 0
    assert not cloud.calls


def test_missing_policy_can_be_frozen_on_budget_resume_before_any_call(client, policy, monkeypatch):
    from app.domain.tasks.contracts import TaskCreateRequest
    from app.domain.tasks.service import TaskService
    base, file, result, _ = prepared(client)
    owner = client.get('/api/v1/auth/me').json()['user']['id']
    with monkeypatch.context() as patch:
        patch.setenv('PAPERASSIST_PLOT_POLICY_FILE', '')
        task, _ = TaskService(owner).create(base.split('/')[4], TaskCreateRequest(task_type='boxplot',
            file_id=file['id'], analysis_run_id=result['id'], expected_revision=1), idempotency_key='generic-plot')
    waiting = transition(client, task, 'waiting_confirmation', 'budget_exceeded', 'plot_not_configured')
    response = client.post('/api/v1/tasks/' + task['id'] + '/retry', json={'expected_revision': waiting['revision']})
    assert response.status_code == 202 and response.json()['id'] == task['id']
    with database_connection() as db:
        saved = db.execute('SELECT input_snapshot FROM tasks WHERE id=%s', (task['id'],)).fetchone()
        assert saved['input_snapshot']['boxplot_policy'] == policy
        budget = db.execute("SELECT limit_micro_usd FROM model_budgets WHERE scope_type='task' AND scope_key=%s", (task['id'],)).fetchone()
        assert budget['limit_micro_usd'] == policy['task_limit_micro_usd']
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0


def test_input_limit_requires_explicit_new_task_with_new_frozen_policy(client, policy, monkeypatch):
    from copy import deepcopy
    from app.domain import plot_policy
    _, _, _, url = prepared(client)
    task = post(client, url).json()['task']
    failed = transition(client, task, 'failed', 'execution_failed', 'plot_input_limit')
    updated = deepcopy(policy)
    updated['input_token_allowance'] += 1000
    monkeypatch.setattr(plot_policy, 'get_execution_policy', lambda payload=None: updated)
    assert post(client, url).json()['task'] == failed
    assert client.post('/api/v1/tasks/' + task['id'] + '/retry',
        json={'expected_revision': failed['revision']}).status_code == 409
    response = post(client, url, retry=True, expected_predecessor_id=task['id'],
        expected_predecessor_revision=failed['revision'], idempotency_key='plot-input-limit-new-policy')
    assert response.status_code == 202
    successor = response.json()['task']
    assert successor['id'] != task['id']
    with database_connection() as db:
        old = db.execute('SELECT status,input_snapshot FROM tasks WHERE id=%s', (task['id'],)).fetchone()
        new = db.execute('SELECT input_snapshot FROM tasks WHERE id=%s', (successor['id'],)).fetchone()
        assert old['status'] == 'failed' and old['input_snapshot']['boxplot_policy'] == policy
        assert new['input_snapshot']['boxplot_policy'] == updated
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0


def test_budget_resume_is_idempotent_and_keeps_task(client, cloud, policy):
    _, _, _, url = prepared(client)
    task = post(client, url).json()['task']
    waiting = transition(client, task, 'waiting_confirmation', 'budget_exceeded', 'model_budget_missing')
    endpoint = '/api/v1/tasks/' + task['id'] + '/retry'
    with ThreadPoolExecutor(max_workers=3) as pool:
        responses = list(pool.map(lambda _: client.post(endpoint, json={'expected_revision': waiting['revision']}), range(3)))
    assert all(response.status_code == 202 for response in responses)
    assert {response.json()['id'] for response in responses} == {task['id']}
    assert {response.json()['revision'] for response in responses} == {waiting['revision'] + 1}
    assert client.post(endpoint, json={'expected_revision': 1}).status_code == 409
    assert not cloud.calls


def test_unknown_cannot_be_retried_or_replaced(client, cloud, policy):
    _, _, _, url = prepared(client)
    task = post(client, url).json()['task']
    unknown = transition(client, task, 'waiting_confirmation', 'submission_unknown', 'model_submission_unknown')
    assert client.post('/api/v1/tasks/' + task['id'] + '/retry', json={'expected_revision': unknown['revision']}).status_code == 409
    assert post(client, url, retry=True).json()['task'] == unknown
    assert not cloud.calls


@pytest.mark.parametrize('code', ['plot_result_mismatch'])
def test_terminal_output_needs_explicit_paid_retry_and_creates_only_one_successor(client, cloud, policy, code):
    _, _, _, url = prepared(client)
    task = post(client, url).json()['task']
    failed = transition(client, task, 'failed', 'execution_failed', code)
    assert post(client, url).json()['task'] == failed
    assert client.post('/api/v1/tasks/' + task['id'] + '/retry', json={'expected_revision': failed['revision']}).status_code == 409
    with ThreadPoolExecutor(max_workers=3) as pool:
        responses = list(pool.map(lambda _: post(client, url, retry=True,
            expected_predecessor_id=task['id'], expected_predecessor_revision=failed['revision'],
            idempotency_key='one-plot-paid-retry'), range(3)))
    assert all(response.status_code == 202 for response in responses)
    ids = {response.json()['task']['id'] for response in responses}
    assert len(ids) == 1 and task['id'] not in ids
    assert not cloud.calls


@pytest.mark.parametrize('key', ['', 'bad key', 'x' * 129])
def test_invalid_request_key_is_rejected(client, cloud, policy, key):
    _, _, _, url = prepared(client)
    response = client.post(url, json={'expected_revision': 1, 'external_processing': confirmation(client, url)}, headers={'Idempotency-Key': key})
    assert response.status_code == 422 and not cloud.calls


def test_summary_includes_queued_plot_once(client, policy):
    base, _, _, url = prepared(client)
    task = post(client, url).json()['task']
    state = client.get(base.split('/files/')[0] + '/summary').json()
    plots = [item for item in state['tasks']['items'] if item['kind'] == 'boxplot']
    assert len(plots) == 1 and plots[0]['id'] == task['id'] and plots[0]['status'] == 'queued'


@pytest.mark.parametrize('call_status,call_error,response_id,replacement', [
    ('failed', 'plot_container_expired', None, True),
    ('completed', None, 'resp_download_expired', True),
    ('submission_unknown', 'model_provider_request_failed', None, False),
    ('submitting', None, None, False),
    ('failed', 'model_provider_request_failed', None, False),
])
def test_expired_retry_requires_definite_call_evidence(client, cloud, policy,
        call_status, call_error, response_id, replacement):
    url, task, failed = failed_call(client, policy, call_status, call_error,
        response_id=response_id, task_error='plot_container_expired')
    assert client.post('/api/v1/tasks/' + task['id'] + '/retry',
        json={'expected_revision': failed['revision']}).status_code == 409
    assert post(client, url).json()['task']['id'] == task['id']
    response = post(client, url, retry=True, expected_predecessor_id=task['id'],
        expected_predecessor_revision=failed['revision'], idempotency_key='plot-definite-expired-retry')
    assert response.status_code == (202 if replacement else 200), response.text
    assert (response.json()['task']['id'] != task['id']) == replacement
    assert post(client, url, retry=True).json()['task']['id'] == response.json()['task']['id']
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM tasks').fetchone()['n'] == (2 if replacement else 1)
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 1
        assert db.execute("SELECT count(*) AS n FROM budget_reservations WHERE status='held'").fetchone()['n'] == 3
    assert not cloud.calls


def failed_call(client, policy, call_status, call_error=None, *, response_id=None,
        task_error='task_worker_interrupted', phase=None):
    from app.domain.tasks.service import TaskService
    from app.domain.model_usage.contracts import CallRequest
    from app.domain.model_usage.service import ModelUsageService
    from psycopg.types.json import Jsonb
    _, _, _, url = prepared(client)
    task = post(client, url).json()['task']
    owner = client.get('/api/v1/auth/me').json()['user']['id']
    tasks = TaskService(owner)
    running = tasks.transition(task['id'], expected_revision=task['revision'], status='running')
    service = ModelUsageService(owner)
    for scope, key in [('user', owner), ('project', task['project_id'])]:
        service.set_budget(scope, key, 1000000, 0)
    call = service.reserve_call(CallRequest(task_id=task['id'], expected_task_revision=running['revision'],
        call_key='boxplot:v1', input_digest='a' * 64, policy=policy['policy'],
        input_token_allowance=policy['input_token_allowance'],
        tool_reserve_micro_usd=policy['tool_reserve_micro_usd'],
        tool_reserve_version=policy['tool_reserve_version']))
    # The gateway's separately tested receipts are seeded without using any provider.
    with database_connection(write=True) as db:
        db.execute('UPDATE model_calls SET status=%s,error_code=%s,provider_response_id=%s,provider_state=%s WHERE id=%s',
            (call_status, call_error, response_id, Jsonb({'phase': phase}), call['id']))
    failed = tasks.transition(task['id'], expected_revision=running['revision'], status='failed', reason_code='execution_failed')
    with database_connection(write=True) as db:
        db.execute('UPDATE tasks SET error_code=%s WHERE id=%s', (task_error, task['id']))
    return url, task, failed


@pytest.mark.parametrize('call_status,phase,resumable', [
    ('submitting', 'container_ready', True),
    ('submitting', 'file_ready', True),
    ('submitting', 'container_creating', False),
    ('submitting', 'file_uploading', False),
    ('submitting', 'response_creating', False),
    ('submission_unknown', 'container_ready', False),
])
@pytest.mark.parametrize('route', ['task_retry', 'plot_post'])
def test_only_acknowledged_preparation_can_resume_same_task(client, cloud, policy,
        call_status, phase, resumable, route):
    url, task, failed = failed_call(client, policy, call_status, phase=phase)
    if route == 'task_retry':
        response = client.post('/api/v1/tasks/' + task['id'] + '/retry', json={'expected_revision': failed['revision']})
        assert response.status_code == (202 if resumable else 409), response.text
        result = response.json() if resumable else client.get(url).json()['task']
    else:
        response = post(client, url, retry=True)
        assert response.status_code == (202 if resumable else 200), response.text
        result = response.json()['task']
    assert result['id'] == task['id']
    assert result['status'] == ('queued' if resumable else 'failed')
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM tasks').fetchone()['n'] == 1
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 1
    assert not cloud.calls
