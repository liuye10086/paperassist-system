"""Durable user actions in disposable PostgreSQL; no remote calls or worker services."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.core.exceptions import StorageError
from app.db.database import database_connection
from app.domain.tasks.service import TaskService
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_boxplot import cloud  # noqa: F401
from tests.api.test_plot_tasks import policy, post, prepared  # noqa: F401
from tests.api.test_explanation_tasks import transition
from tests.integration.test_explanations import writer  # noqa: F401


def waiting(client, kind='budget_exceeded'):
    _, _, _, url = prepared(client)
    task = post(client, url).json()['task']
    status = 'waiting_input' if kind == 'input_required' else 'waiting_confirmation'
    task = transition(client, task, status, kind)
    return task, client.get('/api/v1/auth/me').json()['user']['id']


def request_for(task):
    from app.domain.tasks.waits import get_open_wait
    with database_connection() as db:
        wait = get_open_wait(db, task)
    return dict(operation='resume', wait_id=wait['id'], expected_task_revision=task['revision'],
                input_version=task['input_version'])


def test_wait_is_durable_read_only_and_budget_resume_is_atomic(client, cloud, policy):
    from app.domain.tasks.waits import get_open_wait, allowed_recovery_actions
    from app.domain.tasks.resume import TaskResumeService
    task, owner = waiting(client)
    with database_connection() as db:
        first = get_open_wait(db, task)
        assert first['kind'] == 'budget_confirmation' and first['task_revision'] == task['revision']
        assert get_open_wait(db, task) == first
        assert allowed_recovery_actions(db, task) == ['resume']
    saved = TaskResumeService(owner).resume(task['id'], request_for(task), idempotency_key='budget-continue')
    assert saved['id'] == task['id'] and saved['status'] == 'queued'
    with database_connection() as db:
        wait = db.execute('SELECT * FROM task_waits').fetchone()
        assert wait['status'] == 'resolved' and wait['resolved_at'] is not None
        assert db.execute('SELECT count(*) AS n FROM task_resume_requests').fetchone()['n'] == 1
        assert db.execute('SELECT count(*) AS n FROM task_outbox').fetchone()['n'] == 2
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0
    assert not cloud.calls


def test_same_resume_key_is_replayed_even_after_execution_advances(client, policy):
    from app.domain.tasks.resume import TaskResumeService
    task, owner = waiting(client)
    request = request_for(task)
    service = TaskResumeService(owner)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: service.resume(task['id'], request, idempotency_key='same'), range(3)))
    assert results[0] == results[1] == results[2]
    TaskService(owner).transition(task['id'], expected_revision=results[0]['revision'], status='running')
    assert service.resume(task['id'], request, idempotency_key='same') == results[0]
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM task_resume_requests').fetchone()['n'] == 1
        assert db.execute('SELECT count(*) AS n FROM task_outbox').fetchone()['n'] == 2


def test_competing_keys_or_changed_request_cannot_resolve_one_wait_twice(client, policy):
    from app.domain.tasks.resume import TaskResumeService
    task, owner = waiting(client)
    service, request = TaskResumeService(owner), request_for(task)
    service.resume(task['id'], request, idempotency_key='accepted')
    for key, changes in [('different', {}), ('accepted', {'expected_task_revision': 1}),
                         ('accepted', {'input_version': {'setup_revision': 2, 'output_language': 'zh-CN'}})]:
        with pytest.raises(StorageError) as error:
            service.resume(task['id'], {**request, **changes}, idempotency_key=key)
        assert error.value.status == 409


@pytest.mark.parametrize('kind', ['submission_unknown', 'input_required', 'confirmation_required'])
def test_unsupported_and_unknown_waits_are_read_only(client, policy, kind):
    from app.domain.tasks.resume import TaskResumeService
    from app.domain.tasks.waits import allowed_recovery_actions
    task, owner = waiting(client, kind)
    with database_connection() as db:
        assert allowed_recovery_actions(db, task) == []
    with pytest.raises(StorageError) as error:
        TaskResumeService(owner).resume(task['id'], request_for(task), idempotency_key='forbidden')
    assert error.value.status == 409
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM task_resume_requests').fetchone()['n'] == 0
        assert db.execute('SELECT count(*) AS n FROM task_outbox').fetchone()['n'] == 1


def test_resume_failure_rolls_back_wait_receipt_event_and_outbox(client, policy, monkeypatch):
    from app.domain.tasks.resume import TaskResumeService
    from app.adapters.task_store import TaskStore
    task, owner = waiting(client)
    request = request_for(task)
    def unavailable(*args):
        raise RuntimeError('synthetic outbox failure')
    monkeypatch.setattr(TaskStore, 'enqueue', unavailable)
    with pytest.raises(RuntimeError):
        TaskResumeService(owner).resume(task['id'], request, idempotency_key='rollback')
    with database_connection() as db:
        assert db.execute('SELECT status FROM task_waits').fetchone()['status'] == 'open'
        assert db.execute('SELECT count(*) AS n FROM task_resume_requests').fetchone()['n'] == 0
        assert db.execute('SELECT count(*) AS n FROM task_events').fetchone()['n'] == 3
        assert db.execute('SELECT count(*) AS n FROM task_outbox').fetchone()['n'] == 1


def test_legacy_retry_resolves_same_wait_and_new_wait_gets_new_identity(client, policy):
    task, owner = waiting(client)
    first = request_for(task)
    response = client.post('/api/v1/tasks/' + task['id'] + '/retry', json={'expected_revision': task['revision']})
    assert response.status_code == 202
    second = transition(client, response.json(), 'waiting_confirmation', 'budget_exceeded')
    assert request_for(second)['wait_id'] != first['wait_id']
    with database_connection() as db:
        assert [row['status'] for row in db.execute('SELECT status FROM task_waits ORDER BY task_revision')] == ['resolved', 'open']


def test_resume_rejects_current_source_conflict_and_cross_owner(client, policy):
    from app.domain.tasks.resume import TaskResumeService
    task, owner = waiting(client)
    request = request_for(task)
    with pytest.raises(StorageError) as error:
        TaskResumeService('other-owner').resume(task['id'], request, idempotency_key='private')
    assert error.value.status == 404
    with database_connection(write=True) as db:
        db.execute('UPDATE analysis_setups SET revision=revision+1')
    with pytest.raises(StorageError) as error:
        TaskResumeService(owner).resume(task['id'], request, idempotency_key='stale-source')
    assert error.value.code == 'task_source_conflict'
    with database_connection() as db:
        assert db.execute('SELECT status FROM task_waits').fetchone()['status'] == 'open'


def test_receipt_insert_failure_rolls_back_all_preceding_recovery_writes(client, policy):
    from app.domain.tasks.resume import TaskResumeService
    from app.db.database import migration_connection
    task, owner = waiting(client)
    request = request_for(task)
    with migration_connection(write=True) as db:
        db.execute("""CREATE FUNCTION reject_resume_test() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'synthetic receipt failure'; END $$""")
        db.execute('CREATE TRIGGER reject_resume_test BEFORE INSERT ON task_resume_requests FOR EACH ROW EXECUTE FUNCTION reject_resume_test()')
    with pytest.raises(StorageError) as error:
        TaskResumeService(owner).resume(task['id'], request, idempotency_key='retry-after-rollback')
    assert error.value.code == 'storage_unavailable'
    with database_connection() as db:
        assert db.execute('SELECT status FROM task_waits').fetchone()['status'] == 'open'
        assert db.execute('SELECT revision,status FROM tasks').fetchone() == {'revision': task['revision'], 'status': task['status']}
        assert db.execute('SELECT count(*) AS n FROM task_resume_requests').fetchone()['n'] == 0
        assert db.execute('SELECT count(*) AS n FROM task_events').fetchone()['n'] == 3
        assert db.execute('SELECT count(*) AS n FROM task_outbox').fetchone()['n'] == 1
    with migration_connection(write=True) as db:
        db.execute('DROP TRIGGER reject_resume_test ON task_resume_requests')
        db.execute('DROP FUNCTION reject_resume_test()')
    assert TaskResumeService(owner).resume(task['id'], request, idempotency_key='retry-after-rollback')['status'] == 'queued'


def test_concurrent_distinct_keys_only_one_can_consume_wait(client, policy):
    from app.domain.tasks.resume import TaskResumeService
    task, owner = waiting(client)
    service, request = TaskResumeService(owner), request_for(task)
    def resume(key):
        try:
            return service.resume(task['id'], request, idempotency_key=key)['status']
        except StorageError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(resume, ['one', 'two']))
    assert sorted(outcomes) == ['queued', 'task_revision_conflict']
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM task_resume_requests').fetchone()['n'] == 1


@pytest.mark.parametrize('changes', [{'expected_task_revision': True}, {'expected_task_revision': '3'},
    {'expected_task_revision': 0}, {'input_version': {'setup_revision': True, 'output_language': 'zh-CN'}},
    {'input_version': {'setup_revision': 1, 'output_language': 'zh-CN', 'extra': 'ignored?'}},
    {'operation': 'retry'}, {'wait_id': None}, {'answers': {'text': 'must not be accepted'}}])
def test_resume_request_validation_is_strict(client, policy, changes):
    from app.domain.tasks.resume import TaskResumeService
    task, owner = waiting(client)
    with pytest.raises(StorageError) as error:
        TaskResumeService(owner).resume(task['id'], {**request_for(task), **changes}, idempotency_key='invalid')
    assert error.value.code == 'task_input_invalid' and error.value.status == 422


@pytest.mark.parametrize('key', ['', 'with space', '中文', 'x' * 129])
def test_resume_key_is_required_bounded_ascii(client, policy, key):
    from app.domain.tasks.resume import TaskResumeService
    task, owner = waiting(client)
    with pytest.raises(StorageError) as error:
        TaskResumeService(owner).resume(task['id'], request_for(task), idempotency_key=key)
    assert error.value.status == 422


def test_worker_budget_wait_is_persisted_and_legacy_resume_closes_it(client, policy):
    from app.domain.tasks.execution import run_boxplot_task
    _, _, _, url = prepared(client)
    task = post(client, url).json()['task']
    # No user/project budget exists. Provider construction is local and its
    # methods must never be called before all three budget checks succeed.
    class ForbiddenProvider:
        def close(self):
            pass
        def create_container(self, **kwargs):
            raise AssertionError('A waiting task cannot submit any paid work.')
    current = run_boxplot_task(task['id'], task['revision'], provider_factory=ForbiddenProvider)
    assert current['status'] == 'waiting_confirmation'
    wait = request_for(current)
    response = client.post('/api/v1/tasks/' + task['id'] + '/retry', json={'expected_revision': current['revision']})
    assert response.status_code == 202
    with database_connection() as db:
        assert db.execute('SELECT status FROM task_waits WHERE id=%s', (wait['wait_id'],)).fetchone()['status'] == 'resolved'
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0


@pytest.mark.parametrize('kind', ['boxplot', 'explanation', 'word_report'])
def test_failed_tasks_share_explicit_idempotent_safe_retry(client, policy, writer, kind):
    from app.domain.tasks.contracts import TaskCreateRequest
    from app.domain.tasks.resume import TaskResumeService
    from app.domain.tasks.waits import allowed_recovery_actions
    if kind == 'boxplot':
        _, _, _, url = prepared(client)
        task = post(client, url).json()['task']
    elif kind == 'explanation':
        from tests.integration.test_explanations import ready
        *_, figure, url = ready(client)
        task = client.post(url, json={'expected_revision': 1, 'figure_id': figure['id']}).json()['task']
    else:
        from tests.integration.test_task_execution import queued
        task, *_ = queued(client)
    owner = client.get('/api/v1/auth/me').json()['user']['id']
    failed = transition(client, task, 'failed', 'execution_failed', 'task_worker_interrupted')
    with database_connection() as db:
        assert allowed_recovery_actions(db, failed) == ['retry']
    request = dict(operation='retry', wait_id=None, expected_task_revision=failed['revision'], input_version=failed['input_version'])
    service = TaskResumeService(owner)
    accepted = service.resume(task['id'], request, idempotency_key='safe-retry')
    assert accepted['id'] == task['id'] and accepted['status'] == 'queued'
    assert service.resume(task['id'], request, idempotency_key='safe-retry') == accepted
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM task_waits').fetchone()['n'] == 0
        assert db.execute('SELECT wait_id FROM task_resume_requests').fetchone()['wait_id'] is None


@pytest.mark.parametrize('code', ['plot_container_expired', 'plot_input_limit', 'plot_invalid_result', 'model_response_not_found'])
def test_paid_regeneration_or_unavailable_response_cannot_use_generic_retry(client, policy, code):
    from app.domain.tasks.resume import TaskResumeService
    from app.domain.tasks.waits import allowed_recovery_actions
    _, _, _, url = prepared(client)
    task = post(client, url).json()['task']
    failed = transition(client, task, 'failed', 'execution_failed', code)
    owner = client.get('/api/v1/auth/me').json()['user']['id']
    with database_connection() as db:
        assert allowed_recovery_actions(db, failed) == []
    with pytest.raises(StorageError) as error:
        TaskResumeService(owner).resume(task['id'], dict(operation='retry', wait_id=None,
            expected_task_revision=failed['revision'], input_version=failed['input_version']), idempotency_key='not-a-paid-retry')
    assert error.value.status == 409


@pytest.mark.parametrize('phase', ['container', 'upload', 'response'])
def test_late_receipt_resolution_closes_persisted_unknown_wait(client, phase):
    from tests.integration.test_boxplot_execution import test_boxplot_late_receipt_requeues_unknown_task_once_without_repeating_known_post
    test_boxplot_late_receipt_requeues_unknown_task_once_without_repeating_known_post(client, phase)
    with database_connection() as db:
        wait = db.execute('SELECT * FROM task_waits').fetchone()
        assert wait['kind'] == 'submission_unknown' and wait['status'] == 'resolved'
        assert wait['resolved_task_revision'] > wait['task_revision']
        assert db.execute('SELECT count(*) AS n FROM task_resume_requests').fetchone()['n'] == 0


def test_late_definite_expiry_supersedes_unknown_wait(client):
    from tests.integration.test_boxplot_execution import test_boxplot_late_definite_upload_expiry_finishes_unknown_task_with_ledger_intact
    test_boxplot_late_definite_upload_expiry_finishes_unknown_task_with_ledger_intact(client)
    with database_connection() as db:
        wait = db.execute('SELECT * FROM task_waits').fetchone()
        assert wait['kind'] == 'submission_unknown' and wait['status'] == 'superseded'
