"""One fenced plot slice: one remote write, or receipt recovery and publication."""
from datetime import datetime, timezone
import hashlib
import logging
from threading import Event, Thread

from app.adapters.models.openai_responses import ModelProviderError, canonical_payload
from app.adapters.openai_plot import INSTRUCTIONS, PROMPT_VERSION
from app.adapters.task_execution_store import LeaseLost, TaskExecutionStore
from app.core.exceptions import PlotError, StorageError
from app.domain.model_usage.contracts import CallRequest, ModelPolicy
from app.domain.model_usage.gateway import ModelGateway, ModelGatewayError, input_digest
from app.domain.model_usage.service import ModelUsageService
from app.domain.plot_response import download_plot, parse_plot_response


logger = logging.getLogger(__name__)
BUDGET_ERRORS = frozenset({'model_budget_missing', 'model_budget_exceeded', 'plot_not_configured',
                           'openai_not_configured', 'boxplot_not_configured'})


def create_provider():
    from app.adapters.models.openai_plot import OpenAIPlotProvider
    from app.domain.plot_policy import plot_api_key
    return OpenAIPlotProvider(api_key=plot_api_key())


def unknown_submission(call):
    if not call or call.get('provider_response_id'):
        return False
    return (call['status'] == 'submission_unknown' or call['status'] == 'submitting'
            and (call.get('provider_state') or {}).get('phase') not in ('container_ready', 'file_ready'))


def release_unused_reservation(repository, lease, config, error_code):
    call = repository.boxplot_call(lease)
    if (call and call['status'] == 'reserved' and not call.get('provider_state')
            and not call.get('provider_response_id')):
        # The service transaction rechecks reserved status. If another attempt
        # has crossed any POST fence, release is rejected instead of erasing cost.
        ModelUsageService(call['user_id'], config).release_unsubmitted(call['id'],
            event_key='plot:unsubmitted_failure:v1', reason_code=error_code)


def run_boxplot_task(task_id, task_revision, *, config=None, directory=None, provider_factory=None):
    repository = TaskExecutionStore(config=config, directory=directory)
    lease = repository.claim(task_id, task_revision, task_type='boxplot')
    if lease is None:
        return None
    stop, providers = Event(), []

    def keep_alive():
        while not stop.wait(10):
            try:
                if not repository.heartbeat(lease):
                    return
            except Exception:
                logger.warning('plot heartbeat unavailable task_id=%s attempt=%s', task_id, lease.attempt_no)

    thread = Thread(target=keep_alive, name='boxplot-task-heartbeat', daemon=True)
    thread.start()
    try:
        return _execute(repository, lease, config, provider_factory or create_provider, providers)
    except LeaseLost:
        return None
    except (StorageError, PlotError) as exc:
        try:
            if exc.code in BUDGET_ERRORS:
                return repository.wait_explanation(lease, 'budget_exceeded', exc.code)
            if isinstance(exc, PlotError) or exc.status < 500 or exc.code == 'plot_input_limit':
                # Finish only after a safe release has persisted. A failed or
                # unknown release commit leaves the lease recoverable.
                release_unused_reservation(repository, lease, config, exc.code)
                return repository.fail(lease, exc.code)
        except LeaseLost:
            return None
        except Exception:
            pass
        logger.warning('plot persistence unavailable task_id=%s attempt=%s', task_id, lease.attempt_no)
        return None
    except Exception as exc:
        # Log the type, never provider bodies or exception strings containing secrets.
        logger.warning('plot execution interrupted task_id=%s attempt=%s error_type=%s',
                       task_id, lease.attempt_no, type(exc).__name__)
        return None
    finally:
        stop.set()
        thread.join(timeout=1)
        for provider in providers:
            try:
                provider.close()
            except Exception:
                logger.warning('plot client cleanup unavailable task_id=%s', task_id)


def _execute(repository, lease, config, provider_factory, providers):
    from app.domain.plot_policy import validate_execution_policy
    task = repository.load_boxplot_task(lease)
    call = repository.boxplot_call(lease)
    if call and call['status'] == 'released':
        # A previous source failure may have released its reservation before
        # the worker lost its lease or the task failure transaction committed.
        return repository.fail(lease, 'task_source_conflict')
    if (call and not call.get('provider_response_id') and call['status'] == 'failed'
            and call.get('error_code') == 'plot_container_expired'):
        return repository.fail(lease, 'plot_container_expired')
    if unknown_submission(call):
        return repository.wait_explanation(lease, 'submission_unknown', 'model_submission_unknown')
    # A registered, verified local candidate survives container expiry and an
    # unknown SQL commit outcome; recovering it never needs another cloud read.
    if task.get('figure_candidate'):
        task, snapshot, payload, expected = repository.load_boxplot(lease)
        completed = repository.complete_boxplot(lease, snapshot, payload, expected)
        if completed is not None:
            return completed
    if not call or not call.get('provider_response_id'):
        task, snapshot, payload, expected = repository.load_boxplot(lease)
        cached = repository.cached_boxplot(lease)
        if cached is not None and call is None:
            return repository.complete_boxplot(lease, snapshot, payload, expected, cached=cached)
        frozen = validate_execution_policy(task['input_snapshot'].get('boxplot_policy'), payload=payload)
    service = ModelUsageService(task['user_id'], config)
    provider = provider_factory()
    providers.append(provider)
    gateway = ModelGateway(service, provider)
    try:
        if call and call.get('provider_response_id'):
            output = gateway.refresh(call['id'])
        else:
            request = CallRequest(task_id=task['id'], expected_task_revision=task['revision'],
                call_key='boxplot:v1', input_digest=input_digest(instructions=INSTRUCTIONS, payload=payload),
                policy=ModelPolicy.model_validate(frozen['policy']),
                input_token_allowance=frozen['input_token_allowance'],
                tool_reserve_micro_usd=frozen['tool_reserve_micro_usd'],
                tool_reserve_version=frozen['tool_reserve_version'])
            output = gateway.submit_plot(request, instructions=INSTRUCTIONS, payload=payload, execution_lease=lease)
    except ModelGatewayError as exc:
        call = repository.boxplot_call(lease)
        if exc.code in ('model_response_not_found', 'plot_container_expired'):
            return repository.fail(lease, exc.code)
        if unknown_submission(call):
            return repository.wait_explanation(lease, 'submission_unknown', 'model_submission_unknown')
        if call and call.get('provider_response_id'):
            return repository.defer(lease, seconds=30)
        raise
    call, response = output['call'], output.get('response')
    if (not call.get('provider_response_id') and call['status'] == 'failed'
            and call.get('error_code') == 'plot_container_expired'):
        return repository.fail(lease, 'plot_container_expired')
    if unknown_submission(call):
        return repository.wait_explanation(lease, 'submission_unknown', 'model_submission_unknown')
    if response is None or isinstance(response, dict) and response.get('status') in ('queued', 'in_progress'):
        return repository.defer(lease)
    # Terminal usage has already reached the ledger. Source changes must block
    # publication, while preserving the paid call's response and usage evidence.
    task, snapshot, payload, expected = repository.load_boxplot(lease)
    parsed = parse_plot_response(response, (call.get('provider_state') or {}).get('container_id'))
    if parsed is None:
        return repository.defer(lease)
    policy = ModelPolicy.model_validate({key: call['policy_snapshot'][key]
        for key in ModelPolicy.model_fields if key in call['policy_snapshot']})
    try:
        downloaded = download_plot(parsed, provider, policy, expected)
    except ModelProviderError as exc:
        if exc.code in ('plot_container_expired', 'plot_output_limit'):
            return repository.fail(lease, exc.code)
        if exc.code in ('plot_receipt_invalid', 'model_input_invalid'):
            return repository.fail(lease, 'plot_invalid_result')
        return repository.defer(lease, seconds=30)
    figure = {**expected, 'file_id': snapshot['result']['file_id'],
        'setup_revision': snapshot['result']['setup_revision'], 'figure_number': 1, 'language': 'zh-CN',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'engine': {'id': PROMPT_VERSION, 'provider': 'openai_code_interpreter', 'model': parsed['provenance']['model']},
        'method': {'whisker_iqr_multiplier': 1.5, 'quantile_method': 'linear_inclusive', 'outliers_removed': False},
        'verification': {'status': 'matched', 'note': '结构化数值、标签及图注已核对；图片视觉内容仍需人工确认。'},
        'provenance': {**downloaded['provenance'], 'model_call_id': call['id'],
            'model_input_digest': call['input_digest'],
            'input_sha256': hashlib.sha256(canonical_payload(payload).encode('utf-8')).hexdigest()}}
    candidate = repository.register_figure_candidate(lease, snapshot, figure, downloaded['png'], expected, payload)
    repository.write_figure_candidate(lease, candidate, downloaded['png'])
    return repository.complete_boxplot(lease, snapshot, payload, expected)
