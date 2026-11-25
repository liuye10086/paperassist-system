"""Reserve, submit once, and save usage before exposing provider output internally."""
from copy import deepcopy
from hashlib import sha256
import json
from typing import TYPE_CHECKING

from app.adapters.models.openai_responses import ModelProviderError, canonical_payload, safe_request_id
from app.core.exceptions import StorageError

if TYPE_CHECKING:
    from app.domain.model_usage.contracts import CallRequest


class ModelGatewayError(Exception):
    def __init__(self, code, *, request_id=None, status_code=None):
        super().__init__('统一模型调用未能完成，请核对已保存的调用状态。')
        self.code = code
        self.request_id = safe_request_id(request_id)
        self.status_code = status_code if type(status_code) is int and 100 <= status_code <= 599 else None


def input_digest(*, instructions: str, payload: dict) -> str:
    """SHA256 of the exact instructions and canonical JSON material sent to the SDK."""
    if not isinstance(instructions, str) or not instructions.strip():
        raise ValueError('Instructions must be nonempty.')
    material = json.loads(canonical_payload(payload))
    content = canonical_payload({'instructions': instructions, 'payload': material})
    return sha256(content.encode('utf-8')).hexdigest()


class ModelGateway:
    def __init__(self, service, provider):
        self.service = service
        self.provider = provider

    def _configuration_gate(self,request):
        from app.adapters.models.openai_responses import OpenAIResponsesProvider
        if not isinstance(self.provider,OpenAIResponsesProvider):return
        from app.domain.admin_configuration.bindings import resolve
        with self.service.store.connection() as db:
            task=self.service.store.require_task(db,request.task_id)
            version=resolve(db,kind='task',object_id=task['id'])
            if version and not version['bundle']['models']['real_calls_enabled']:
                raise ModelGatewayError('model_configuration_disabled')

    def submit(self, request: 'CallRequest', *, instructions: str, payload: dict, execution_lease=None) -> dict:
        self._configuration_gate(request)
        # Freeze the material before any service callback or network operation.
        request = deepcopy(request)
        if request.policy.tools:
            raise ModelGatewayError('model_tools_unsupported')
        try:
            material = json.loads(canonical_payload(payload))
            digest = input_digest(instructions=instructions, payload=material)
        except (TypeError, ValueError, RecursionError):
            raise ModelGatewayError('model_input_invalid') from None
        if digest != request.input_digest:
            raise ModelGatewayError('model_input_digest_mismatch')

        lease_options = {'execution_lease': execution_lease} if execution_lease is not None else {}
        call = self.service.reserve_call(request, **lease_options)
        if call.get('provider_response_id'):
            return self.refresh(call['id'])
        # The service transaction commits before this function receives True.
        begin_options = {**lease_options, 'expected_task_revision': request.expected_task_revision} if lease_options else {}
        from app.domain.model_usage.provenance import admission_context
        operation = 'reader_report' if getattr(request.policy, 'output_format', 'text') == 'reader_report_v1' else 'text'
        begin_options['provenance_context']=admission_context(self.provider,request=request,operation=operation)
        if not self.service.begin_submission(call['id'], **begin_options):
            current = self.service.get_call(call['id'])
            if current.get('provider_response_id'):
                return self.refresh(call['id'])
            return {'call': current, 'response': None}
        try:
            receipt = self.provider.create(policy=request.policy, instructions=instructions, payload=material)
        except Exception as exc:
            request_id = safe_request_id(getattr(exc, 'request_id', None))
            self._mark_unknown(call['id'], 'model_provider_request_failed', request_id)
            raise ModelGatewayError('model_provider_request_failed', request_id=request_id,
                                    status_code=getattr(exc, 'status_code', None)) from None
        return self._record(call['id'], receipt, submitted=True)

    def submit_frozen_writing(self, request, *, wire_json, execution_lease, on_delta=None):
        self._configuration_gate(request)
        from app.domain.manuscript_writing.authorization import LiveWritingService
        from app.domain.manuscript_writing.frozen import bundle_contract
        from app.domain.manuscript_writing.live_execution import require_live_snapshot
        from app.domain.model_usage.provenance import admission_context
        from app.domain.report_collections.service import scoped_store

        with self.service.store.connection() as db:
            task = self.service.store.require_task(db, request.task_id)
            snapshot = require_live_snapshot(task)
            assets = scoped_store(task['user_id'], self.service.store.config)
            bundle = LiveWritingService(assets).bundle(db, task['project_id'], snapshot['execution']['bundle_id'])
            saved_wire = bundle['wire_json']
            if wire_json != saved_wire:
                raise ModelGatewayError('model_input_digest_mismatch')
        frozen = bundle_contract(bundle)
        context = admission_context(self.provider, request=request, operation='frozen_writing')
        create_events = None
        if frozen.get('response_stream') is True:
            create_events = getattr(self.provider, 'create_frozen_events', None)
            if not callable(create_events):
                if context.kind != 'synthetic_fixture' or self.service.store.config.environment != 'test':
                    raise ModelGatewayError('model_provider_request_failed')
                create_events = None
        call = self.service.reserve_call(request, execution_lease=execution_lease)
        if call.get('provider_response_id'):
            return self.refresh(call['id'])
        if not self.service.begin_submission(call['id'], execution_lease=execution_lease,
                                             expected_task_revision=request.expected_task_revision,
                                             provenance_context=context):
            current = self.service.get_call(call['id'])
            return self.refresh(call['id']) if current.get('provider_response_id') else {'call': current, 'response': None}
        if create_events is not None:
            return self._consume_frozen_events(
                call, lambda: create_events(wire_json=saved_wire, execution_contract=frozen),
                on_delta=on_delta, submitted=True,
            )
        try:
            receipt = self.provider.create_frozen(wire_json=saved_wire, execution_contract=frozen)
        except Exception as exc:
            request_id = safe_request_id(getattr(exc, 'request_id', None))
            self._mark_unknown(call['id'], 'model_provider_request_failed', request_id)
            raise ModelGatewayError('model_provider_request_failed', request_id=request_id,
                                    status_code=getattr(exc, 'status_code', None)) from None
        return self._record(call['id'], receipt, submitted=True)

    def resume_frozen_writing(self, call_id, *, starting_after, on_delta):
        """Observe an admitted response by GET, within its original observation window."""
        call = self.service.get_call(call_id)
        response_id = call.get('provider_response_id')
        if not response_id:
            return {'call': call, 'response': None}
        if call.get('provider_status') not in ('queued', 'in_progress') or self._observation_expired(call):
            return self.refresh(call_id)
        policy = self._saved_policy(call)
        if policy.tools or policy.output_format != 'manuscript_writing_v2':
            raise ModelGatewayError('model_input_invalid')
        if starting_after is not None and (type(starting_after) is not int or starting_after < 0):
            raise ModelGatewayError('model_input_invalid')
        retrieve_events = getattr(self.provider, 'retrieve_events', None)
        if not callable(retrieve_events):
            from app.domain.model_usage.provenance import public_provider_provenance
            if (self.service.store.config.environment == 'test' and public_provider_provenance(call) == 'synthetic_fixture'
                    and getattr(self.provider, 'source_kind', None) == 'synthetic_fixture'):
                return self.refresh(call_id)
            raise ModelGatewayError('model_provider_request_failed')
        # The provider can resume after response.created, so consult the saved identity evidence.
        with self.service.store.connection() as db:
            model_mismatch = db.execute("SELECT 1 FROM usage_events WHERE call_id=%s AND reason_code='model_mismatch' LIMIT 1",
                                        (call_id,)).fetchone()
        if model_mismatch:
            return self.refresh(call_id)
        return self._consume_frozen_events(
            call, lambda: retrieve_events(response_id, policy=policy, starting_after=starting_after),
            on_delta=on_delta, submitted=False,
        )

    def _consume_frozen_events(self, call, open_events, *, on_delta, submitted):
        call_id = call['id']
        response_id = call.get('provider_response_id')
        result = {'call': call, 'response': None}
        model_matches = True
        events = None
        provider_error = None
        try:
            events = iter(open_events())
        except Exception as exc:
            provider_error = exc
        if events is not None:
            try:
                while True:
                    try:
                        kind, value = next(events)
                    except StopIteration:
                        break
                    except Exception as exc:
                        provider_error = exc
                        break
                    if kind == 'receipt':
                        if response_id and (not isinstance(value, dict) or value.get('response_id') != response_id):
                            break
                        result = self._record(call_id, value, submitted=submitted and not response_id)
                        response_id = result['call'].get('provider_response_id')
                        model_matches = model_matches and value['model'] == call['model']
                        if value['status'] not in ('queued', 'in_progress'):
                            return result
                    elif kind == 'delta' and response_id and model_matches and on_delta is not None:
                        on_delta(result['call'], value)
            finally:
                close = getattr(events, 'close', None)
                if close is not None:
                    close()
        if response_id:
            return self.refresh(call_id)
        request_id = safe_request_id(getattr(provider_error, 'request_id', None))
        code = 'model_provider_request_failed' if provider_error is not None else 'model_response_invalid'
        self._mark_unknown(call_id, code, request_id)
        raise ModelGatewayError(code, request_id=request_id, status_code=getattr(provider_error, 'status_code', None)) from None

    def submit_plot(self, request: 'CallRequest', *, instructions: str, payload: dict, execution_lease) -> dict:
        """At most one remote POST per slice, using persisted side-effect checkpoints."""
        self._configuration_gate(request)
        from app.domain.model_usage.contracts import CallRequest
        from app.adapters.openai_plot import PROMPT_VERSION
        from app.adapters.task_execution_store import LeaseLost
        if execution_lease is None:
            raise LeaseLost()
        try:
            request = CallRequest.model_validate(deepcopy(request).model_dump())
            if (request.policy.tools != ['code_interpreter'] or request.policy.output_format != 'text'
                    or request.policy.prompt_version not in (PROMPT_VERSION,'openai_analysis_plot_v2','openai_comparison_plot_v3','openai_modeling_plot_v4','openai_figure_workbench_v1','openai_figure_workbench_v2','openai_figure_workbench_v3','openai_figure_workbench_v4')):
                raise ValueError('A supported plot policy is required.')
            material = json.loads(canonical_payload(payload))
            if input_digest(instructions=instructions, payload=material) != request.input_digest:
                raise ModelGatewayError('model_input_digest_mismatch')
        except (TypeError, ValueError, RecursionError):
            raise ModelGatewayError('model_input_invalid') from None
        call = self.service.reserve_call(request, execution_lease=execution_lease)
        if call.get('provider_response_id'):
            return self.refresh(call['id'])
        state = call.get('provider_state') or {}
        step = {None: 'container', 'container_ready': 'upload', 'file_ready': 'response'}.get(state.get('phase'))
        if step is None or call['status'] in ('submission_unknown', 'released', 'failed', 'completed'):
            return {'call': call, 'response': None}
        from app.domain.model_usage.provenance import admission_context
        context=admission_context(self.provider,request=request,operation='plot') if step=='container' else None
        if not self.service.begin_plot_step(call['id'], step, execution_lease=execution_lease,
                                             expected_task_revision=request.expected_task_revision,provenance_context=context):
            return {'call': self.service.get_call(call['id']), 'response': None}
        try:
            if step == 'container':
                receipt = self.provider.create_container(policy=request.policy, call_id=call['id'])
            elif step == 'upload':
                receipt = self.provider.upload_input(policy=request.policy,
                    container_id=state['container_id'], payload=material)
            else:
                receipt = self.provider.create_plot(policy=request.policy, instructions=instructions,
                    container_id=state['container_id'], input_file_path=state['input_file_path'])
        except Exception as exc:
            request_id = safe_request_id(getattr(exc, 'request_id', None))
            expired = (step == 'upload' and getattr(exc, 'code', None) == 'plot_container_expired'
                       and getattr(exc, 'status_code', None) in (404, 410))
            code = 'plot_container_expired' if expired else 'model_provider_request_failed'
            if expired:
                try:
                    self.service.fail_plot_preparation(call['id'], error_code=code, request_id=request_id)
                except Exception:
                    self._mark_unknown(call['id'], 'model_receipt_persistence_failed', request_id)
                    raise ModelGatewayError('model_receipt_persistence_failed', request_id=request_id) from None
            else:
                self._mark_unknown(call['id'], code, request_id)
            raise ModelGatewayError(code, request_id=request_id,
                                    status_code=getattr(exc, 'status_code', None)) from None
        if step == 'response':
            return self._record(call['id'], receipt, submitted=True)
        try:
            if not isinstance(receipt, dict):
                raise ValueError('Invalid provider receipt.')
            fields = ('container_id',) if step == 'container' else ('input_file_id', 'input_file_path')
            call = self.service.record_plot_step(call['id'], step,
                request_id=safe_request_id(receipt.get('request_id')), **{key: receipt[key] for key in fields})
        except Exception:
            request_id = safe_request_id(receipt.get('request_id')) if isinstance(receipt, dict) else None
            self._mark_unknown(call['id'], 'model_receipt_persistence_failed', request_id)
            raise ModelGatewayError('model_receipt_persistence_failed', request_id=request_id) from None
        return {'call': call, 'response': None}

    def refresh(self, call_id: str, *, accept_terminal_failure=False) -> dict:
        call = self.service.get_call(call_id)
        response_id = call.get('provider_response_id')
        if not response_id:
            return {'call': call, 'response': None}
        continuation = self._observation_expired(call)
        policy = self._saved_policy(call)
        if policy.tools and policy.tools != ['code_interpreter']:
            raise ModelGatewayError('model_tools_unsupported')
        if continuation:
            consume = getattr(self.service, 'consume_observation_grant', None)
            if consume is None or not consume(call_id, response_id):
                raise ModelGatewayError('model_observation_expired')
        try:
            receipt = self.provider.retrieve(response_id, policy=policy)
        except Exception as exc:
            # Preserve the saved response so the next poll can use the same ID.
            status_code = getattr(exc, 'status_code', None)
            code = ('model_observation_expired' if continuation else
                    'model_response_not_found' if status_code == 404 else
                    exc.code if isinstance(exc, ModelProviderError) else 'internal_error')
            raise ModelGatewayError(code,
                                    request_id=getattr(exc, 'request_id', None), status_code=status_code) from None
        if not isinstance(receipt, dict) or receipt.get('response_id') != response_id:
            raise ModelGatewayError('model_observation_expired' if continuation else 'model_response_invalid',
                                    request_id=receipt.get('request_id') if isinstance(receipt, dict) else None)
        try:
            result = self._record(call_id, receipt, submitted=False)
        except ModelGatewayError as exc:
            if continuation:
                raise ModelGatewayError('model_observation_expired', request_id=exc.request_id,
                                        status_code=exc.status_code) from None
            raise
        status = receipt.get('status')
        finished = status == 'completed' or accept_terminal_failure and status in ('failed', 'incomplete', 'cancelled')
        if continuation and not finished:
            raise ModelGatewayError('model_observation_expired')
        return result

    @staticmethod
    def _observation_expired(call):
        from app.domain.model_usage.observation import expired
        try:
            return expired(call)
        except (KeyError, TypeError, ValueError):
            raise ModelGatewayError('model_response_invalid') from None

    @staticmethod
    def _saved_policy(call):
        from app.domain.model_usage.contracts import ModelPolicy
        snapshot = call['policy_snapshot']
        return ModelPolicy.model_validate({key: snapshot[key] for key in ModelPolicy.model_fields if key in snapshot})

    def _record(self, call_id, receipt, *, submitted):
        if not isinstance(receipt, dict):
            if submitted:
                self._mark_unknown(call_id, 'model_response_invalid', None)
            raise ModelGatewayError('model_response_invalid')
        request_id = safe_request_id(receipt.get('request_id'))
        try:
            observation = {key: receipt[key] for key in ('response_id', 'model', 'status', 'usage')}
            # Poll request IDs differ; accounting observations remain idempotent.
            event_key = 'response:' + sha256(canonical_payload(observation).encode('utf-8')).hexdigest()
        except (KeyError, TypeError, ValueError, RecursionError):
            if submitted:
                self._mark_unknown(call_id, 'model_response_invalid', request_id)
            raise ModelGatewayError('model_response_invalid', request_id=request_id) from None
        try:
            call = self.service.record_response(call_id, event_key=event_key, request_id=request_id,
                                                response=receipt.get('response'),
                                                **observation)
        except Exception as exc:
            code = ('model_response_invalid' if isinstance(exc, StorageError)
                    and exc.code == 'model_usage_input_invalid' else 'model_receipt_persistence_failed')
            if submitted:
                self._mark_unknown(call_id, code, request_id)
            raise ModelGatewayError(code, request_id=request_id) from None
        return {'call': call, 'response': receipt.get('response')}

    def _mark_unknown(self, call_id, code, request_id):
        try:
            self.service.mark_submission_unknown(call_id, error_code=code, request_id=request_id)
        except Exception:
            # The already committed submitting state fences subsequent POSTs.
            pass
