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

    def submit(self, request: 'CallRequest', *, instructions: str, payload: dict, execution_lease=None) -> dict:
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

    def submit_plot(self, request: 'CallRequest', *, instructions: str, payload: dict, execution_lease) -> dict:
        """At most one remote POST per slice, using persisted side-effect checkpoints."""
        from app.domain.model_usage.contracts import CallRequest
        from app.adapters.openai_plot import PROMPT_VERSION
        from app.adapters.task_execution_store import LeaseLost
        if execution_lease is None:
            raise LeaseLost()
        try:
            request = CallRequest.model_validate(deepcopy(request).model_dump())
            if (request.policy.tools != ['code_interpreter'] or request.policy.output_format != 'text'
                    or request.policy.prompt_version != PROMPT_VERSION or request.tool_reserve_micro_usd <= 0
                    or not request.tool_reserve_version):
                raise ValueError('A fixed plot policy and positive tool reservation are required.')
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
        if not self.service.begin_plot_step(call['id'], step, execution_lease=execution_lease,
                                             expected_task_revision=request.expected_task_revision):
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

    def refresh(self, call_id: str) -> dict:
        call = self.service.get_call(call_id)
        response_id = call.get('provider_response_id')
        if not response_id:
            return {'call': call, 'response': None}
        from app.domain.model_usage.contracts import ModelPolicy
        snapshot = call['policy_snapshot']
        policy = ModelPolicy.model_validate({key: snapshot[key] for key in ModelPolicy.model_fields if key in snapshot})
        if policy.tools and policy.tools != ['code_interpreter']:
            raise ModelGatewayError('model_tools_unsupported')
        try:
            receipt = self.provider.retrieve(response_id, policy=policy)
        except Exception as exc:
            # GET cannot invalidate the saved response or release its reservation.
            status_code = getattr(exc, 'status_code', None)
            code = ('model_response_not_found' if status_code == 404 else
                    exc.code if isinstance(exc, ModelProviderError) else 'internal_error')
            raise ModelGatewayError(code,
                                    request_id=getattr(exc, 'request_id', None), status_code=status_code) from None
        if not isinstance(receipt, dict) or receipt.get('response_id') != response_id:
            raise ModelGatewayError('model_response_invalid',
                                    request_id=receipt.get('request_id') if isinstance(receipt, dict) else None)
        return self._record(call_id, receipt, submitted=False)

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
