"""Real PostgreSQL execution slices with synthetic model receipts; no cloud I/O."""
from concurrent.futures import ThreadPoolExecutor
import json

import pytest
from psycopg.types.json import Jsonb

from app.adapters.task_execution_store import LeaseLost, TaskExecutionStore
from app.adapters.task_store import TaskStore
from app.db.database import database_connection
from app.domain.tasks.contracts import TaskCreateRequest
from app.domain.tasks.service import TaskService
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_boxplot import cloud  # noqa: F401
from tests.domain.test_explanation_content import valid_draft
from tests.helpers.tasks import task_owner
from tests.integration.test_explanations import ready
from tests.integration.test_task_execution import expired


def queued(client):
    base, file, result, figure, _ = ready(client)
    owner = task_owner(client)
    task, _ = TaskService(owner).create(base.split('/')[4], TaskCreateRequest(
        task_type='explanation', file_id=file['id'], analysis_run_id=result['id'],
        expected_revision=result['setup_revision'], figure_id=figure['id']), idempotency_key='explanation-test')
    return task, owner, base, result, figure


def test_explanation_defer_revokes_lease_and_resumes_same_attempt(client, cloud):
    task, owner, *_ = queued(client)
    store = TaskExecutionStore()
    lease = store.claim(task['id'], task['revision'])
    assert lease is not None, 'Explanation tasks must be claimable.'
    deferred = store.defer(lease, seconds=5)
    assert deferred['status'] == 'running' and deferred['revision'] == 3
    assert not store.heartbeat(lease)
    with pytest.raises(LeaseLost):
        store.fail(lease, 'task_execution_failed')
    with database_connection() as db:
        attempt = db.execute('SELECT * FROM task_attempts WHERE task_id=%s', (task['id'],)).fetchone()
        assert attempt['status'] == 'running'
        assert all(attempt[key] is None for key in ('lease_owner', 'lease_expires_at', 'heartbeat_at'))
        outbox = db.execute('SELECT * FROM task_outbox WHERE task_id=%s ORDER BY task_revision DESC',
                            (task['id'],)).fetchone()
        assert outbox['task_revision'] == 3
        assert (outbox['available_at'] - outbox['created_at']).total_seconds() >= 5
    assert store.recover_expired() == 0
    with ThreadPoolExecutor(max_workers=2) as pool:
        leases = list(pool.map(lambda _: store.claim(task['id'], 3), range(2)))
    resumed = next(item for item in leases if item)
    assert sum(item is not None for item in leases) == 1
    assert resumed.attempt_no == lease.attempt_no == 1 and resumed.lease_owner != lease.lease_owner
    assert TaskStore(owner).get(task['id'])['revision'] == 3
    assert [item['event_type'] for item in TaskStore(owner).events(task['id'])['items']] == [
        'created', 'started', 'deferred']


def test_explanation_expired_attempt_is_requeued_and_old_lease_fenced(client, cloud):
    task, owner, *_ = queued(client)
    store = TaskExecutionStore()
    lease = store.claim(task['id'], 1)
    assert lease is not None, 'Explanation tasks must be claimable.'
    expired(lease)
    assert store.recover_expired() == 1
    current = TaskStore(owner).get(task['id'])
    assert current['status'] == 'queued'
    assert store.claim(task['id'], current['revision']).attempt_no == 2
    with pytest.raises(LeaseLost):
        store.defer(lease)


def test_explanation_dispatcher_publishes_only_identifiers(client, cloud):
    from app.workers.dispatcher import dispatch_once
    task, *_ = queued(client)
    messages = []
    assert dispatch_once(publish=messages.append) == 1
    assert set(messages[0]) == {'id', 'task_id', 'task_revision'}
    assert messages[0]['task_id'] == task['id']


def execution_setup(client):
    from app.domain.explanation_content import VERSION
    from app.domain.model_usage.service import ModelUsageService
    task, owner, base, result, figure = queued(client)
    frozen = {'policy': {'model': 'test-explanation', 'prompt_version': VERSION,
        'max_output_tokens': 10000, 'timeout_seconds': 15, 'tools': [],
        'output_format': 'analysis_explanation_v1', 'price': {
            'version': 'synthetic-only', 'currency': 'USD', 'model': 'test-explanation',
            'input_micro_usd_per_million': 100, 'cached_input_micro_usd_per_million': 50,
            'output_micro_usd_per_million': 200, 'cache_write_micro_usd_per_million': 100}},
        'input_token_allowance': 100000, 'task_limit_micro_usd': 1000000}
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET input_snapshot=jsonb_set(input_snapshot,'{explanation_policy}',%s) WHERE id=%s",
                   (Jsonb(frozen), task['id']))
    service = ModelUsageService(owner)
    for scope, key in [('user', owner), ('project', task['project_id']), ('task', task['id'])]:
        service.set_budget(scope, key, 1000000, 0)
    return task, owner, base, result, figure, service


class SyntheticProvider:
    def __init__(self, *, pending=False, corrupt=False, fail_create=False, fail_get=False):
        self.pending, self.corrupt = pending, corrupt
        self.fail_create, self.fail_get = fail_create, fail_get
        self.posts, self.gets, self.closed = [], [], 0
        self.on_create = None
        self.response_id = 'resp_explanation_test'

    def receipt(self):
        payload = self.posts[0][1]
        draft = valid_draft(payload)
        if self.corrupt:
            draft['results'] += ' 均值为999。'
        usage = {'input_tokens': 100, 'output_tokens': 50, 'total_tokens': 150,
                 'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0}}
        response = {'id': self.response_id, 'model': 'test-explanation',
            'status': 'in_progress' if self.pending else 'completed', 'usage': usage,
            'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(draft)}]}]}
        return {'response_id': response['id'], 'request_id': 'req_synthetic',
                'model': response['model'], 'status': response['status'], 'usage': usage, 'response': response}

    def create(self, *, policy, instructions, payload):
        self.posts.append((policy, payload))
        if self.on_create:
            self.on_create()
        if self.fail_create:
            raise RuntimeError('private provider response')
        return self.receipt()

    def retrieve(self, response_id, *, policy):
        self.gets.append(response_id)
        if self.fail_get:
            raise RuntimeError('private provider response')
        return self.receipt()

    def close(self):
        self.closed += 1


def run(task, provider):
    from app.domain.tasks import execution
    assert hasattr(execution, 'run_explanation_task'), 'Explanation executor must be implemented.'
    return execution.run_explanation_task(task['id'], task['revision'], provider_factory=lambda: provider)


def test_pending_response_releases_worker_then_completes_same_call_and_attempt(client, cloud):
    task, owner, _, _, _, service = execution_setup(client)
    provider = SyntheticProvider(pending=True)
    first = run(task, provider)
    assert first['status'] == 'running' and first['revision'] == 3
    assert first['current_attempt'] == 1
    provider.pending = False
    finished = run(first, provider)
    assert finished['status'] == 'succeeded' and finished['result_explanation_id']
    assert len(provider.posts) == 1 and len(provider.gets) == 1 and provider.closed == 2
    assert finished['current_attempt'] == 1
    assert run(task, provider) is None
    with database_connection() as db:
        saved = json.loads(db.execute('SELECT explanation_json FROM explanations').fetchone()['explanation_json'])
        call = db.execute('SELECT * FROM model_calls').fetchone()
        assert saved['provenance']['model_call_id'] == call['id']
        assert saved['provenance']['model_input_digest'] == call['input_digest']
        assert saved['provenance']['input_sha256'] != call['input_digest']
        assert len(db.execute('SELECT * FROM task_attempts').fetchall()) == 1
        assert {r['status'] for r in db.execute('SELECT status FROM budget_reservations')} == {'settled'}


def test_budget_missing_waits_without_post_or_call(client, cloud):
    task, owner, *_ = execution_setup(client)
    with database_connection(write=True) as db:
        db.execute("DELETE FROM model_budgets WHERE scope_type='task'")
    provider = SyntheticProvider()
    waiting = run(task, provider)
    assert waiting['status'] == 'waiting_confirmation' and waiting['reason_code'] == 'budget_exceeded'
    assert provider.posts == []
    with database_connection() as db:
        assert not db.execute('SELECT id FROM model_calls').fetchall()


def test_unconfigured_snapshot_waits_without_initializing_provider(client, cloud):
    task, *_ = queued(client)
    provider = SyntheticProvider()
    waiting = run(task, provider)
    assert waiting['status'] == 'waiting_confirmation'
    assert waiting['reason_code'] == 'budget_exceeded'
    assert waiting['error_code'] == 'explanation_not_configured'
    assert provider.posts == [] and provider.closed == 0


def test_unknown_submission_waits_and_never_reposts(client, cloud):
    task, owner, *_ = execution_setup(client)
    provider = SyntheticProvider(fail_create=True)
    waiting = run(task, provider)
    assert waiting['status'] == 'waiting_confirmation' and waiting['reason_code'] == 'submission_unknown'
    assert run(task, provider) is None and len(provider.posts) == 1
    with database_connection() as db:
        call = db.execute('SELECT * FROM model_calls').fetchone()
        assert call['status'] == 'submission_unknown' and call['provider_response_id'] is None
        assert {r['status'] for r in db.execute('SELECT status FROM budget_reservations')} == {'held'}


def test_bad_business_output_fails_after_usage_is_saved(client, cloud):
    task, *_ = execution_setup(client)
    failed = run(task, SyntheticProvider(corrupt=True))
    assert failed['status'] == 'failed' and failed['error_code'] == 'explanation_invalid'
    with database_connection() as db:
        assert not db.execute('SELECT id FROM explanations').fetchall()
        assert db.execute('SELECT status FROM model_calls').fetchone()['status'] == 'completed'
        assert {r['status'] for r in db.execute('SELECT status FROM budget_reservations')} == {'settled'}


@pytest.mark.parametrize('failure', ['explanation', 'success_event'])
def test_explanation_save_failure_preserves_response_and_lease_for_recovery(client, cloud, monkeypatch, failure):
    from app.db.database import DatabaseConnection
    task, owner, *_ = execution_setup(client)
    provider = SyntheticProvider()
    original = DatabaseConnection.execute
    def reject(db, sql, parameters=()):
        if (failure == 'explanation' and 'INSERT INTO explanations' in sql
                or failure == 'success_event' and 'INSERT INTO task_events' in sql and parameters[3] == 'succeeded'):
            raise RuntimeError('synthetic persistence failure')
        return original(db, sql, parameters)
    with monkeypatch.context() as patch:
        patch.setattr(DatabaseConnection, 'execute', reject)
        run(task, provider)
    current = TaskStore(owner).get(task['id'])
    assert current['status'] == 'running'
    with database_connection(write=True) as db:
        db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second'")
        assert db.execute('SELECT provider_response_id FROM model_calls').fetchone()['provider_response_id']
        assert not db.execute('SELECT id FROM explanations').fetchall()
    assert TaskExecutionStore().recover_expired() == 1
    finished = run(TaskStore(owner).get(task['id']), provider)
    assert finished['status'] == 'succeeded' and finished['current_attempt'] == 2
    assert len(provider.posts) == len(provider.gets) == 1


def test_reserved_call_survives_attempt_recovery_without_new_reservation(client, cloud):
    from app.adapters.openai_explanation import INSTRUCTIONS
    from app.domain.model_usage.contracts import CallRequest, ModelPolicy
    from app.domain.model_usage.gateway import input_digest
    task, owner, _, _, _, service = execution_setup(client)
    repository = TaskExecutionStore()
    lease = repository.claim(task['id'], 1)
    current, _, payload = repository.load_explanation(lease)
    frozen = current['input_snapshot']['explanation_policy']
    call = service.reserve_call(CallRequest(task_id=task['id'], expected_task_revision=current['revision'],
        call_key='explanation:v1', input_digest=input_digest(instructions=INSTRUCTIONS, payload=payload),
        policy=ModelPolicy.model_validate(frozen['policy']), input_token_allowance=frozen['input_token_allowance']),
        execution_lease=lease)
    expired(lease)
    assert repository.recover_expired() == 1
    provider = SyntheticProvider()
    finished = run(TaskStore(owner).get(task['id']), provider)
    assert finished['status'] == 'succeeded' and finished['current_attempt'] == 2
    assert len(provider.posts) == 1 and not provider.gets
    with database_connection() as db:
        assert [row['id'] for row in db.execute('SELECT id FROM model_calls')] == [call['id']]
        assert len(db.execute('SELECT * FROM budget_reservations').fetchall()) == 3


def test_transient_get_releases_lease_with_longer_delay_and_retains_response(client, cloud):
    task, owner, *_ = execution_setup(client)
    provider = SyntheticProvider(pending=True)
    pending = run(task, provider)
    provider.fail_get = True
    deferred = run(pending, provider)
    assert deferred['status'] == 'running' and deferred['current_attempt'] == 1
    with database_connection() as db:
        outbox = db.execute('SELECT * FROM task_outbox ORDER BY task_revision DESC').fetchone()
        assert (outbox['available_at'] - outbox['created_at']).total_seconds() >= 30
        assert db.execute('SELECT provider_response_id FROM model_calls').fetchone()['provider_response_id']
        assert db.execute('SELECT lease_owner FROM task_attempts').fetchone()['lease_owner'] is None
    provider.fail_get = provider.pending = False
    assert run(deferred, provider)['status'] == 'succeeded'
    assert len(provider.posts) == 1 and len(provider.gets) == 2


def test_known_response_404_fails_without_posting_again(client, cloud):
    from app.adapters.models.openai_responses import ModelProviderError
    task, *_ = execution_setup(client)
    provider = SyntheticProvider(pending=True)
    pending = run(task, provider)
    def missing(*args, **kwargs):
        raise ModelProviderError(status_code=404)
    provider.retrieve = missing
    failed = run(pending, provider)
    assert failed['status'] == 'failed' and failed['error_code'] == 'model_response_not_found'
    assert len(provider.posts) == 1
    with database_connection() as db:
        assert {row['status'] for row in db.execute('SELECT status FROM budget_reservations')} == {'held'}


def test_source_changed_after_model_completion_rejects_explanation_but_keeps_usage(client, cloud):
    task, _, base, result, *_ = execution_setup(client)
    provider = SyntheticProvider()
    provider.on_create = lambda: client.put(base + '/analysis-setup', json={
        **result['selection'], 'expected_revision': 1, 'unit': 'changed'})
    failed = run(task, provider)
    assert failed['status'] == 'failed' and failed['error_code'] == 'task_source_conflict'
    with database_connection() as db:
        assert not db.execute('SELECT * FROM explanations').fetchall()
        assert db.execute('SELECT status FROM model_calls').fetchone()['status'] == 'completed'


def test_expired_worker_cannot_publish_explanation_and_successor_only_retrieves(client, cloud):
    task, owner, *_ = execution_setup(client)
    provider = SyntheticProvider()
    def lose_lease():
        with database_connection(write=True) as db:
            db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second'")
    provider.on_create = lose_lease
    assert run(task, provider) is None
    with database_connection() as db:
        assert not db.execute('SELECT id FROM explanations').fetchall()
    repository = TaskExecutionStore()
    assert repository.recover_expired() == 1
    finished = run(TaskStore(owner).get(task['id']), provider)
    assert finished['status'] == 'succeeded'
    assert len(provider.posts) == len(provider.gets) == 1


def same_source_task(task_id, owner):
    with database_connection() as db:
        source = dict(db.execute('SELECT * FROM tasks WHERE id=%s', (task_id,)).fetchone())
    snapshot = source['input_snapshot']
    return TaskService(owner).create(source['project_id'], TaskCreateRequest(task_type='explanation',
        file_id=snapshot['file']['id'], analysis_run_id=snapshot['result']['id'],
        expected_revision=snapshot['result']['setup_revision'], figure_id=snapshot['figure']['id']),
        idempotency_key='different-header', explanation_policy=snapshot['explanation_policy'])[0]


@pytest.mark.parametrize('corrupt_cached', [False, True])
def test_existing_explanation_is_validated_and_reused_without_provider(client, cloud, corrupt_cached):
    task, owner, *_ = execution_setup(client)
    first = run(task, SyntheticProvider())
    assert first['status'] == 'succeeded'
    second = same_source_task(task['id'], owner)
    if corrupt_cached:
        with database_connection(write=True) as db:
            row = db.execute('SELECT * FROM explanations').fetchone()
            value = json.loads(row['explanation_json'])
            value['provenance']['input_sha256'] = '0' * 64
            db.execute('UPDATE explanations SET explanation_json=%s WHERE id=%s', (json.dumps(value), row['id']))
    provider = SyntheticProvider()
    finished = run(second, provider)
    if corrupt_cached:
        assert finished['status'] == 'failed' and finished['error_code'] == 'task_source_conflict'
    else:
        assert finished['status'] == 'succeeded'
        assert finished['result_explanation_id'] == first['result_explanation_id']
    assert provider.posts == [] and provider.closed == 0
    with database_connection() as db:
        assert len(db.execute('SELECT id FROM model_calls').fetchall()) == 1


def test_final_source_reads_cannot_outlive_publication_lease(client, cloud, monkeypatch):
    from datetime import datetime, timezone
    task, *_ = queued(client)
    repository = TaskExecutionStore()
    lease = repository.claim(task['id'], 1)
    _, snapshot, _ = repository.load_explanation(lease)
    require_lease = repository.require_lease
    def expire_after_first_check(db, current):
        result = require_lease(db, current)
        db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second'")
        return result
    monkeypatch.setattr(repository, 'require_lease', expire_after_first_check)
    with pytest.raises(LeaseLost):
        repository.complete_explanation(lease, snapshot, {'created_at': datetime.now(timezone.utc).isoformat()})
    with database_connection() as db:
        assert not db.execute('SELECT id FROM explanations').fetchall()


def test_later_cached_result_does_not_abandon_an_already_submitted_call(client, cloud):
    task, owner, *_ = execution_setup(client)
    second = same_source_task(task['id'], owner)
    first_provider, second_provider = SyntheticProvider(pending=True), SyntheticProvider(pending=True)
    second_provider.response_id = 'resp_second_task'
    first_pending, second_pending = run(task, first_provider), run(second, second_provider)
    first_provider.pending = False
    first_done = run(first_pending, first_provider)
    still_pending = run(second_pending, second_provider)
    assert still_pending['status'] == 'running' and len(second_provider.gets) == 1
    second_provider.pending = False
    second_done = run(still_pending, second_provider)
    assert second_done['status'] == 'succeeded'
    assert second_done['result_explanation_id'] == first_done['result_explanation_id']
    with database_connection() as db:
        assert {row['status'] for row in db.execute('SELECT status FROM budget_reservations')} == {'settled'}


def test_unknown_on_final_automatic_attempt_still_waits_without_requeue(client, cloud):
    from app.adapters.openai_explanation import INSTRUCTIONS
    from app.domain.model_usage.contracts import CallRequest, ModelPolicy
    from app.domain.model_usage.gateway import input_digest
    task, owner, _, _, _, service = execution_setup(client)
    repository = TaskExecutionStore()
    for _ in range(2):
        current = TaskStore(owner).get(task['id'])
        lease = repository.claim(task['id'], current['revision'])
        expired(lease)
        repository.recover_expired()
    current = TaskStore(owner).get(task['id'])
    lease = repository.claim(task['id'], current['revision'])
    current, _, payload = repository.load_explanation(lease)
    frozen = current['input_snapshot']['explanation_policy']
    call = service.reserve_call(CallRequest(task_id=task['id'], expected_task_revision=current['revision'],
        call_key='explanation:v1', input_digest=input_digest(instructions=INSTRUCTIONS, payload=payload),
        policy=ModelPolicy.model_validate(frozen['policy']), input_token_allowance=frozen['input_token_allowance']),
        execution_lease=lease)
    assert service.begin_submission(call['id'], execution_lease=lease, expected_task_revision=current['revision'])
    expired(lease)
    repository.recover_expired()
    waiting = TaskStore(owner).get(task['id'])
    assert waiting['status'] == 'waiting_confirmation' and waiting['reason_code'] == 'submission_unknown'
    assert waiting['current_attempt'] == 3
    with database_connection() as db:
        assert {row['status'] for row in db.execute('SELECT status FROM budget_reservations')} == {'held'}
        assert db.execute('SELECT count(*) AS n FROM task_outbox').fetchone()['n'] == 3


def test_source_changed_between_slices_still_retrieves_and_accounts_existing_response(client, cloud):
    task, _, base, result, *_ = execution_setup(client)
    provider = SyntheticProvider(pending=True)
    pending = run(task, provider)
    changed = client.put(base + '/analysis-setup', json={
        **result['selection'], 'expected_revision': 1, 'unit': 'changed-between-slices'})
    assert changed.status_code == 200
    still_pending = run(pending, provider)
    assert still_pending['status'] == 'running' and len(provider.gets) == 1
    provider.pending = False
    failed = run(still_pending, provider)
    assert failed['status'] == 'failed' and failed['error_code'] == 'task_source_conflict'
    assert len(provider.posts) == 1 and provider.gets == [provider.response_id, provider.response_id]
    with database_connection() as db:
        assert not db.execute('SELECT id FROM explanations').fetchall()
        call = db.execute('SELECT * FROM model_calls').fetchone()
        assert call['status'] == 'completed' and call['usage_status'] == 'estimated'
        assert {row['status'] for row in db.execute('SELECT status FROM budget_reservations')} == {'settled'}


def test_source_changed_before_first_submission_never_initializes_provider(client, cloud):
    task, _, base, result, *_ = execution_setup(client)
    assert client.put(base + '/analysis-setup', json={
        **result['selection'], 'expected_revision': 1, 'unit': 'changed-before-submission'}).status_code == 200
    provider = SyntheticProvider()
    failed = run(task, provider)
    assert failed['status'] == 'failed' and failed['error_code'] == 'task_source_conflict'
    assert not provider.posts and not provider.gets and provider.closed == 0
    with database_connection() as db:
        assert not db.execute('SELECT id FROM model_calls').fetchall()


def test_disabled_owner_cannot_retrieve_an_existing_response(client, cloud):
    task, owner, *_ = execution_setup(client)
    provider = SyntheticProvider(pending=True)
    pending = run(task, provider)
    with database_connection(write=True) as db:
        db.execute('UPDATE users SET active=FALSE WHERE id=%s', (owner,))
    assert run(pending, provider) is None
    assert len(provider.posts) == 1 and not provider.gets and provider.closed == 1
    with database_connection() as db:
        current = db.execute('SELECT * FROM tasks WHERE id=%s', (task['id'],)).fetchone()
        assert current['status'] == 'failed' and current['error_code'] == 'task_owner_unavailable'
        assert {row['status'] for row in db.execute('SELECT status FROM budget_reservations')} == {'held'}
