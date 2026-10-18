"""New structured explanation requests and lease forwarding."""
import json

import httpx2
import pytest

from app.adapters.models.openai_responses import OpenAIResponsesProvider
from app.domain.model_usage.contracts import ModelPolicy
from app.domain.model_usage.gateway import ModelGateway, ModelGatewayError
from tests.adapters.test_model_gateway import Service, Provider, policy, request, INSTRUCTIONS, PAYLOAD


@pytest.mark.parametrize('output_format', ['analysis_explanation_v1','analysis_explanation_v2','analysis_explanation_v3','analysis_recommendation_v1','analysis_recommendation_v2','analysis_recommendation_v3','analysis_recommendation_v4'])
def test_policy_supports_only_trusted_output_format_and_sdk_uses_fixed_schema(output_format):
    from app.adapters.openai_explanation import SCHEMA
    from app.domain.analysis_recommendation.contracts import RecommendationDraft, RecommendationDraftV2, RecommendationDraftV3, RecommendationDraftV4
    drafts={'analysis_recommendation_v1':RecommendationDraft,'analysis_recommendation_v2':RecommendationDraftV2,
            'analysis_recommendation_v3':RecommendationDraftV3,'analysis_recommendation_v4':RecommendationDraftV4}
    expected_schema = drafts[output_format].model_json_schema() if output_format in drafts else SCHEMA
    name = 'analysis_recommendation' if output_format.startswith('analysis_recommendation_') else 'analysis_explanation'
    selected = ModelPolicy.model_validate(vars(policy()) | {'output_format': output_format})
    requests = []
    def transport(req):
        requests.append(json.loads(req.content))
        return httpx2.Response(200, json={'id': 'resp_text', 'object': 'response', 'status': 'queued',
            'model': selected.model, 'output': [], 'usage': None}, request=req)
    provider = OpenAIResponsesProvider(api_key='synthetic', http_client=httpx2.Client(transport=httpx2.MockTransport(transport)))
    try:
        provider.create(policy=selected, instructions=INSTRUCTIONS, payload=PAYLOAD)
    finally:
        provider.close()
    assert requests[0]['text']['format'] == {
        'type': 'json_schema', 'name': name, 'strict': True, 'schema': expected_schema}
    assert requests[0]['model'] == selected.model
    assert 'tools' not in requests[0]


def test_gateway_passes_lease_and_current_revision_only_when_present():
    class Fenced(Service):
        def reserve_call(self, req, execution_lease=None):
            assert execution_lease is lease
            return super().reserve_call(req)
        def begin_submission(self, call_id, execution_lease=None, expected_task_revision=None):
            assert execution_lease is lease and expected_task_revision == 2
            return super().begin_submission(call_id)
    lease = object()
    service = Fenced()
    provider = Provider(service)
    ModelGateway(service, provider).submit(request(), instructions=INSTRUCTIONS, payload=PAYLOAD, execution_lease=lease)
    assert len(provider.posts) == 1


def test_refresh_old_snapshot_defaults_to_text_and_404_is_distinct():
    class Missing(Exception):
        status_code = 404
    service = Service(row={'provider_response_id': 'resp_text', 'status': 'submitted'})
    provider = Provider(service, error=Missing('private upstream body'))
    with pytest.raises(ModelGatewayError) as error:
        ModelGateway(service, provider).refresh('call-1')
    assert error.value.code == 'model_response_not_found'
    assert service.row['provider_response_id'] == 'resp_text'


def test_official_sdk_404_remains_classifiable_without_leaking_body():
    def transport(req):
        return httpx2.Response(404, json={'error': {'message': 'private provider body'}}, request=req)
    provider = OpenAIResponsesProvider(api_key='synthetic', http_client=httpx2.Client(transport=httpx2.MockTransport(transport)))
    try:
        with pytest.raises(Exception) as error:
            provider.retrieve('resp_missing', policy=ModelPolicy.model_validate(vars(policy())))
        assert getattr(error.value, 'status_code', None) == 404
        assert 'private' not in str(error.value)
    finally:
        provider.close()
