"""Read-only classification boundaries, without network or developer credentials."""
import pytest

from app.adapters.models.openai_responses import ModelProviderError
from app.domain.model_usage.gateway import ModelGateway, ModelGatewayError
from tests.adapters.test_model_gateway import Provider, Service


@pytest.mark.parametrize('status', [401, 403, 429, 500, 502, 503, 504])
def test_gateway_retains_safe_http_status_for_known_response_read(status):
    service = Service(row={'status': 'submitted', 'provider_response_id': 'resp_text'})
    provider = Provider(service, error=ModelProviderError(status_code=status, request_id='req_safe'))
    with pytest.raises(ModelGatewayError) as caught:
        ModelGateway(service, provider).refresh('call-1')
    assert caught.value.status_code == status
    assert caught.value.request_id == 'req_safe'
    assert provider.posts == []


@pytest.mark.parametrize('status', [True, '503', -1, 999, object()])
def test_gateway_error_does_not_retain_unsafe_status(status):
    assert ModelGatewayError('internal_error', status_code=status).status_code is None


def test_unknown_provider_programming_error_is_not_a_temporary_network_error():
    service = Service(row={'status': 'submitted', 'provider_response_id': 'resp_text'})
    provider = Provider(service, error=RuntimeError('private provider details'))
    with pytest.raises(ModelGatewayError) as caught:
        ModelGateway(service, provider).refresh('call-1')
    assert caught.value.code == 'internal_error'
    assert 'private' not in str(caught.value)


def test_provider_validation_error_code_survives_gateway_read():
    service = Service(row={'status': 'submitted', 'provider_response_id': 'resp_text'})
    provider = Provider(service, error=ModelProviderError('model_response_invalid'))
    with pytest.raises(ModelGatewayError) as caught:
        ModelGateway(service, provider).refresh('call-1')
    assert caught.value.code == 'model_response_invalid'


@pytest.mark.parametrize('field', ['model', 'status', 'usage'])
def test_missing_receipt_fields_are_invalid_output_not_persistence_errors(field):
    service = Service(row={'status': 'submitted', 'provider_response_id': 'resp_text'})
    provider = Provider(service)
    del provider.result[field]
    with pytest.raises(ModelGatewayError) as caught:
        ModelGateway(service, provider).refresh('call-1')
    assert caught.value.code == 'model_response_invalid'
    assert not any(isinstance(event, tuple) and event[0] == 'record' for event in service.events)
