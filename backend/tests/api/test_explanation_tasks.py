"""Unified explanation HTTP is observational and never calls a paid provider."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.db.database import database_connection
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_boxplot import cloud  # noqa: F401
from tests.integration.test_explanations import ready, writer  # noqa: F401


def post(client, url, figure, **changes):
    return client.post(url, json={'expected_revision': figure['setup_revision'],
                                 'figure_id': figure['id'], **changes})


def test_post_only_queues_explanation_and_get_has_no_execution_side_effects(client, cloud, writer):
    *_, figure, url = ready(client)
    response = post(client, url, figure)
    assert response.status_code == 202, response.text
    state = response.json()
    assert state.get('task') and state['task']['status'] == 'queued'
    assert state['task']['task_type'] == 'explanation'
    assert state['job'] is None and state['explanation'] is None
    assert writer.calls == []
    before = client.get('/api/v1/tasks/' + state['task']['id'] + '/events').json()
    assert client.get(url).json() == state
    assert post(client, url, figure).json()['task'] == state['task']
    assert client.get('/api/v1/tasks/' + state['task']['id'] + '/events').json() == before
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM explanation_jobs').fetchone()['n'] == 0
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0


def transition(client, task, status, reason=None, error=None):
    from app.domain.tasks.service import TaskService
    service = TaskService(client.get('/api/v1/auth/me').json()['user']['id'])
    running = service.transition(task['id'], expected_revision=task['revision'], status='running')
    changed = service.transition(task['id'], expected_revision=running['revision'], status=status, reason_code=reason)
    if error:
        with database_connection(write=True) as db:
            db.execute('UPDATE tasks SET error_code=%s WHERE id=%s', (error, task['id']))
        changed = service.store.get(task['id'])
    return changed


def test_concurrent_posts_share_task_and_outbox(client, cloud, writer):
    *_, figure, url = ready(client)
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: post(client, url, figure), range(4)))
    assert all(response.status_code == 202 for response in responses)
    assert len({response.json()['task']['id'] for response in responses}) == 1
    assert writer.calls == []
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM tasks').fetchone()['n'] == 1
        assert db.execute('SELECT count(*) AS n FROM task_outbox').fetchone()['n'] == 1


def test_different_keys_cannot_race_into_duplicate_paid_tasks(client, cloud, writer, monkeypatch):
    from threading import Barrier
    from app.domain import explanation_tasks
    original = explanation_tasks.matching_task
    barrier = Barrier(2)
    def synchronized(*args):
        result = original(*args)
        barrier.wait(timeout=5)
        return result
    monkeypatch.setattr(explanation_tasks, 'matching_task', synchronized)
    *_, figure, url = ready(client)
    def create(key):
        return client.post(url, json={'expected_revision': 1, 'figure_id': figure['id']}, headers={'Idempotency-Key': key})
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(create, ['race-a', 'race-b']))
    assert sorted(response.status_code for response in responses) == [202, 409]
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM tasks').fetchone()['n'] == 1
        assert db.execute('SELECT count(*) AS n FROM task_outbox').fetchone()['n'] == 1
    assert not writer.calls


def test_budget_wait_resumes_same_task_and_revision_only_once(client, cloud, writer):
    *_, figure, url = ready(client)
    task = post(client, url, figure).json()['task']
    waiting = transition(client, task, 'waiting_confirmation', 'budget_exceeded', 'model_budget_missing')
    endpoint = '/api/v1/tasks/' + task['id'] + '/retry'
    with ThreadPoolExecutor(max_workers=3) as pool:
        responses = list(pool.map(lambda _: client.post(endpoint, json={'expected_revision': waiting['revision']}), range(3)))
    assert all(response.status_code == 202 for response in responses)
    assert {response.json()['revision'] for response in responses} == {waiting['revision'] + 1}
    assert all(response.json()['id'] == task['id'] for response in responses)
    assert client.post(endpoint, json={'expected_revision': 1}).status_code == 409
    assert writer.calls == []
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM task_outbox').fetchone()['n'] == 2
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0


def test_unknown_submission_cannot_be_requeued_or_replaced(client, cloud, writer):
    *_, figure, url = ready(client)
    task = post(client, url, figure).json()['task']
    waiting = transition(client, task, 'waiting_confirmation', 'submission_unknown', 'model_submission_unknown')
    assert client.post('/api/v1/tasks/' + task['id'] + '/retry', json={'expected_revision': waiting['revision']}).status_code == 409
    for retry in (False, True):
        response = post(client, url, figure, retry=retry)
        assert response.status_code == 200 and response.json()['task'] == waiting
    assert writer.calls == []


def test_explicit_failed_retry_creates_one_new_task_but_plain_post_does_not(client, cloud, writer):
    *_, figure, url = ready(client)
    original = post(client, url, figure).json()['task']
    failed = transition(client, original, 'failed', 'execution_failed', 'explanation_invalid')
    assert post(client, url, figure).json()['task'] == failed
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: post(client, url, figure, retry=True), range(4)))
    assert all(response.status_code == 202 for response in responses)
    ids = {response.json()['task']['id'] for response in responses}
    assert len(ids) == 1 and original['id'] not in ids
    assert writer.calls == []
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM tasks').fetchone()['n'] == 2


def test_missing_policy_rejects_new_work_but_does_not_block_existing_task_reads(client, cloud, writer, monkeypatch):
    *_, figure, url = ready(client)
    monkeypatch.setenv('OPENAI_API_KEY', '')
    assert post(client, url, figure).status_code == 503
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-key')
    task = post(client, url, figure).json()['task']
    monkeypatch.setenv('OPENAI_API_KEY', '')
    assert post(client, url, figure).json()['task'] == task
    assert client.get(url).json()['task'] == task


def test_same_idempotency_key_replays_failure_without_loading_new_policy(client, cloud, writer, monkeypatch):
    *_, figure, url = ready(client)
    headers = {'Idempotency-Key': 'stable-original-request'}
    response = client.post(url, json={'expected_revision': 1, 'figure_id': figure['id']}, headers=headers)
    failed = transition(client, response.json()['task'], 'failed', 'execution_failed', 'explanation_invalid')
    monkeypatch.setenv('OPENAI_API_KEY', '')
    replay = client.post(url, json={'expected_revision': 1, 'figure_id': figure['id'], 'retry': True}, headers=headers)
    assert replay.status_code == 200, replay.text
    assert replay.json()['task'] == failed
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM tasks').fetchone()['n'] == 1


def test_config_endpoint_exposes_only_safe_metadata(client, cloud, writer):
    response = client.get('/api/v1/ai/explanation-config')
    assert response.status_code == 200
    assert response.json()['configured'] is True
    assert set(response.json()) == {'configured', 'model', 'message', 'message_code', 'message_params'}
    assert 'policy' not in response.json() and 'price' not in response.text


@pytest.mark.parametrize('key', ['', 'bad key', 'x' * 129])
def test_idempotency_header_is_validated(client, cloud, writer, key):
    *_, figure, url = ready(client)
    response = client.post(url, json={'expected_revision': 1, 'figure_id': figure['id']}, headers={'Idempotency-Key': key})
    assert response.status_code == 422 and not writer.calls


def test_summary_shows_each_unified_explanation_once(client, cloud, writer):
    base, _, _, figure, url = ready(client)
    task = post(client, url, figure).json()['task']
    endpoint = base.split('/files/')[0] + '/summary'
    state = client.get(endpoint).json()
    explanations = [item for item in state['tasks']['items'] if item['kind'] == 'explanation']
    assert len(explanations) == 1 and explanations[0]['id'] == task['id']
    assert explanations[0]['status'] == 'queued'
    waiting = transition(client, task, 'waiting_confirmation', 'budget_exceeded')
    state = client.get(endpoint).json()
    explanations = [item for item in state['tasks']['items'] if item['kind'] == 'explanation']
    assert len(explanations) == 1 and explanations[0]['status'] == waiting['status']


def test_interrupted_before_first_call_resumes_original_task(client, cloud, writer):
    from app.domain.tasks.contracts import TaskCreateRequest
    from app.domain.tasks.service import TaskService
    base, file, result, figure, _ = ready(client)
    service = TaskService(client.get('/api/v1/auth/me').json()['user']['id'])
    task, _ = service.create(base.split('/')[4], TaskCreateRequest(task_type='explanation', file_id=file['id'],
        analysis_run_id=result['id'], expected_revision=1, figure_id=figure['id']), idempotency_key='before-first-call')
    failed = transition(client, task, 'failed', 'execution_failed', 'task_worker_interrupted')
    response = client.post('/api/v1/tasks/' + task['id'] + '/retry', json={'expected_revision': failed['revision']})
    assert response.status_code == 202, response.text
    assert response.json()['id'] == task['id'] and response.json()['status'] == 'queued'
    assert not writer.calls


def test_resume_missing_policy_freezes_new_config_and_budget_only_before_any_call(client, cloud, writer, monkeypatch):
    from app.domain import explanation_policy
    from app.domain.tasks.contracts import TaskCreateRequest
    from app.domain.tasks.service import TaskService
    from tests.domain.test_explanation_policy import execution_policy
    from app.core.exceptions import StorageError
    base, file, result, figure, _ = ready(client)
    owner = client.get('/api/v1/auth/me').json()['user']['id']
    service = TaskService(owner)
    def absent(payload):
        raise StorageError('explanation_not_configured', 'synthetic missing policy', 503)
    with monkeypatch.context() as patch:
        patch.setattr(explanation_policy, 'get_execution_policy', absent)
        task, _ = service.create(base.split('/')[4], TaskCreateRequest(task_type='explanation', file_id=file['id'],
            analysis_run_id=result['id'], expected_revision=1, figure_id=figure['id']), idempotency_key='generic-before-policy')
    waiting = transition(client, task, 'waiting_confirmation', 'budget_exceeded', 'explanation_not_configured')
    response = client.post('/api/v1/tasks/' + task['id'] + '/retry', json={'expected_revision': waiting['revision']})
    assert response.status_code == 202, response.text
    with database_connection() as db:
        snapshot = db.execute('SELECT input_snapshot FROM tasks WHERE id=%s', (task['id'],)).fetchone()['input_snapshot']
        assert snapshot.get('explanation_policy') == execution_policy()
        budget = db.execute("SELECT limit_micro_usd FROM model_budgets WHERE scope_type='task' AND scope_key=%s", (task['id'],)).fetchone()
        assert budget['limit_micro_usd'] == execution_policy()['task_limit_micro_usd']
    assert not writer.calls


def test_provider_response_not_found_cannot_requeue_or_start_a_replacement(client, cloud, writer):
    from tests.integration.test_explanations import submit
    *_, figure, url = ready(client)
    writer.pending = True
    submit(client, url, figure)
    task = client.get(url).json()['task']
    failed = transition(client, task, 'failed', 'execution_failed', 'model_response_not_found')
    response = client.post('/api/v1/tasks/' + task['id'] + '/retry', json={'expected_revision': failed['revision']})
    assert response.status_code == 409
    response = post(client, url, figure, retry=True)
    assert response.status_code == 200 and response.json()['task'] == failed
    assert len(writer.calls) == 1
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM tasks').fetchone()['n'] == 1
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 1
