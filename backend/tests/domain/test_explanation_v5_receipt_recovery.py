"""Pure recovery-gate and existing transaction flow checks; no live SQL/model."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.core.exceptions import StorageError
from app.domain.figure_workbench import tasks as t
from tests.domain.test_explanation_v5_real_response import FIXTURE


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def failed_task():
    return {'id': 'retained-v5-task', 'task_type': 'figure_explanation', 'status': 'failed',
            'revision': 4, 'error_code': 'explanation_invalid', 'reason_code': None,
            'input_snapshot': {'figure': deepcopy(FIXTURE['bundle']['figure']),
                               'explanation_policy': {'policy': {'prompt_version': 'figure_explanation_v5'}}}}


def completed_call():
    return {'status': 'completed', 'provider_status': 'completed', 'provider_response_id': FIXTURE['source_response_id']}


def test_only_known_completed_v5_validation_failure_offers_original_retry(monkeypatch):
    task = failed_task()
    before = deepcopy(task)
    call = completed_call()
    monkeypatch.setattr(t, '_call', lambda db, value: call)
    assert t.allowed_recovery_actions(None, task) == ['retry']
    assert task == before


@pytest.mark.parametrize('field,value', [
    ('status', 'queued'), ('status', 'running'), ('status', 'succeeded'),
    ('status', 'waiting_confirmation'), ('task_type', 'figure_projection'),
    ('task_type', 'figure_workbench'), ('task_type', 'boxplot'),
    ('error_code', 'explanation_invalid_json'), ('error_code', 'explanation_refused'),
    ('error_code', 'explanation_output_limit'), ('error_code', 'explanation_incomplete'),
])
def test_recovery_exception_does_not_cover_other_tasks_or_output_failures(monkeypatch, field, value):
    task = failed_task()
    task[field] = value
    monkeypatch.setattr(t, '_call', lambda db, task: completed_call())
    assert t.allowed_recovery_actions(None, task) == []


@pytest.mark.parametrize('call', [
    None, {'status': 'completed', 'provider_status': 'completed'},
    {'status': 'completed', 'provider_status': 'completed', 'provider_response_id': ''},
    {'status': 'completed', 'provider_status': 'in_progress', 'provider_response_id': 'known'},
    {'status': 'completed', 'provider_response_id': 'known'},
    {'status': 'failed', 'provider_status': 'completed', 'provider_response_id': 'known'},
    {'status': 'submission_unknown', 'provider_status': 'completed'},
    {'status': 'submitting', 'provider_status': 'completed'},
    {'status': 'reserved', 'provider_status': 'completed', 'provider_response_id': 'known'},
])
def test_recovery_requires_both_completed_statuses_and_a_receipt(monkeypatch, call):
    monkeypatch.setattr(t, '_call', lambda db, task: call)
    assert t.allowed_recovery_actions(None, failed_task()) == []


@pytest.mark.parametrize('version', ['figure_explanation_v1', 'figure_explanation_v2', 'figure_explanation_v3', 'figure_explanation_v4', 'figure_explanation_v6', None])
def test_recovery_exception_uses_frozen_v5_not_a_latest_or_supplied_version(monkeypatch, version):
    task = failed_task()
    task['input_snapshot']['explanation_policy']['policy']['prompt_version'] = version
    if version == 'figure_explanation_v1':
        task['input_snapshot']['figure']['engine']['id'] = 'openai_figure_workbench_v1'
    elif version == 'figure_explanation_v2':
        task['input_snapshot']['figure']['engine']['id'] = 'openai_figure_workbench_v2'
        task['input_snapshot']['figure']['presentation']['schema_version'] = 1
    monkeypatch.setattr(t, '_call', lambda db, task: completed_call())
    assert t.allowed_recovery_actions(None, task) == []


def test_missing_or_incompatible_frozen_figure_cannot_enable_retry(monkeypatch):
    task = failed_task()
    monkeypatch.setattr(t, '_call', lambda db, task: completed_call())
    task['input_snapshot'].pop('figure')
    assert t.allowed_recovery_actions(None, task) == []
    task = failed_task()
    task['input_snapshot']['figure']['engine']['id'] = 'openai_figure_workbench_v2'
    assert t.allowed_recovery_actions(None, task) == []


def test_existing_retry_keeps_revision_source_checks_events_and_queue(monkeypatch):
    from app.adapters import task_execution_store
    from app.domain.tasks import waits
    calls = []
    sentinel = object()
    store = SimpleNamespace(config='offline',
        update_task=lambda db, task, revision: calls.append(('update', revision, task['status'])),
        append_event=lambda db, task, event: calls.append(('event', event)),
        enqueue=lambda db, task: calls.append(('enqueue', task['id'])),
        public_task=lambda task: deepcopy(task))
    monkeypatch.setattr(t, '_call', lambda db, task: completed_call())
    monkeypatch.setattr(task_execution_store, 'TaskExecutionStore', lambda config: sentinel)
    monkeypatch.setattr(t, 'require_task_sources', lambda repository, db, task: calls.append(('source_guard', repository is sentinel)))
    monkeypatch.setattr(waits, 'resolve_open_wait', lambda db, task: calls.append(('resolve_existing_wait', task['id'])))
    task = failed_task()
    with pytest.raises(StorageError):
        t.retry_in_transaction(store, None, task, 3)
    assert calls == [] and task['status'] == 'failed'
    result = t.retry_in_transaction(store, None, task, 4)
    assert result['status'] == 'queued' and result['revision'] == 5
    assert result['reason_code'] == 'retry_requested' and result['error_code'] is None
    assert calls == [('source_guard', True), ('update', 4, 'queued'), ('event', 'requeued'), ('enqueue', 'retained-v5-task'), ('resolve_existing_wait', 'retained-v5-task')]


def test_source_conflict_stops_retry_before_mutation_or_events(monkeypatch):
    task = failed_task()
    original = deepcopy(task)
    monkeypatch.setattr(t, '_call', lambda db, task: completed_call())
    def reject_source(*args):
        raise StorageError('task_source_conflict', 'offline source mismatch', 409)
    monkeypatch.setattr(t, 'require_task_sources', reject_source)
    from app.adapters import task_execution_store
    monkeypatch.setattr(task_execution_store, 'TaskExecutionStore', lambda config: None)
    with pytest.raises(StorageError) as failure:
        t.retry_in_transaction(SimpleNamespace(config='offline'), None, task, 4)
    assert failure.value.code == 'task_source_conflict'
    assert task == original


@pytest.mark.parametrize('expired', [False, True])
def test_existing_worker_retrieves_same_receipt_without_reserving_or_posting(monkeypatch, expired):
    from contextlib import nullcontext
    from datetime import datetime, timedelta, timezone
    import json
    from app.domain.figure_workbench import execution as worker
    from app.domain.figure_workbench import explanations as e
    from tests.adapters.test_model_gateway import Service, Provider
    from tests.domain.test_explanation_policy import execution_policy

    task = failed_task()
    task.update(status='queued', revision=5, user_id='offline-user', project_id='offline-project')
    policy = execution_policy()
    policy['policy'].update(prompt_version='figure_explanation_v5', output_format='analysis_explanation_v2')
    policy['input_token_allowance'] = 1000000
    task['input_snapshot']['explanation_policy'] = policy
    call = {**completed_call(), 'id': 'retained-call', 'input_digest': FIXTURE['model_input_digest'],
            'policy_snapshot': policy['policy'],
            'created_at': datetime.now(timezone.utc) - timedelta(minutes=21 if expired else 1)}
    service = Service(row=call)
    def unexpected_submit(*args, **kwargs):
        pytest.fail('Known receipt recovery must not reserve or begin a new submission')
    service.reserve_call = unexpected_submit
    service.begin_submission = unexpected_submit
    body = {'id': FIXTURE['source_response_id'], 'status': 'completed', 'model': policy['policy']['model'],
            'usage': None, 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(FIXTURE['draft'])}]}]}
    provider = Provider(service, result={'response_id': body['id'], 'request_id': 'offline-get',
        'model': body['model'], 'status': 'completed', 'usage': None, 'response': body})
    repository = SimpleNamespace(config='offline', connection=lambda: nullcontext(None),
        require_lease=lambda db, lease: task, require_owner=lambda db, task: None,
        retry_failure=lambda lease, code: {'blocked_by_existing_observation': code})
    monkeypatch.setattr(worker, '_call', lambda repository, lease: deepcopy(call))
    monkeypatch.setattr(worker, 'ModelUsageService', lambda user_id, config: service)
    context_calls = []
    def context(repository, lease):
        context_calls.append('source_revalidated_after_get')
        return task, SimpleNamespace(assets=None), None, None, None, FIXTURE['payload'], None
    monkeypatch.setattr(worker, '_context', context)
    monkeypatch.setattr(worker, 'read_bundle', lambda assets, project, figure: FIXTURE['bundle'])
    def publish(repository, lease, bundle, value):
        assert e.validate_saved(bundle, value) == value
        assert value['draft'] == FIXTURE['draft']
        assert value['provenance']['model_call_id'] == call['id']
        assert value['provenance']['response_id'] == call['provider_response_id']
        return value
    monkeypatch.setattr(worker, '_publish_explanation', publish)
    result = worker._execute(repository, object(), lambda: provider, [], True)
    assert provider.posts == [] and 'reserve' not in service.events and 'begin' not in service.events
    if expired:
        assert provider.gets == [] and context_calls == []
        assert result == {'blocked_by_existing_observation': 'model_observation_expired'}
    else:
        assert provider.gets == [FIXTURE['source_response_id']]
        assert context_calls == ['source_revalidated_after_get']
        assert result['draft'] == FIXTURE['draft']
