"""Durable retry and safe history, in a disposable PostgreSQL schema."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.adapters.task_execution_store import LeaseLost, TaskExecutionStore
from app.adapters.task_store import TaskStore
from app.db.database import database_connection
from app.domain.tasks.service import TaskService
from tests.db.test_task_schema import seed_owner, insert_row, task_row


@pytest.fixture
def seeded(postgres_schema):
    with database_connection(write=True) as db:
        seed_owner(db)
        insert_row(db, 'tasks', task_row(task_type='explanation', workflow_version='explanation_v1',
            phase='interpret', input_snapshot={'result': {'setup_revision': 1}, 'output_language': 'zh-CN'}))
    return TaskExecutionStore(), TaskStore('u')


def test_retry_count_delays_exhaustion_and_normal_polling(seeded):
    store, public = seeded
    assert public.get('t')['retry_count'] == 0
    lease = store.claim('t', 1)
    for count, seconds in enumerate((10, 30, 90), 1):
        current = store.retry_failure(lease, 'model_provider_unavailable')
        assert current['status'] == 'running' and current['retry_count'] == count
        assert not store.heartbeat(lease)
        event = public.events('t')['items'][-1]
        assert event['error_code'] == 'model_provider_unavailable'
        assert event['error_category'] == 'temporary'
        assert event['retry_reason'] == 'temporary_provider_error'
        assert (event['retry_count'], event['retry_delay_seconds']) == (count, seconds)
        with database_connection() as db:
            outbox = db.execute('SELECT * FROM task_outbox ORDER BY task_revision DESC').fetchone()
            assert (outbox['available_at'] - outbox['created_at']).total_seconds() == seconds
        lease = store.claim('t', current['revision'])
        current = store.defer(lease)
        assert current['retry_count'] == count
        normal = public.events('t')['items'][-1]
        assert all(normal[key] is None for key in ('error_code', 'error_category', 'retry_reason', 'retry_count', 'retry_delay_seconds'))
        lease = store.claim('t', current['revision'])
    with database_connection() as db:
        before = len(db.execute('SELECT * FROM task_outbox').fetchall())
    final = store.retry_failure(lease, 'model_provider_unavailable')
    assert final['status'] == 'failed' and final['retry_count'] == 3
    event = public.events('t')['items'][-1]
    assert event['retry_count'] == 3 and event['retry_delay_seconds'] is None
    with database_connection() as db:
        assert len(db.execute('SELECT * FROM task_outbox').fetchall()) == before
        attempt = db.execute('SELECT * FROM task_attempts').fetchone()
        assert attempt['error_category'] == 'temporary' and attempt['error_code'] == event['error_code']


@pytest.mark.parametrize('code,expected,category', [
    ('model_authentication_failed', 'model_authentication_failed', 'authentication'),
    ('model_permission_denied', 'model_permission_denied', 'permission'),
    ('private provider body secret', 'internal_error', 'internal'),
])
def test_permanent_and_unknown_errors_fail_safely(seeded, code, expected, category):
    store, public = seeded
    final = store.retry_failure(store.claim('t', 1), code)
    assert final['status'] == 'failed' and final['retry_count'] == 0
    with database_connection() as db:
        for table in ('tasks', 'task_attempts', 'task_events'):
            row = db.execute('SELECT * FROM ' + table + (' ORDER BY seq DESC' if table == 'task_events' else '')).fetchone()
            assert row['error_code'] == expected
            if table != 'tasks':
                assert row['error_category'] == category
    assert public.events('t')['items'][-1]['error_code'] == expected


def test_attempt_keeps_last_error_on_success_and_replaces_it_on_permanent_failure(seeded):
    store, public = seeded
    current = store.retry_failure(store.claim('t', 1), 'model_provider_unavailable')
    lease = store.claim('t', current['revision'])
    failed = store.fail(lease, 'model_authentication_failed')
    with database_connection() as db:
        attempt = db.execute('SELECT * FROM task_attempts').fetchone()
        assert attempt['error_code'] == 'model_authentication_failed'
        assert attempt['error_category'] == 'authentication'
        assert attempt['retry_reason'] is None
    service = TaskService('u')
    current = service.transition('t', expected_revision=failed['revision'], status='queued', reason_code='retry_requested')
    current = store.retry_failure(store.claim('t', current['revision']), 'model_provider_unavailable')
    lease = store.claim('t', current['revision'])
    current = store.defer(lease)
    lease = store.claim('t', current['revision'])
    with store.connection(write=True) as db:
        task = store.require_lease(db, lease)
        store._finish(db, task, 'succeeded', None)
    with database_connection() as db:
        attempt = db.execute('SELECT * FROM task_attempts ORDER BY attempt_no DESC').fetchone()
        assert attempt['error_code'] == 'model_provider_unavailable'
        assert attempt['error_category'] == 'temporary'
    assert public.events('t')['items'][-1]['error_code'] is None


def test_retry_atomic_rollback_and_fenced_competition(seeded, monkeypatch):
    store, public = seeded
    lease = store.claim('t', 1)
    before = public.get('t')
    with monkeypatch.context() as patch:
        patch.setattr(TaskStore, 'append_event', staticmethod(lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('reject event'))))
        with pytest.raises(RuntimeError):
            store.retry_failure(lease, 'model_provider_unavailable')
    assert public.get('t') == before and store.heartbeat(lease)
    def retry(_):
        try:
            return store.retry_failure(lease, 'model_provider_unavailable')
        except LeaseLost:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(retry, range(2)))
    assert sum(value is not None for value in results) == 1
    assert public.get('t')['retry_count'] == 1


def test_interruption_preserves_count_manual_retry_resets_and_replay_does_not(seeded):
    from tests.integration.test_task_execution import expired
    store, public = seeded
    current = store.retry_failure(store.claim('t', 1), 'model_provider_unavailable')
    lease = store.claim('t', current['revision'])
    expired(lease)
    store.recover_expired()
    current = public.get('t')
    assert current['retry_count'] == 1
    events = public.events('t')['items']
    assert events[-2]['error_category'] == 'interrupted'
    assert events[-1]['retry_reason'] == 'worker_interrupted'
    replayed = TaskService('u').transition('t', expected_revision=current['revision'], status='queued', reason_code='retry_requested')
    assert replayed['retry_count'] == 1
    lease = store.claim('t', current['revision'])
    current = store.fail(lease, 'task_worker_interrupted')
    service = TaskService('u')
    current = service.transition('t', expected_revision=current['revision'], status='queued', reason_code='retry_requested')
    assert current['retry_count'] == 0
    assert public.events('t')['items'][-1]['retry_reason'] == 'manual_retry'
    lease = store.claim('t', current['revision'])
    current = store.retry_failure(lease, 'model_provider_unavailable')
    current = store.fail(store.claim('t', current['revision']), 'task_worker_interrupted')
    assert current['retry_count'] == 1
