"""Prepare narrative output through the budgeted, lease-fenced model worker."""
import json
from threading import Event, Thread

from psycopg.types.json import Jsonb

from app.adapters.research_results_store import now
from app.adapters.task_execution_store import LeaseLost, TaskExecutionStore
from app.adapters.task_store import TaskStore, source_conflict
from app.core.exceptions import StorageError
from app.domain.dataset_preparation.service import append_checkpoint
from app.domain.model_usage.contracts import CallRequest, ModelPolicy
from app.domain.model_usage.gateway import ModelGateway, ModelGatewayError
from app.domain.model_usage.service import ModelUsageService
from app.domain.report_collections.service import scoped_store
from app.domain.tasks.errors import classify_read_error
from app.domain.tasks.waits import allowed_recovery_actions, get_open_wait, resolve_open_wait

from .contracts import CALL_KEY, TASK_TYPE
from .service import ReaderReportService, artifact_sha, input_version


def _checkpoint(db, task):
    row = db.execute('SELECT * FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',
                     (task['id'],)).fetchone()
    if not row or row['state_json'].get('input_digest') != task['input_digest']:
        raise source_conflict()
    return row


def _call(db, task):
    return db.execute('''SELECT * FROM model_calls WHERE task_id=%s AND project_id=%s AND user_id=%s AND call_key=%s''',
                     (task['id'], task['project_id'], task['user_id'], CALL_KEY)).fetchone()


def _unknown(call):
    return call and not call['provider_response_id'] and call['status'] in ('submitting', 'submission_unknown')


def _wait(repository, lease, reason, code):
    with repository.connection(write=True) as db:
        task = repository.require_lease(db, lease)
        repository._wait_explanation(db, task, reason, code)
        return TaskStore.public_task(task)


def _parse_response(response):
    if not isinstance(response, dict) or response.get('status') != 'completed':
        raise ValueError('Incomplete reader report output')
    messages = [item for item in response['output'] if item['type'] == 'message']
    if len(messages) != 1 or len(messages[0]['content']) != 1:
        raise ValueError('Expected one report JSON message')
    item = messages[0]['content'][0]
    if item['type'] != 'output_text' or not isinstance(item['text'], str) or len(item['text'].encode()) > 512 * 1024:
        raise ValueError('Invalid reader report output')

    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate reader report JSON key')
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError('Non-finite reader report JSON value')

    raw = json.loads(item['text'], object_pairs_hook=unique_keys, parse_constant=invalid_constant)
    if not isinstance(raw, dict):
        raise ValueError('Expected a reader report JSON object')
    return raw


def run_reader_report_task(task_id, task_revision, *, config=None, directory=None, provider=None):
    repository = TaskExecutionStore(config=config, directory=directory)
    if provider is not None and (repository.config.environment != 'test' or
                                 getattr(provider, 'source_kind', None) != 'synthetic_fixture'):
        raise StorageError('task_input_invalid', '仅隔离测试允许注入合成解读供应商。', 422)
    lease = repository.claim(task_id, task_revision, task_type=TASK_TYPE)
    if lease is None:
        return None
    stop = Event()

    def heartbeat():
        while not stop.wait(10):
            try:
                if not repository.heartbeat(lease):
                    return
            except StorageError:
                return

    thread = Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        return _execute(repository, lease, provider)
    except LeaseLost:
        return None
    except StorageError as exc:
        if exc.code in ('model_budget_missing', 'model_budget_exceeded'):
            return _wait(repository, lease, 'budget_exceeded', exc.code)
        if exc.status >= 500:
            return None
        return repository.fail(lease, exc.code)
    except (ValueError, KeyError, TypeError):
        return repository.fail(lease, 'model_response_invalid')
    finally:
        stop.set()
        thread.join(timeout=1)


def _execute(repository, lease, provider):
    from .content import validate_output
    from .policy import real_calls_enabled

    with repository.connection() as db:
        task = repository.require_lease(db, lease)
        repository.require_owner(db, task)
        _checkpoint(db, task)
        service = ReaderReportService(scoped_store(task['user_id'], repository.config, repository.assets.directory))
        identifier = input_version(task)['narrative_id']
        row, _ = service.row(db, task['project_id'], identifier)
        frozen = row['input_snapshot']['bundle']
        call = _call(db, task)
    if _unknown(call):
        return _wait(repository, lease, 'submission_unknown', 'model_submission_unknown')
    if call and call['status'] == 'released':
        return repository.fail(lease, 'task_source_conflict')

    owns_provider = provider is None
    if owns_provider:
        # Existing remote responses are retrieved through the same ledger.
        if not real_calls_enabled():
            return _wait(repository, lease, 'confirmation_required', 'model_policy_not_configured')
        from app.adapters.models.openai_responses import OpenAIResponsesProvider
        from app.domain.explanation_policy import explanation_api_key
        try:
            provider = OpenAIResponsesProvider(api_key=explanation_api_key())
        except StorageError:
            return _wait(repository, lease, 'confirmation_required', 'model_policy_not_configured')
    gateway = ModelGateway(ModelUsageService(task['user_id'], repository.config), provider)
    try:
        try:
            if call and call['provider_response_id']:
                output = gateway.refresh(call['id'], accept_terminal_failure=True)
            else:
                with repository.connection() as db:
                    repository.require_lease(db, lease)
                    material = service.material_for_task(db, row, task)
                request = CallRequest(task_id=task['id'], expected_task_revision=task['revision'], call_key=CALL_KEY,
                                      input_digest=frozen['input_digest'], policy=ModelPolicy.model_validate(frozen['policy']),
                                      input_token_allowance=frozen['input_token_allowance'])
                output = gateway.submit(request, instructions=frozen['instructions'], payload=material, execution_lease=lease)
        except ModelGatewayError as exc:
            with repository.connection() as db:
                call = _call(db, task)
            if _unknown(call):
                return _wait(repository, lease, 'submission_unknown', 'model_submission_unknown')
            if exc.code == 'model_receipt_persistence_failed':
                return None
            if exc.code == 'model_configuration_disabled':
                return _wait(repository, lease, 'confirmation_required', exc.code)
            return repository.retry_failure(lease, classify_read_error(exc.code, exc.status_code))
    finally:
        if owns_provider:
            provider.close()

    call, response = output['call'], output.get('response')
    if not call['provider_response_id']:
        return _wait(repository, lease, 'submission_unknown', 'model_submission_unknown')
    if isinstance(response, dict) and response.get('status') in ('queued', 'in_progress'):
        return repository.defer(lease)

    raw = {'unparseable': True}
    try:
        raw = _parse_response(response)
        result = validate_output(raw, frozen['material'])
    except (ValueError, KeyError, TypeError):
        result = {'validation_status': 'invalid'}

    with repository.connection(write=True) as db:
        task = repository.require_lease(db, lease)
        repository.require_owner(db, task)
        fresh, _ = service.row(db, task['project_id'], identifier)
        if fresh['result_json'] is not None:
            raise source_conflict()
        if call['input_digest'] != frozen['input_digest']:
            raise source_conflict()
        if db.execute("SELECT 1 FROM usage_events WHERE call_id=%s AND reason_code='model_mismatch'",
                      (call['id'],)).fetchone():
            result = {'validation_status': 'invalid'}
        db.execute('''UPDATE reader_report_narratives
            SET raw_output_json=%s,result_json=%s,artifact_sha256=%s,model_call_id=%s WHERE id=%s''',
            (Jsonb(raw), Jsonb(result), artifact_sha(row, raw, result, call['id']), call['id'], identifier))
        if result == {'validation_status': 'invalid'}:
            repository._finish(db, task, 'failed', 'model_response_invalid')
        else:
            previous = _checkpoint(db, task)
            append_checkpoint(db, task, 'done', 'done', previous['state_json'], previous)
            repository._finish(db, task, 'succeeded', None)
        return service.store.public_task(task)


def retry_in_transaction(store, db, task, expected_revision, *, assets=None):
    version = input_version(task)
    task = store.require_task(db, task['id'])
    if task['revision'] != expected_revision:
        raise StorageError('task_revision_conflict', '解读任务状态已变化，请重新读取。', 409)
    actions = allowed_recovery_actions(db, task)
    if not actions:
        raise StorageError('task_transition_invalid', '当前解读任务不能安全重试。', 409)
    service = ReaderReportService(assets or scoped_store(task['user_id'], store.config))
    row, _ = service.row(db, task['project_id'], version['narrative_id'])
    call = _call(db, task)
    if row['result_json'] is not None or _unknown(call):
        raise source_conflict()
    if task.get('reason_code') == 'observation_expired':
        from app.domain.tasks.resume import TaskResumeService
        wait = get_open_wait(db, task)
        if wait is None:
            raise StorageError('task_revision_conflict', '解读任务的待办已变化，请重新读取。', 409)
        # The common resume transaction records the decision required by the one-GET grant.
        return TaskResumeService(store.user_id, store.config).resume(
            task['id'], dict(operation='resume', wait_id=wait['id'], expected_task_revision=expected_revision,
                             input_version=version),
            idempotency_key=f"reader-report-observation:{wait['id']}", transaction=db,
        )
    if not call or not call['provider_response_id']:
        service.require_no_replacement(db, row, has_reservation=bool(call and call['status'] == 'reserved'))
    _checkpoint(db, task)
    task.update(status='queued', revision=expected_revision+1, reason_code='retry_requested', error_code=None,
                updated_at=max(now(), task['updated_at']), _retry_reason='manual_retry')
    store.update_task(db, task, expected_revision)
    store.append_event(db, task, 'requeued')
    store.enqueue(db, task)
    resolve_open_wait(db, task)
    return store.public_task(task)
