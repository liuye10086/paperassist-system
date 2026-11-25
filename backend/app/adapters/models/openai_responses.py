"""Official background Responses text requests; caller data never configures SDK options."""
import json
import math
import re
from typing import TYPE_CHECKING
from weakref import WeakKeyDictionary

from openai import APIConnectionError, APIError, APIStatusError, DefaultHttpxClient, OpenAI, Stream

from app.core.safe_logging import configure_safe_logging

if TYPE_CHECKING:
    from app.domain.model_usage.contracts import ModelPolicy


OFFICIAL_BASE_URL = 'https://api.openai.com/v1'
RESPONSE_ID = re.compile(r'resp_[A-Za-z0-9_-]{1,200}\Z')
_TRANSPORT_ORIGINS = WeakKeyDictionary()


def provider_transport_origin(provider):
    """Constructor-owned evidence; an adapter attribute or payload cannot set it."""
    return _TRANSPORT_ORIGINS.get(provider, 'unverified_injected')


class ModelProviderError(Exception):
    """Safe internal provider error, without provider text or exception chaining."""
    def __init__(self, code='model_provider_request_failed', *, request_id=None, status_code=None):
        super().__init__('模型供应商请求未能完成，请核对调用状态。')
        self.code = code
        self.request_id = safe_request_id(request_id)
        self.status_code = status_code if type(status_code) is int else None


def safe_request_id(value):
    if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,256}', value):
        return value
    return None


def canonical_payload(payload: dict) -> str:
    """Accept JSON data without silently coercing Python keys or nonfinite numbers."""
    def validate(value):
        if value is None or type(value) in (str, bool, int):
            return
        if type(value) is float and math.isfinite(value):
            return
        if type(value) is list:
            for item in value:
                validate(item)
            return
        if type(value) is dict and all(type(key) is str for key in value):
            for item in value.values():
                validate(item)
            return
        raise ValueError('Payload must contain JSON data only.')

    if type(payload) is not dict:
        raise ValueError('Payload must be an object.')
    validate(payload)
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


class OpenAIResponsesProvider:
    def _default_http_client(self):
        return DefaultHttpxClient(follow_redirects=False)

    def __init__(self, *, api_key: str, http_client=None):
        configure_safe_logging()
        # No arbitrary endpoint, SDK kwargs, tools, or environment-selected URL.
        if http_client is None:
            http_client = self._default_http_client()
            origin = 'official_default'
        else:
            http_client.follow_redirects = False
            origin = 'unverified_injected'
        self.client = OpenAI(api_key=api_key, base_url=OFFICIAL_BASE_URL,
                             max_retries=0, timeout=45, http_client=http_client)
        _TRANSPORT_ORIGINS[self] = origin

    def create(self, *, policy: 'ModelPolicy', instructions: str, payload: dict) -> dict:
        if policy.tools:
            raise ModelProviderError('model_tools_unsupported')
        try:
            if not isinstance(instructions, str) or not instructions.strip():
                raise ValueError('Instructions must be nonempty.')
            content = canonical_payload(payload)
            if getattr(policy, 'output_format', 'text') == 'reader_report_v1':
                from app.domain.reader_reports.content import multimodal_input
                content = multimodal_input(payload)
        except (TypeError, ValueError, RecursionError):
            raise ModelProviderError('model_input_invalid') from None
        try:
            options = {}
            if getattr(policy, 'output_format', 'text') == 'reader_report_v1':
                from app.domain.reader_reports.content import response_schema
                options['text'] = {'format': {'type': 'json_schema', 'name': 'reader_report_v1',
                                              'strict': True, 'schema': response_schema()}}
            elif getattr(policy, 'output_format', 'text') in ('analysis_explanation_v1','analysis_explanation_v2','analysis_explanation_v3','analysis_explanation_v4'):
                from app.adapters.openai_explanation import SCHEMA
                options['text'] = {'format': {'type': 'json_schema', 'name': 'analysis_explanation',
                                             'strict': True, 'schema': SCHEMA}}
            elif getattr(policy, 'output_format', 'text') in ('analysis_recommendation_v1','analysis_recommendation_v2','analysis_recommendation_v3','analysis_recommendation_v4','analysis_recommendation_v5'):
                from app.domain.analysis_recommendation.contracts import RecommendationDraft, RecommendationDraftV2, RecommendationDraftV3, RecommendationDraftV4, RecommendationDraftV5
                draft = {'analysis_recommendation_v1': RecommendationDraft,
                         'analysis_recommendation_v2': RecommendationDraftV2,
                         'analysis_recommendation_v3': RecommendationDraftV3,
                         'analysis_recommendation_v4': RecommendationDraftV4,'analysis_recommendation_v5':RecommendationDraftV5}[policy.output_format]
                options['text']={'format':{'type':'json_schema','name':'analysis_recommendation','strict':True,'schema':draft.model_json_schema()}}
            elif getattr(policy, 'output_format', 'text') == 'school_rule_suggestions_v1':
                from app.domain.school_templates.suggestion_contracts import SuggestionDraft
                options['text']={'format':{'type':'json_schema','name':'school_rule_suggestions_v1','strict':True,'schema':SuggestionDraft.model_json_schema()}}
            elif getattr(policy, 'output_format', 'text') != 'text':
                raise ModelProviderError('model_input_invalid')
            response = self.client.responses.create(
                model=policy.model, background=True, store=True,
                instructions=instructions, input=content,
                max_output_tokens=policy.max_output_tokens, timeout=policy.timeout_seconds, **options)
            return self._receipt(response)
        except (APIConnectionError, APIStatusError) as exc:
            raise ModelProviderError(request_id=getattr(exc, 'request_id', None),
                                     status_code=getattr(exc, 'status_code', None)) from None

    def create_frozen(self, *, wire_json: str, execution_contract=None) -> dict:
        """Transmit the canonical body verbatim; SDK rebuilding cannot change its bytes."""
        from app.domain.manuscript_writing.frozen import contract,validate_wire
        try:
            if isinstance(execution_contract, dict) and execution_contract.get('response_stream') is True:
                raise ValueError('Streaming requires the frozen event transport.')
            frozen=validate_wire(wire_json,execution_contract if execution_contract is not None else contract())
            from openai.types.responses import Response
            response=self.client.post('/responses',cast_to=Response,content=wire_json.encode('utf-8'),options={
                'headers':{'Content-Type':'application/json'},'timeout':frozen.timeout_seconds})
            return self._receipt(response)
        except (KeyError,ValueError,TypeError):
            raise ModelProviderError('model_input_invalid') from None
        except (APIConnectionError, APIStatusError) as exc:
            raise ModelProviderError(request_id=getattr(exc,'request_id',None),status_code=getattr(exc,'status_code',None)) from None

    def create_frozen_events(self, *, wire_json: str, execution_contract: dict):
        """Stream the exact approved POST body through the official SDK."""
        from openai.types.responses import Response, ResponseStreamEvent
        from app.domain.manuscript_writing.frozen import validate_wire

        if not isinstance(execution_contract, dict) or execution_contract.get('response_stream') is not True:
            raise ModelProviderError('model_input_invalid')
        try:
            policy = validate_wire(wire_json, execution_contract)
        except (KeyError, ValueError, TypeError):
            raise ModelProviderError('model_input_invalid') from None
        yield from self._response_events(
            self.client.post, '/responses', cast_to=Response, content=wire_json.encode('utf-8'),
            options={'headers': {'Content-Type': 'application/json'}, 'timeout': policy.timeout_seconds},
            stream=True, stream_cls=Stream[ResponseStreamEvent],
        )

    def retrieve_events(self, response_id: str, *, policy: 'ModelPolicy', starting_after: int | None):
        """Resume an existing response from its last persisted event cursor."""
        if policy.tools:
            raise ModelProviderError('model_tools_unsupported')
        if not isinstance(response_id, str) or not RESPONSE_ID.fullmatch(response_id):
            raise ModelProviderError('model_response_invalid')
        if starting_after is not None and (type(starting_after) is not int or starting_after < 0):
            raise ModelProviderError('model_input_invalid')
        options = {'starting_after': starting_after} if starting_after is not None else {}
        yield from self._response_events(self.client.responses.retrieve, response_id,
                                         stream=True, timeout=policy.timeout_seconds, **options)

    def _response_events(self, open_stream, *args, **kwargs):
        from openai.types.responses import Response

        request_id = None
        receipt_events = {
            'response.created', 'response.completed', 'response.failed', 'response.incomplete', 'response.cancelled',
        }
        try:
            with open_stream(*args, **kwargs) as stream:
                request_id = safe_request_id(stream.response.headers.get('x-request-id'))
                for event in stream:
                    kind = getattr(event, 'type', None)
                    if kind in receipt_events:
                        response = getattr(event, 'response', None)
                        if not isinstance(response, Response):
                            raise ModelProviderError('model_response_invalid', request_id=request_id)
                        yield 'receipt', self._receipt(response, request_id=request_id)
                    elif kind == 'response.output_text.delta':
                        event_data = {key: getattr(event, key, None) for key in
                                      ('sequence_number', 'item_id', 'output_index', 'content_index', 'delta')}
                        if (not all(type(event_data[key]) is int and event_data[key] >= 0 for key in
                                    ('sequence_number', 'output_index', 'content_index'))
                                or not safe_request_id(event_data['item_id']) or not isinstance(event_data['delta'], str)):
                            raise ModelProviderError('model_response_invalid', request_id=request_id)
                        yield 'delta', event_data
                    elif kind == 'error':
                        raise ModelProviderError(request_id=request_id)
        except APIError as exc:
            raise ModelProviderError(request_id=safe_request_id(getattr(exc, 'request_id', None)) or request_id,
                                     status_code=getattr(exc, 'status_code', None)) from None
        except (TypeError, ValueError):
            raise ModelProviderError('model_response_invalid', request_id=request_id) from None

    def retrieve(self, response_id: str, *, policy: 'ModelPolicy') -> dict:
        if policy.tools:
            raise ModelProviderError('model_tools_unsupported')
        if not isinstance(response_id, str) or not RESPONSE_ID.fullmatch(response_id):
            raise ModelProviderError('model_response_invalid')
        try:
            return self._receipt(self.client.responses.retrieve(response_id, timeout=policy.timeout_seconds))
        except (APIConnectionError, APIStatusError) as exc:
            raise ModelProviderError(request_id=getattr(exc, 'request_id', None),
                                     status_code=getattr(exc, 'status_code', None)) from None

    @staticmethod
    def _receipt(response, *, request_id=None) -> dict:
        data = response.model_dump(mode='json')
        # SDK defaults are not supplier evidence: preserve omitted usage fields
        # separately from explicitly returned nulls for accounting validation.
        usage = response.usage.model_dump(mode='json', exclude_unset=True) if response.usage is not None else None
        # SDK model_dump omits this dynamic attribute; the header is the evidence.
        request_id = safe_request_id(request_id) or safe_request_id(getattr(response, '_request_id', None))
        response_id = data.get('id')
        if not isinstance(response_id, str) or not RESPONSE_ID.fullmatch(response_id):
            raise ModelProviderError('model_response_invalid', request_id=request_id)
        return {'response_id': response_id, 'request_id': request_id, 'model': data.get('model'),
                'status': data.get('status'), 'usage': usage, 'response': data}

    def close(self):
        self.client.close()
