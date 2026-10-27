"""Official background Responses text requests; caller data never configures SDK options."""
import json
import math
import re
from typing import TYPE_CHECKING

from openai import APIConnectionError, APIStatusError, DefaultHttpxClient, OpenAI

from app.core.safe_logging import configure_safe_logging

if TYPE_CHECKING:
    from app.domain.model_usage.contracts import ModelPolicy


OFFICIAL_BASE_URL = 'https://api.openai.com/v1'
RESPONSE_ID = re.compile(r'resp_[A-Za-z0-9_-]{1,200}\Z')


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
    def __init__(self, *, api_key: str, http_client=None):
        configure_safe_logging()
        # No arbitrary endpoint, SDK kwargs, tools, or environment-selected URL.
        if http_client is None:
            http_client = DefaultHttpxClient(follow_redirects=False)
        else:
            http_client.follow_redirects = False
        self.client = OpenAI(api_key=api_key, base_url=OFFICIAL_BASE_URL,
                             max_retries=0, timeout=45, http_client=http_client)

    def create(self, *, policy: 'ModelPolicy', instructions: str, payload: dict) -> dict:
        if policy.tools:
            raise ModelProviderError('model_tools_unsupported')
        try:
            if not isinstance(instructions, str) or not instructions.strip():
                raise ValueError('Instructions must be nonempty.')
            content = canonical_payload(payload)
        except (TypeError, ValueError, RecursionError):
            raise ModelProviderError('model_input_invalid') from None
        try:
            options = {}
            if getattr(policy, 'output_format', 'text') in ('analysis_explanation_v1','analysis_explanation_v2','analysis_explanation_v3','analysis_explanation_v4'):
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
            frozen=validate_wire(wire_json,execution_contract if execution_contract is not None else contract())
            from openai.types.responses import Response
            response=self.client.post('/responses',cast_to=Response,content=wire_json.encode('utf-8'),options={
                'headers':{'Content-Type':'application/json'},'timeout':frozen.timeout_seconds})
            return self._receipt(response)
        except (KeyError,ValueError,TypeError):
            raise ModelProviderError('model_input_invalid') from None
        except (APIConnectionError, APIStatusError) as exc:
            raise ModelProviderError(request_id=getattr(exc,'request_id',None),status_code=getattr(exc,'status_code',None)) from None

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
    def _receipt(response) -> dict:
        data = response.model_dump(mode='json')
        # SDK defaults are not supplier evidence: preserve omitted usage fields
        # separately from explicitly returned nulls for accounting validation.
        usage = response.usage.model_dump(mode='json', exclude_unset=True) if response.usage is not None else None
        # SDK model_dump omits this dynamic attribute; the header is the evidence.
        request_id = safe_request_id(getattr(response, '_request_id', None))
        response_id = data.get('id')
        if not isinstance(response_id, str) or not RESPONSE_ID.fullmatch(response_id):
            raise ModelProviderError('model_response_invalid', request_id=request_id)
        return {'response_id': response_id, 'request_id': request_id, 'model': data.get('model'),
                'status': data.get('status'), 'usage': usage, 'response': data}

    def close(self):
        self.client.close()
