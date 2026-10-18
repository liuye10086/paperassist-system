"""Persisted cloud observation windows; every test owns an isolated schema."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from psycopg.types.json import Jsonb

from app.db.database import database_connection
from app.domain.model_usage.gateway import ModelGateway, ModelGatewayError
from app.core.exceptions import StorageError
from tests.integration.test_model_usage import context, configure, request, response  # noqa: F401


def test_first_submission_persists_window_and_restart_does_not_reset_it(context):
    service = configure(context)
    saved = service.reserve_call(request(context[3]))
    assert service.begin_submission(saved['id'])
    first = service.get_call(saved['id'])['provider_state']['observation']
    assert first['version'] == 1
    assert datetime.fromisoformat(first['deadline_at']) - datetime.fromisoformat(first['started_at']) == timedelta(minutes=20)
    assert not service.begin_submission(saved['id'])
    assert service.get_call(saved['id'])['provider_state']['observation'] == first


def expired(context):
    service = configure(context)
    saved = service.reserve_call(request(context[3]))
    service.begin_submission(saved['id'])
    saved = response(service, saved, status='in_progress', usage=None)
    start = datetime.now(timezone.utc) - timedelta(minutes=21)
    observation = {'version': 1, 'started_at': start.isoformat(),
                   'deadline_at': (start + timedelta(minutes=20)).isoformat(), 'continuations': 0}
    with database_connection(write=True) as db:
        db.execute('UPDATE model_calls SET provider_state=%s WHERE id=%s',
                   (Jsonb({'observation': observation}), saved['id']))
    return service, saved, observation


def test_expiry_preserves_receipt_and_reservation_without_network_or_resend(context):
    service, saved, _ = expired(context)
    before = service.get_call(saved['id'])
    provider = SimpleNamespace(retrieve=lambda *a, **kw: pytest.fail('expired window must not poll automatically'),
                               submit=lambda *a, **kw: pytest.fail('must not resubmit'))
    with pytest.raises(ModelGatewayError) as error:
        ModelGateway(service, provider).refresh(saved['id'])
    assert error.value.code == 'model_observation_expired'
    assert service.get_call(saved['id']) == before
    assert service.project_usage(context[2])['reserved_micro_usd'] > 0


def test_explicit_original_response_continuation_is_atomic_idempotent_and_preserves_first_start(context):
    from app.domain.tasks.waits import persist_wait, get_open_wait, input_version, allowed_recovery_actions
    from app.domain.tasks.resume import TaskResumeService
    service, saved, observation = expired(context)
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET status='waiting_confirmation', revision=3, reason_code='observation_expired',error_code='model_observation_expired',input_snapshot=%s WHERE id=%s",
                   (Jsonb({'result': {'setup_revision': 1}, 'output_language': 'zh-CN'}), context[3]))
        task = dict(db.execute('SELECT * FROM tasks WHERE id=%s', (context[3],)).fetchone())
        persist_wait(db, task)
        wait = get_open_wait(db, task)
        assert wait['kind'] == 'remote_observation'
        assert allowed_recovery_actions(db, task) == ['resume']
    body = dict(operation='resume', wait_id=wait['id'], expected_task_revision=3, input_version=input_version(task))
    resumer = TaskResumeService(context[1])
    result = resumer.resume(context[3], body, idempotency_key='explicit-check-original')
    assert result['status'] == 'queued'
    assert resumer.resume(context[3], body, idempotency_key='explicit-check-original') == result
    with pytest.raises(StorageError) as stale:
        resumer.resume(context[3], body, idempotency_key='stale-window')
    assert stale.value.code == 'task_revision_conflict'
    after = service.get_call(saved['id'])
    assert after['provider_response_id'] == saved['provider_response_id']
    assert after['provider_state']['observation']['started_at'] == observation['started_at']
    assert after['provider_state']['observation']['continuations'] == 1
    assert after['provider_state']['observation']['deadline_at'] == observation['deadline_at']
    grant = after['provider_state']['observation']['retrieval_grant']
    assert grant['call_id'] == saved['id'] and grant['response_id'] == saved['provider_response_id']
    assert grant['wait_id'] == wait['id'] and grant['consumed_at'] is None
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 1
        assert db.execute('SELECT count(*) AS n FROM task_resume_requests').fetchone()['n'] == 1
        assert db.execute('SELECT count(*) AS n FROM task_outbox').fetchone()['n'] == 1
        assert db.execute('SELECT status FROM task_waits').fetchone()['status'] == 'resolved'


def test_original_response_resume_rolls_back_clock_with_outbox(context, monkeypatch):
    from app.adapters.task_store import TaskStore
    from app.domain.tasks.waits import persist_wait, get_open_wait, input_version
    from app.domain.tasks.resume import TaskResumeService
    service, saved, observation = expired(context)
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET status='waiting_confirmation',revision=3,reason_code='observation_expired',input_snapshot=%s WHERE id=%s",
                   (Jsonb({'result': {'setup_revision': 1}, 'output_language': 'zh-CN'}), context[3]))
        task = dict(db.execute('SELECT * FROM tasks WHERE id=%s', (context[3],)).fetchone())
        persist_wait(db, task)
        wait = get_open_wait(db, task)
    def unavailable(*args):
        raise RuntimeError('synthetic outbox failure')
    monkeypatch.setattr(TaskStore, 'enqueue', unavailable)
    body = dict(operation='resume', wait_id=wait['id'], expected_task_revision=3, input_version=input_version(task))
    with pytest.raises(RuntimeError):
        TaskResumeService(context[1]).resume(context[3], body, idempotency_key='rollback-check')
    assert service.get_call(saved['id'])['provider_state']['observation'] == observation
    with database_connection() as db:
        assert db.execute('SELECT status FROM task_waits').fetchone()['status'] == 'open'
        assert db.execute('SELECT count(*) AS n FROM task_resume_requests').fetchone()['n'] == 0


def test_legacy_call_uses_persisted_created_at_not_restart_time(context):
    service, saved, _ = expired(context)
    with database_connection(write=True) as db:
        db.execute('UPDATE model_calls SET provider_state=NULL,created_at=%s WHERE id=%s',
                   (datetime.now(timezone.utc) - timedelta(minutes=21), saved['id']))
    provider = SimpleNamespace(retrieve=lambda *a, **kw: pytest.fail('legacy expiry must not restart'))
    with pytest.raises(ModelGatewayError) as error:
        ModelGateway(service, provider).refresh(saved['id'])
    assert error.value.code == 'model_observation_expired'


def resumed(context, *, parallel=False):
    from app.domain.tasks.waits import persist_wait, get_open_wait, input_version
    from app.domain.tasks.resume import TaskResumeService
    service, saved, observation = expired(context)
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET status='waiting_confirmation',revision=3,reason_code='observation_expired',error_code='model_observation_expired',input_snapshot=%s WHERE id=%s",
                   (Jsonb({'result': {'setup_revision': 1}, 'output_language': 'zh-CN'}), context[3]))
        task = dict(db.execute('SELECT * FROM tasks WHERE id=%s', (context[3],)).fetchone())
        persist_wait(db, task)
        wait = get_open_wait(db, task)
    body = dict(operation='resume', wait_id=wait['id'], expected_task_revision=3, input_version=input_version(task))
    def resume():
        return TaskResumeService(context[1]).resume(context[3], body, idempotency_key='once-for-this-wait')
    if parallel:
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        ready = Barrier(2)
        def race(_):
            ready.wait(timeout=10)
            return resume()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(race, range(2)))
        assert results[0] == results[1]
    else:
        resume()
    return service, saved, observation, wait, body


@pytest.mark.parametrize('outcome', ['pending', 'failed', 'network_failure', 'malformed'])
def test_expired_continuation_authorizes_exactly_one_get_and_never_renews_window(context, outcome):
    service, saved, observation, wait, _ = resumed(context)
    calls = []
    def retrieve(response_id, **kwargs):
        calls.append(response_id)
        committed = service.get_call(saved['id'])['provider_state']['observation']['retrieval_grant']
        assert committed['consumed_at'] is not None
        if outcome == 'network_failure':
            raise RuntimeError('synthetic provider unavailable')
        if outcome == 'malformed':
            return {'response_id': 'foreign'}
        return dict(response_id=response_id, request_id='req-single', model='test-model',
                    status='failed' if outcome == 'failed' else 'in_progress', usage=None, response=None)
    provider = SimpleNamespace(retrieve=retrieve, create=lambda **_: pytest.fail('no new POST'))
    gateway = ModelGateway(service, provider)
    for _ in range(2):
        with pytest.raises(ModelGatewayError) as error:
            gateway.refresh(saved['id'])
        assert error.value.code == 'model_observation_expired'
    assert calls == [saved['provider_response_id']]
    observed = service.get_call(saved['id'])['provider_state']['observation']
    assert observed['started_at'] == observation['started_at']
    assert observed['deadline_at'] == observation['deadline_at']
    assert observed['retrieval_grant']['wait_id'] == wait['id']
    assert observed['retrieval_grant']['consumed_at'] is not None
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 1
        assert db.execute('SELECT count(*) AS n FROM budget_reservations').fetchone()['n'] == 3
        assert all(row['status'] == 'held' for row in db.execute('SELECT status FROM budget_reservations').fetchall())


def test_parallel_resume_and_refresh_cannot_duplicate_the_single_get_grant(context):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.domain.tasks.resume import TaskResumeService
    service, saved, observation, wait, body = resumed(context, parallel=True)
    calls, ready = [], Barrier(2)
    def retrieve(response_id, **kwargs):
        calls.append(response_id)
        return dict(response_id=response_id, request_id='req-once', model='test-model', status='in_progress', usage=None, response=None)
    gateway = ModelGateway(service, SimpleNamespace(retrieve=retrieve))
    def refresh(_):
        ready.wait(timeout=10)
        with pytest.raises(ModelGatewayError) as error:
            gateway.refresh(saved['id'])
        return error.value.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(refresh, range(2))) == ['model_observation_expired'] * 2
    assert calls == [saved['provider_response_id']]
    consumed = service.get_call(saved['id'])['provider_state']['observation']
    assert consumed['continuations'] == 1 and consumed['deadline_at'] == observation['deadline_at']
    TaskResumeService(context[1]).resume(context[3], body, idempotency_key='once-for-this-wait')
    assert service.get_call(saved['id'])['provider_state']['observation'] == consumed
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM task_resume_requests').fetchone()['n'] == 1
        assert db.execute('SELECT count(*) AS n FROM task_outbox').fetchone()['n'] == 1


def test_single_get_can_save_terminal_receipt_without_resetting_original_deadline(context):
    service, saved, observation, _, _ = resumed(context)
    calls = []
    def retrieve(response_id, **kwargs):
        calls.append(response_id)
        return dict(response_id=response_id, request_id='req-completed', model='test-model', status='completed',
                    usage={'input_tokens': 50, 'output_tokens': 5}, response={'output': 'saved'})
    value = ModelGateway(service, SimpleNamespace(retrieve=retrieve)).refresh(saved['id'])
    assert value['response'] == {'output': 'saved'}
    assert value['call']['status'] == 'completed'
    observed = service.get_call(saved['id'])['provider_state']['observation']
    assert observed['started_at'] == observation['started_at'] and observed['deadline_at'] == observation['deadline_at']
    assert observed['retrieval_grant']['consumed_at'] is not None
    with pytest.raises(ModelGatewayError) as error:
        ModelGateway(service, SimpleNamespace(retrieve=retrieve)).refresh(saved['id'])
    assert error.value.code == 'model_observation_expired'
    assert calls == [saved['provider_response_id']]


@pytest.mark.parametrize('damage', ['missing_consumed', 'foreign_call', 'foreign_response', 'foreign_wait'])
def test_only_a_complete_grant_bound_to_the_resolved_wait_can_be_consumed(context, damage):
    service, saved, _, _, _ = resumed(context)
    state = service.get_call(saved['id'])['provider_state']
    grant = state['observation']['retrieval_grant']
    if damage == 'missing_consumed':
        grant.pop('consumed_at')
    else:
        grant[{'foreign_call': 'call_id', 'foreign_response': 'response_id', 'foreign_wait': 'wait_id'}[damage]] = 'foreign'
    with database_connection(write=True) as db:
        db.execute('UPDATE model_calls SET provider_state=%s WHERE id=%s', (Jsonb(state), saved['id']))
    provider = SimpleNamespace(retrieve=lambda *a, **kw: pytest.fail('unbound grant reached provider'))
    with pytest.raises(ModelGatewayError) as error:
        ModelGateway(service, provider).refresh(saved['id'])
    assert error.value.code == 'model_observation_expired'


def test_pending_single_get_returns_to_new_wait_and_needs_another_explicit_decision(context):
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.domain.tasks.waits import get_open_wait, input_version
    from app.domain.tasks.resume import TaskResumeService
    service, saved, observation, old_wait, _ = resumed(context)
    repository = TaskExecutionStore(config=context[0].store.config)
    lease = repository.claim(context[3], 4, task_type='boxplot')
    assert lease is not None
    calls = []
    def retrieve(response_id, **kwargs):
        calls.append(response_id)
        return dict(response_id=response_id, request_id='req-pending', model='test-model', status='in_progress', usage=None, response=None)
    with pytest.raises(ModelGatewayError) as error:
        ModelGateway(service, SimpleNamespace(retrieve=retrieve)).refresh(saved['id'])
    waiting = repository.retry_failure(lease, error.value.code)
    assert waiting['status'] == 'waiting_confirmation' and waiting['reason_code'] == 'observation_expired'
    with database_connection() as db:
        task = dict(db.execute('SELECT * FROM tasks WHERE id=%s', (context[3],)).fetchone())
        wait = get_open_wait(db, task)
    assert wait['id'] != old_wait['id']
    body = dict(operation='resume', wait_id=wait['id'], expected_task_revision=task['revision'], input_version=input_version(task))
    TaskResumeService(context[1]).resume(context[3], body, idempotency_key='explicit-second-get')
    after = service.get_call(saved['id'])['provider_state']['observation']
    assert after['deadline_at'] == observation['deadline_at'] and after['started_at'] == observation['started_at']
    assert after['continuations'] == 2 and after['retrieval_grant']['consumed_at'] is None
    with pytest.raises(ModelGatewayError):
        ModelGateway(service, SimpleNamespace(retrieve=retrieve)).refresh(saved['id'])
    assert calls == [saved['provider_response_id']] * 2
