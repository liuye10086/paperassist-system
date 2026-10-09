"""A paid retry names the failure observed when its HTTP intent was frozen."""
import pytest

from app.db.database import database_connection
from app.domain.tasks.service import TaskService
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_boxplot import cloud, prepared, seed_legacy as seed_plot_legacy  # noqa: F401
from tests.api.test_explanation_tasks import persistence_counts
from tests.api.test_plot_tasks import policy  # noqa: F401
from tests.api.test_external_processing import confirmation
from tests.integration.test_explanations import ready, writer, seed_legacy as seed_explanation_legacy  # noqa: F401


def source(client, kind):
    if kind == 'boxplot':
        _, _, _, url = prepared(client)
        return url, {'expected_revision': 1, 'external_processing': confirmation(client, url)}, 'plot_invalid_result'
    *_, figure, url = ready(client)
    return url, {'expected_revision': 1, 'figure_id': figure['id'],
                 'external_processing': confirmation(client, url)}, 'explanation_invalid'


def fail_task(client, task, error):
    service = TaskService(client.get('/api/v1/auth/me').json()['user']['id'])
    if task['status'] == 'queued':
        task = service.transition(task['id'], expected_revision=task['revision'], status='running')
    service.transition(task['id'], expected_revision=task['revision'], status='failed', reason_code='execution_failed')
    with database_connection(write=True) as db:
        db.execute('UPDATE tasks SET error_code=%s WHERE id=%s', (error, task['id']))
    return service.store.get(task['id'])


def predecessor(client, kind, url, body, error, legacy):
    if not legacy:
        response = client.post(url, json=body)
        assert response.status_code == 202, response.text
        return fail_task(client, response.json()['task'], error)['id']
    if kind == 'boxplot':
        return seed_plot_legacy(client, url, status='failed')['id']
    return seed_explanation_legacy(client, url, {'id': body['figure_id']}, status='failed')['id']


def paid_retry(client, url, body, observed_id):
    frozen = {**body, 'retry': True, 'expected_predecessor_id': observed_id}
    task = client.get(url).json()['task']
    if task:
        frozen['expected_predecessor_revision'] = task['revision']
    return frozen


def watch_policy(monkeypatch, kind):
    loaded = []
    if kind == 'boxplot':
        from app.domain import plot_policy
        module = plot_policy
    else:
        from app.domain import explanation_policy
        module = explanation_policy
    original = module.get_execution_policy
    def recorded(*args, **kwargs):
        loaded.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(module, 'get_execution_policy', recorded)
    return loaded


@pytest.mark.parametrize('kind', ['boxplot', 'explanation'])
@pytest.mark.parametrize('legacy', [False, True], ids=['task', 'legacy'])
@pytest.mark.parametrize('other_state', ['queued', 'running'])
def test_unaccepted_retry_key_cannot_pay_for_a_later_failure(client, cloud, policy, writer, monkeypatch,
        kind, legacy, other_state):
    url, body, error = source(client, kind)
    observed_id = predecessor(client, kind, url, body, error, legacy)
    frozen = paid_retry(client, url, body, observed_id)
    accepted = client.post(url, json=frozen, headers={'Idempotency-Key': 'accepted-page-l'})
    assert accepted.status_code == 202, accepted.text
    successor = accepted.json()['task']
    if other_state == 'running':
        service = TaskService(client.get('/api/v1/auth/me').json()['user']['id'])
        successor = service.transition(successor['id'], expected_revision=successor['revision'], status='running')
    before = persistence_counts()
    with monkeypatch.context() as patch:
        loaded = watch_policy(patch, kind)
        unaccepted = client.post(url, json=frozen, headers={'Idempotency-Key': 'unaccepted-page-k'})
        assert persistence_counts() == before
        assert loaded == []
    # K's caller never observes its response. B fails before it confirms exactly
    # the same frozen request: this must not silently authorize a new task C.
    failed = fail_task(client, successor, error)
    before = persistence_counts()
    with monkeypatch.context() as patch:
        loaded = watch_policy(patch, kind)
        replay = client.post(url, json=frozen, headers={'Idempotency-Key': 'unaccepted-page-k'})
        assert replay.status_code == 409, replay.text
        assert replay.json()['detail']['code'] == 'task_source_conflict'
        assert persistence_counts() == before
        original = client.post(url, json=frozen, headers={'Idempotency-Key': 'accepted-page-l'})
        assert original.status_code == 200 and original.json()['task'] == failed
        assert persistence_counts() == before
        assert loaded == []
    assert unaccepted.status_code == 409, unaccepted.text
    assert unaccepted.json()['detail']['code'] == 'task_source_conflict'
    assert not cloud.calls and not writer.calls


@pytest.mark.parametrize('kind', ['boxplot', 'explanation'])
@pytest.mark.parametrize('legacy', [False, True], ids=['task', 'legacy'])
def test_paid_successor_key_also_requires_observed_predecessor(client, cloud, policy, writer, monkeypatch,
        kind, legacy):
    url, body, error = source(client, kind)
    predecessor(client, kind, url, body, error, legacy)
    before = persistence_counts()
    loaded = watch_policy(monkeypatch, kind)
    response = client.post(url, json={**body, 'retry': True}, headers={'Idempotency-Key': 'missing-predecessor'})
    assert response.status_code == 422, response.text
    assert response.json()['detail']['code'] == 'task_input_invalid'
    assert persistence_counts() == before
    assert loaded == []
    assert not cloud.calls and not writer.calls


@pytest.mark.parametrize('kind', ['boxplot', 'explanation'])
@pytest.mark.parametrize('with_key', [False, True])
def test_stale_predecessor_cannot_resume_another_failed_task(client, cloud, policy, writer, monkeypatch,
        kind, with_key):
    url, body, error = source(client, kind)
    observed_id = predecessor(client, kind, url, body, error, False)
    frozen = paid_retry(client, url, body, observed_id)
    accepted = client.post(url, json=frozen,
        headers={'Idempotency-Key': 'another-page-successor'})
    assert accepted.status_code == 202, accepted.text
    failed = fail_task(client, accepted.json()['task'], 'task_worker_interrupted')
    before = persistence_counts()
    loaded = watch_policy(monkeypatch, kind)
    response = client.post(url, json=frozen,
        headers={'Idempotency-Key': 'stale-resume-intent'} if with_key else {})
    assert response.status_code == 409, response.text
    assert response.json()['detail']['code'] == 'task_source_conflict'
    assert client.get(url).json()['task'] == failed
    assert persistence_counts() == before
    assert loaded == []
    assert not cloud.calls and not writer.calls


@pytest.mark.parametrize('kind', ['boxplot', 'explanation'])
@pytest.mark.parametrize('invalid', ['', 'contains space', 'x' * 65, 123, True, {}, []])
def test_observed_predecessor_is_a_bounded_strict_identifier(client, cloud, policy, writer, kind, invalid):
    url, body, _ = source(client, kind)
    before = persistence_counts()
    response = client.post(url, json={**body, 'retry': True, 'expected_predecessor_id': invalid},
        headers={'Idempotency-Key': 'invalid-predecessor'})
    assert response.status_code == 422
    assert persistence_counts() == before
    assert not cloud.calls and not writer.calls


@pytest.mark.parametrize('kind', ['boxplot', 'explanation'])
@pytest.mark.parametrize('with_revision', [False, True], ids=['missing-version', 'frozen-version'])
def test_unbound_safe_resume_key_cannot_pay_after_same_task_fails_again(client, cloud, policy, writer, monkeypatch,
        kind, with_revision):
    url, body, error = source(client, kind)
    initial = client.post(url, json=body).json()['task']
    observed = fail_task(client, initial, 'task_worker_interrupted')
    frozen = {**body, 'retry': True, 'expected_predecessor_id': observed['id']}
    if with_revision:
        frozen['expected_predecessor_revision'] = observed['revision']
    resumed = client.post(url, json=frozen, headers={'Idempotency-Key': 'safe-resume-page-k'})
    assert resumed.status_code == 202, resumed.text
    assert resumed.json()['task']['id'] == observed['id']
    fail_task(client, resumed.json()['task'], error)
    before = persistence_counts()
    loaded = watch_policy(monkeypatch, kind)
    replay = client.post(url, json=frozen, headers={'Idempotency-Key': 'safe-resume-page-k'})
    assert replay.status_code == (409 if with_revision else 422), replay.text
    assert replay.json()['detail']['code'] == ('task_source_conflict' if with_revision else 'task_input_invalid')
    assert persistence_counts() == before and loaded == []
    assert not cloud.calls and not writer.calls


@pytest.mark.parametrize('kind', ['boxplot', 'explanation'])
def test_frozen_predecessor_revision_is_rechecked_inside_create_transaction(client, cloud, policy, writer, monkeypatch, kind):
    url, body, error = source(client, kind)
    observed_id = predecessor(client, kind, url, body, error, False)
    observed = client.get(url).json()['task']
    original = TaskService.create
    changed = []
    def create_after_source_advanced(self, *args, **kwargs):
        # Simulate another accepted recovery advancing the same task after the
        # HTTP source read. Only the create transaction can catch this revision.
        with database_connection(write=True) as db:
            db.execute('UPDATE tasks SET revision=revision+1 WHERE id=%s', (observed_id,))
        changed.append(True)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(TaskService, 'create', create_after_source_advanced)
    before = persistence_counts()
    response = client.post(url, json={**body, 'retry': True, 'expected_predecessor_id': observed_id,
        'expected_predecessor_revision': observed['revision']}, headers={'Idempotency-Key': 'transaction-stale-revision'})
    assert changed == [True]
    assert response.status_code == 409, response.text
    assert response.json()['detail']['code'] == 'task_revision_conflict'
    assert persistence_counts() == before
    assert not cloud.calls and not writer.calls


@pytest.mark.parametrize('kind', ['boxplot', 'explanation'])
@pytest.mark.parametrize('invalid', [0, -1, True, '3', 2_147_483_648, {}, []])
def test_observed_predecessor_revision_is_a_strict_positive_integer(client, cloud, policy, writer, kind, invalid):
    url, body, _ = source(client, kind)
    before = persistence_counts()
    response = client.post(url, json={**body, 'retry': True, 'expected_predecessor_revision': invalid},
        headers={'Idempotency-Key': 'invalid-predecessor-revision'})
    assert response.status_code == 422
    assert persistence_counts() == before
    assert not cloud.calls and not writer.calls


@pytest.mark.parametrize('kind', ['boxplot', 'explanation'])
@pytest.mark.parametrize('successor_state', ['queued', 'failed'])
def test_same_key_acceptance_between_request_lookup_and_task_read_replays_accepted_task(client, cloud, policy,
        writer, monkeypatch, kind, successor_state):
    from app.adapters.task_store import TaskStore
    if kind == 'boxplot':
        from app.domain import plot_tasks as module
    else:
        from app.domain import explanation_tasks as module
    url, body, error = source(client, kind)
    observed_id = predecessor(client, kind, url, body, error, False)
    frozen = paid_retry(client, url, body, observed_id)
    original_lookup = TaskStore.find_request
    original_matching = module.matching_task
    matched = []
    injected = []
    before_lookup = []
    accepted_tasks = []
    def matching(*args, **kwargs):
        result = original_matching(*args, **kwargs)
        matched.append(result['id'] if result else None)
        return result
    def lookup_with_concurrent_acceptance(self, db, project_id, task_type, key):
        found = original_lookup(self, db, project_id, task_type, key)
        if key == 'same-frozen-page-k' and not injected:
            assert found is None
            injected.append(True)
            before_lookup.append(len(matched))
            # Commit the very same frozen request in a second HTTP call before
            # the first lookup's empty result reaches its caller.
            accepted = client.post(url, json=frozen, headers={'Idempotency-Key': key})
            assert accepted.status_code == 202, accepted.text
            task = accepted.json()['task']
            if successor_state == 'failed':
                task = fail_task(client, task, error)
            accepted_tasks.append(task)
        return found
    monkeypatch.setattr(module, 'matching_task', matching)
    monkeypatch.setattr(TaskStore, 'find_request', lookup_with_concurrent_acceptance)
    before = persistence_counts()
    response = client.post(url, json=frozen, headers={'Idempotency-Key': 'same-frozen-page-k'})
    assert response.status_code == (202 if successor_state == 'queued' else 200), response.text
    assert response.json()['task'] == accepted_tasks[0]
    assert before_lookup == [1], 'Observe the predecessor before looking up its request key.'
    after = persistence_counts()
    assert after['tasks'] == before['tasks'] + 1
    assert after['task_outbox'] == before['task_outbox'] + 1
    assert after['model_budgets'] == before['model_budgets'] + 1
    assert after['model_calls'] == after['budget_reservations'] == 0
    assert not cloud.calls and not writer.calls
