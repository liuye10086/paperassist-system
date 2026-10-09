"""One leased explanation execution slice; cloud waiting never occupies a worker."""
from datetime import datetime, timezone
import hashlib
import json
import logging
from threading import Event, Thread

from app.adapters.task_execution_store import LeaseLost, TaskExecutionStore
from app.core.exceptions import PlotError, StorageError
from app.domain.explanation_content import LIMITATIONS, VERSION, render_explanation
from app.domain.model_usage.contracts import CallRequest, ModelPolicy
from app.domain.model_usage.gateway import ModelGateway, ModelGatewayError, input_digest
from app.domain.model_usage.service import ModelUsageService
from app.domain.tasks.errors import classify_read_error


logger = logging.getLogger(__name__)
SOURCE_ERRORS = frozenset({'task_source_conflict', 'task_owner_unavailable', 'file_missing',
    'file_changed', 'figure_missing', 'figure_changed', 'explanation_input_limit'})
OUTPUT_ERRORS = frozenset({'explanation_invalid', 'explanation_invalid_json', 'explanation_refused',
    'explanation_output_limit', 'explanation_incomplete', 'model_response_not_found'})
BUDGET_ERRORS = frozenset({'model_budget_missing', 'model_budget_exceeded',
    'explanation_not_configured', 'openai_not_configured'})


def create_provider():
    from app.adapters.models.openai_responses import OpenAIResponsesProvider
    from app.domain.explanation_policy import explanation_api_key
    return OpenAIResponsesProvider(api_key=explanation_api_key())


def run_explanation_task(task_id, task_revision, *, config=None, directory=None, provider_factory=None):
    repository = TaskExecutionStore(config=config, directory=directory)
    lease = repository.claim(task_id, task_revision, task_type='explanation')
    if lease is None:
        return None
    stop = Event()
    providers = []

    def keep_alive():
        while not stop.wait(10):
            try:
                if not repository.heartbeat(lease):
                    return
            except Exception:
                logger.warning('explanation heartbeat unavailable task_id=%s attempt=%s', task_id, lease.attempt_no)

    heartbeat = Thread(target=keep_alive, name='explanation-task-heartbeat', daemon=True)
    heartbeat.start()
    try:
        return _execute(repository, lease, config, provider_factory or create_provider,
                        lambda value: providers.append(value))
    except LeaseLost:
        return None
    except (StorageError, PlotError) as exc:
        try:
            if exc.code in BUDGET_ERRORS:
                return repository.wait_explanation(lease, 'budget_exceeded', exc.code)
            if exc.code in SOURCE_ERRORS | OUTPUT_ERRORS:
                return repository.fail(lease, exc.code)
        except LeaseLost:
            return None
        except Exception:
            pass
        # A persistence error must leave this attempt recoverable by lease expiry.
        logger.warning('explanation persistence unavailable task_id=%s attempt=%s', task_id, lease.attempt_no)
        return None
    except Exception:
        logger.warning('explanation execution interrupted task_id=%s attempt=%s', task_id, lease.attempt_no)
        return None
    finally:
        stop.set()
        heartbeat.join(timeout=1)
        for provider in providers:
            try:
                provider.close()
            except Exception:
                logger.warning('model client cleanup unavailable task_id=%s', task_id)


def _execute(repository, lease, config, provider_factory, remember_provider):
    from app.domain.external_material import explanation_instructions
    from app.domain.explanation_policy import validate_execution_policy
    from app.domain.explanation_response import parse_explanation_response
    task = repository.load_explanation_task(lease)
    instructions = explanation_instructions(task['input_snapshot'].get('external_processing'))
    call = repository.explanation_call(lease)
    if call and not call['provider_response_id'] and call['status'] in ('submitting', 'submission_unknown'):
        return repository.wait_explanation(lease, 'submission_unknown', 'model_submission_unknown')
    if not call or not call['provider_response_id']:
        task, snapshot, payload = repository.load_explanation(lease)
        cached = repository.cached_explanation(lease)
        if cached is not None and call is None:
            return repository.complete_explanation(lease, snapshot, cached)
        from app.domain.external_material import explanation_material
        _, outbound = explanation_material(snapshot['result'], snapshot['figure'], snapshot.get('external_processing'))
        frozen = validate_execution_policy(task['input_snapshot'].get('explanation_policy'), payload=outbound)
    service = ModelUsageService(task['user_id'], config)
    provider = provider_factory()
    remember_provider(provider)
    gateway = ModelGateway(service, provider)
    try:
        if call and call['provider_response_id']:
            output = gateway.refresh(call['id'])
        else:
            request = CallRequest(task_id=task['id'], expected_task_revision=task['revision'],
                call_key='explanation:v1', input_digest=input_digest(instructions=instructions, payload=outbound),
                policy=ModelPolicy.model_validate(frozen['policy']),
                input_token_allowance=frozen['input_token_allowance'])
            output = gateway.submit(request, instructions=instructions, payload=outbound, execution_lease=lease)
    except ModelGatewayError as exc:
        if exc.code == 'model_receipt_persistence_failed':
            # No retry/defer transaction may conceal an unknown receipt commit.
            # Keep the active lease so expiry recovery resumes this same call.
            raise
        call = repository.explanation_call(lease)
        if call and call['provider_response_id']:
            return repository.retry_failure(lease, classify_read_error(exc.code, exc.status_code))
        if call and call['status'] in ('submitting', 'submission_unknown'):
            return repository.wait_explanation(lease, 'submission_unknown', 'model_submission_unknown')
        return repository.retry_failure(lease, classify_read_error(exc.code, exc.status_code))
    call = output['call']
    if not call.get('provider_response_id'):
        return repository.wait_explanation(lease, 'submission_unknown', 'model_submission_unknown')
    response = output.get('response')
    if response is None:
        return repository.fail(lease, 'model_response_invalid')
    if isinstance(response, dict) and response.get('status') in ('queued', 'in_progress'):
        return repository.defer(lease)
    # A saved response may still incur cost after a setup change. Fetch and
    # record its terminal usage first; only artifact publication needs current
    # source metadata and intact local assets.
    task, snapshot, payload = repository.load_explanation(lease)
    parsed = parse_explanation_response(response)
    if parsed is None:
        return repository.fail(lease, 'model_response_invalid')
    sections = render_explanation(parsed['draft'], payload)
    explanation = {
        'analysis_run_id': snapshot['result']['id'], 'figure_id': snapshot['figure']['id'],
        'figure_sha256': snapshot['figure']['sha256'], 'source_sha256': snapshot['result']['source_sha256'],
        'setup_revision': snapshot['result']['setup_revision'], 'language': 'zh-CN',
        'created_at': datetime.now(timezone.utc).isoformat(), 'sections': sections, 'limitations': LIMITATIONS,
        'engine': {'id': VERSION, 'provider': 'openai', 'model': parsed['provenance']['model']},
        'verification': {'status': 'references_checked',
            'note': '数值与事实引用已由程序填入并核对；语义和研究适用性仍需人工审阅。'},
        'provenance': {**parsed['provenance'], 'prompt_version': VERSION,
            'input_sha256': hashlib.sha256(json.dumps(payload, ensure_ascii=False, allow_nan=False,
                sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest(),
            'model_call_id': call['id'], 'model_input_digest': call['input_digest']}}
    if snapshot.get('external_processing') is not None:
        explanation['provenance']['external_processing'] = snapshot['external_processing']
    return repository.complete_explanation(lease, snapshot, explanation)
