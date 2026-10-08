"""Atomic task policy budgets and model admission fencing in isolated schemas."""
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb

from app.adapters.task_execution_store import LeaseLost, TaskLease
from app.core.exceptions import StorageError
from app.db.database import database_connection
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_boxplot import cloud  # noqa: F401
from tests.domain.test_explanation_policy import execution_policy
from tests.integration.test_explanations import ready
from tests.integration.test_model_usage import context, configure, request  # noqa: F401


def install_lease(task_id, *, attempt=1, expired=False):
    token = str(uuid4())
    with database_connection(write=True) as db:
        now = db.execute('SELECT clock_timestamp() AS now').fetchone()['now']
        db.execute('UPDATE tasks SET current_attempt=%s WHERE id=%s', (attempt, task_id))
        db.execute('''INSERT INTO task_attempts
            (id,task_id,attempt_no,status,started_at,lease_owner,lease_expires_at,heartbeat_at)
            VALUES (%s,%s,%s,'running',%s,%s,%s,%s)''',
            (str(uuid4()), task_id, attempt, now, token, now + timedelta(seconds=-1 if expired else 60), now))
    return TaskLease(task_id, attempt, token)


def test_valid_successor_lease_can_submit_reserved_call_at_current_revision(context):
    service = configure(context)
    saved = service.reserve_call(request(context[3]))
    lease = install_lease(context[3], attempt=2)
    with database_connection(write=True) as db:
        db.execute('UPDATE tasks SET revision=4 WHERE id=%s', (context[3],))
    assert service.reserve_call(request(context[3], expected_task_revision=4), execution_lease=lease)['id'] == saved['id']
    assert service.begin_submission(saved['id'], execution_lease=lease, expected_task_revision=4)
    assert not service.begin_submission(saved['id'], execution_lease=lease, expected_task_revision=4)


@pytest.mark.parametrize('damage', ['expired', 'token', 'attempt', 'task'])
def test_invalid_lease_cannot_reserve_budget(context, damage):
    service = configure(context)
    lease = install_lease(context[3], expired=damage == 'expired')
    if damage == 'token':
        lease = TaskLease(lease.task_id, lease.attempt_no, 'stale')
    elif damage == 'attempt':
        lease = TaskLease(lease.task_id, 9, lease.lease_owner)
    elif damage == 'task':
        lease = TaskLease(str(uuid4()), lease.attempt_no, lease.lease_owner)
    with pytest.raises(LeaseLost):
        service.reserve_call(request(context[3]), execution_lease=lease)
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0


def test_lost_lease_after_reservation_cannot_begin_submission(context):
    service = configure(context)
    lease = install_lease(context[3])
    saved = service.reserve_call(request(context[3]), execution_lease=lease)
    with database_connection(write=True) as db:
        db.execute('UPDATE task_attempts SET lease_expires_at=clock_timestamp() WHERE task_id=%s', (context[3],))
    with pytest.raises(LeaseLost):
        service.begin_submission(saved['id'], execution_lease=lease, expected_task_revision=2)
    assert service.get_call(saved['id'])['status'] == 'reserved'


def test_lease_does_not_bypass_expected_revision(context):
    service = configure(context)
    lease = install_lease(context[3])
    saved = service.reserve_call(request(context[3]), execution_lease=lease)
    with pytest.raises(StorageError) as error:
        service.begin_submission(saved['id'], execution_lease=lease, expected_task_revision=99)
    assert error.value.code == 'task_revision_conflict'


def test_old_snapshot_defaults_are_normalized_during_idempotent_replay(context):
    service = configure(context)
    saved = service.reserve_call(request(context[3]))
    assert saved['policy_snapshot']['output_format'] == 'text'
    original = saved['policy_snapshot'].copy()
    original.pop('output_format')
    with database_connection(write=True) as db:
        db.execute('UPDATE model_calls SET policy_snapshot=%s WHERE id=%s', (Jsonb(original), saved['id']))
    assert service.reserve_call(request(context[3]))['id'] == saved['id']


def create_input(client):
    from app.domain.tasks.contracts import TaskCreateRequest
    from app.domain.tasks.service import TaskService
    from tests.helpers.tasks import task_owner
    base, file, result, figure, _ = ready(client)
    request = TaskCreateRequest(task_type='explanation', file_id=file['id'], analysis_run_id=result['id'],
                               expected_revision=result['setup_revision'], figure_id=figure['id'])
    return TaskService(task_owner(client)), base.split('/')[4], request


def test_task_policy_and_budget_are_frozen_in_creation_transaction(client, cloud):
    service, project, value = create_input(client)
    config = execution_policy()
    task, created = service.create(project, value, idempotency_key='policy', explanation_policy=config)
    assert created
    config['task_limit_micro_usd'] += 1
    with database_connection() as db:
        stored = db.execute('SELECT input_snapshot FROM tasks WHERE id=%s', (task['id'],)).fetchone()['input_snapshot']
        budget = db.execute('SELECT * FROM model_budgets WHERE task_id=%s', (task['id'],)).fetchone()
    assert stored['explanation_policy'] == execution_policy()
    assert budget['limit_micro_usd'] == execution_policy()['task_limit_micro_usd'] and budget['revision'] == 1
    assert 'explanation_policy' not in task
    repeated, created = service.create(project, value, idempotency_key='policy', explanation_policy={'invalid': True})
    assert not created and repeated['id'] == task['id']


def test_task_budget_rolls_back_if_outbox_creation_fails(client, cloud, monkeypatch):
    from app.adapters.task_store import TaskStore
    service, project, value = create_input(client)
    def failure(*args):
        raise RuntimeError('synthetic failure')
    monkeypatch.setattr(TaskStore, 'enqueue', failure)
    with pytest.raises(RuntimeError):
        service.create(project, value, idempotency_key='policy', explanation_policy=execution_policy())
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM tasks').fetchone()['n'] == 0
        assert db.execute('SELECT count(*) AS n FROM model_budgets').fetchone()['n'] == 0


def test_generic_explanation_task_can_persist_without_config(client, cloud, monkeypatch):
    from app.domain import explanation_policy
    monkeypatch.setattr(explanation_policy, 'local_config', lambda: {})
    service, project, value = create_input(client)
    task, _ = service.create(project, value, idempotency_key='no-policy')
    with database_connection() as db:
        stored = db.execute('SELECT input_snapshot FROM tasks WHERE id=%s', (task['id'],)).fetchone()['input_snapshot']
        assert 'explanation_policy' not in stored
        assert db.execute('SELECT count(*) AS n FROM model_budgets').fetchone()['n'] == 0


@pytest.mark.parametrize('same_header', [False, True])
def test_source_admission_is_atomic_across_request_headers(client, cloud, same_header):
    service, project, value = create_input(client)
    barrier = Barrier(2)
    def submit(number):
        barrier.wait(timeout=10)
        try:
            return service.create(project, value, idempotency_key='same' if same_header else f'key-{number}',
                                  explanation_policy=execution_policy(), explanation_predecessor=None)
        except StorageError as error:
            assert error.code == 'task_revision_conflict'
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(submit, range(2)))
    accepted = [result for result in outcomes if result is not None]
    assert len(accepted) == (2 if same_header else 1)
    assert sum(created for _, created in accepted) == 1
    assert len({task['id'] for task, _ in accepted}) == 1
    with database_connection() as db:
        for table in ('tasks', 'task_outbox', 'model_budgets'):
            assert db.execute(f'SELECT count(*) AS n FROM {table}').fetchone()['n'] == 1


def test_source_admission_rejects_changed_predecessor_and_keeps_header_digest(client, cloud):
    service, project, value = create_input(client)
    first, _ = service.create(project, value, idempotency_key='initial',
                              explanation_policy=execution_policy(), explanation_predecessor=None)
    with pytest.raises(StorageError) as error:
        service.create(project, value, idempotency_key='successor', explanation_policy=execution_policy(),
                       explanation_predecessor=first['id'])
    assert error.value.code == 'task_revision_conflict'
    running = service.transition(first['id'], expected_revision=1, status='running')
    service.transition(first['id'], expected_revision=running['revision'], status='failed', reason_code='execution_failed')
    second, _ = service.create(project, value, idempotency_key='successor', explanation_policy=execution_policy(),
                               explanation_predecessor=first['id'])
    with pytest.raises(StorageError) as stale:
        service.create(project, value, idempotency_key='stale', explanation_policy=execution_policy(),
                       explanation_predecessor=first['id'])
    assert stale.value.code == 'task_revision_conflict'
    replay, created = service.create(project, value, idempotency_key='successor',
                                    explanation_policy={'invalid': True}, explanation_predecessor=first['id'])
    assert replay['id'] == second['id'] and not created
    with pytest.raises(StorageError) as conflict:
        service.create(project, value.model_copy(update={'expected_revision': 2}), idempotency_key='successor',
                       explanation_predecessor=first['id'])
    assert conflict.value.code == 'task_idempotency_conflict'
