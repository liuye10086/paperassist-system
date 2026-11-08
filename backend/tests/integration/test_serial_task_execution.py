"""Scheduler invariants in a disposable PostgreSQL schema, without computation."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

import pytest

from app.adapters.task_execution_store import TaskExecutionStore
from app.adapters.task_store import TaskStore
from app.db.database import database_connection
from tests.db.test_task_schema import NOW, seed_owner, task_row


@pytest.fixture
def serial_tasks(postgres_schema):
    with database_connection(write=True) as db:
        seed_owner(db)
        for number, name in enumerate(('first', 'second', 'third')):
            task = task_row(id=name, idempotency_key=name, task_type='explanation',
                input_snapshot={'result': {'setup_revision': 1}, 'output_language': 'zh-CN'},
                created_at=NOW + timedelta(seconds=number), updated_at=NOW + timedelta(seconds=number))
            TaskStore.insert_task(db, task)
            TaskStore.append_event(db, task, 'created')
            TaskStore.enqueue(db, task)
    return TaskExecutionStore()


def ready_all():
    with database_connection(write=True) as db:
        db.execute("UPDATE task_outbox SET available_at=clock_timestamp()-interval '1 second'")


def finish(store, lease, status='succeeded'):
    # Synthetic completion exercises scheduling only; it claims no artifact validation.
    with store.connection(write=True) as db:
        task = store.require_lease(db, lease)
        store._finish(db, task, status, 'task_execution_failed' if status == 'failed' else None)


@pytest.mark.parametrize('status', ['succeeded', 'failed', 'cancelled'])
def test_fifo_claim_and_next_task_after_terminal_state(serial_tasks, status):
    store = serial_tasks
    assert store.claim('second', 1) is None
    first = store.claim('first', 1)
    assert first is not None
    assert store.claim('second', 1) is None
    assert store.claim('third', 1) is None
    assert store.heartbeat(first)
    finish(store, first, status)
    ready_all()
    second = store.claim('second', 1)
    assert second is not None
    assert store.claim('second', 1) is None
    finish(store, second)
    assert store.claim('third', 1) is not None


def test_remote_defer_keeps_logical_slot_until_continuation_finishes(serial_tasks):
    store = serial_tasks
    lease = store.claim('first', 1)
    deferred = store.defer(lease, seconds=30)
    assert deferred['status'] == 'running'
    assert store.claim('second', 1) is None
    from app.workers.dispatcher import dispatch_once
    messages = []
    assert dispatch_once(publish=messages.append) == 0
    ready_all()
    assert dispatch_once(publish=messages.append) == 1
    assert messages[0]['task_id'] == 'first'
    resumed = store.claim('first', deferred['revision'])
    assert resumed.attempt_no == lease.attempt_no
    assert store.claim('second', 1) is None
    finish(store, resumed)
    ready_all()
    assert store.claim('second', 1) is not None


def test_dispatcher_only_publishes_head_and_ignores_stale_terminal_rows(serial_tasks):
    from app.workers.dispatcher import dispatch_once
    messages = []
    assert dispatch_once(publish=messages.append, limit=20) == 1
    assert [message['task_id'] for message in messages] == ['first']
    assert dispatch_once(publish=messages.append, limit=20) == 0
    lease = serial_tasks.claim('first', 1)
    finish(serial_tasks, lease)
    assert dispatch_once(publish=messages.append) == 1
    assert [message['task_id'] for message in messages] == ['first', 'second']


def test_claim_competition_between_distinct_tasks_keeps_one_attempt(serial_tasks):
    with ThreadPoolExecutor(max_workers=3) as pool:
        leases = list(pool.map(lambda task: serial_tasks.claim(task, 1), ('third', 'second', 'first')))
    assert [lease.task_id for lease in leases if lease] == ['first']
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM task_attempts').fetchone()['n'] == 1


def test_blocked_old_broker_message_rearms_same_outbox_once(serial_tasks):
    store = serial_tasks
    first = store.claim('first', 1)
    with database_connection(write=True) as db:
        db.execute("UPDATE task_outbox SET published_at=clock_timestamp() WHERE task_id='second'")
    assert store.claim('second', 1) is None
    assert store.claim('second', 1) is None
    with database_connection() as db:
        rows = db.execute("SELECT * FROM task_outbox WHERE task_id='second'").fetchall()
        assert len(rows) == 1 and rows[0]['published_at'] is None
        assert db.execute("SELECT count(*) AS n FROM task_attempts WHERE task_id='second'").fetchone()['n'] == 0
    finish(store, first)
    ready_all()
    from app.workers.dispatcher import dispatch_once
    messages = []
    assert dispatch_once(publish=messages.append) == 1
    assert messages[0]['task_id'] == 'second'
    lease = store.claim('second', 1)
    assert lease is not None
    assert store.claim('second', 1) is None


def test_old_publish_confirmation_cannot_erase_blocked_message_rearm(serial_tasks):
    from app.workers.dispatcher import dispatch_once
    store = serial_tasks
    with database_connection(write=True) as db:
        db.execute("UPDATE task_outbox SET available_at=clock_timestamp()+interval '1 hour' WHERE task_id='first'")
    messages = []
    def publish(message):
        messages.append(message)
        assert message['task_id'] == 'second'
        with database_connection(write=True) as db:
            db.execute("UPDATE task_outbox SET available_at=clock_timestamp()-interval '1 second' WHERE task_id='first'")
        lease = store.claim('first', 1)
        assert lease is not None
        assert store.claim('second', 1) is None
        finish(store, lease)
    assert dispatch_once(publish=publish) == 1
    with database_connection() as db:
        row = db.execute("SELECT * FROM task_outbox WHERE task_id='second'").fetchone()
        assert row['published_at'] is None
    ready_all()
    assert dispatch_once(publish=messages.append) == 1
    assert [message['task_id'] for message in messages] == ['second', 'second']


def test_worker_can_claim_broker_delivery_before_dispatcher_marks_confirmation(serial_tasks):
    from app.workers.dispatcher import dispatch_once
    leases = []
    def publish(message):
        leases.append(serial_tasks.claim(message['task_id'], message['task_revision']))
        assert leases[-1] is not None
    assert dispatch_once(publish=publish) == 1
    assert leases[0].task_id == 'first'
    assert serial_tasks.claim('second', 1) is None


def test_two_dispatchers_do_not_publish_same_head_concurrently(serial_tasks):
    from app.workers.dispatcher import dispatch_once
    entered, release = Event(), Event()
    messages = []
    def publish(message):
        messages.append(message)
        entered.set()
        assert release.wait(10)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(dispatch_once, publish=publish)
        try:
            assert entered.wait(10)
            # Even an expired retry reservation cannot admit a second host publisher.
            ready_all()
            second = pool.submit(dispatch_once, publish=messages.append)
            assert second.result(timeout=5) == 0
        finally:
            release.set()
        assert first.result(timeout=10) == 1
    assert len(messages) == 1
