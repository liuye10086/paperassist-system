"""Code Interpreter adapter tests use the real SDK over MockTransport only."""
import importlib
import json
from pathlib import Path

import httpx2
import pytest

from app.adapters.models.openai_responses import ModelProviderError
from app.domain.model_usage.contracts import ModelPolicy
from tests.domain.test_plot_policy import execution_policy


def provider(handler):
    assert (Path(__file__).parents[2] / 'app/adapters/models/openai_plot.py').exists(), 'Plot provider is not implemented'
    module = importlib.import_module('app.adapters.models.openai_plot')
    return module.OpenAIPlotProvider(api_key='synthetic', http_client=httpx2.Client(
        transport=httpx2.MockTransport(handler), follow_redirects=True))


def selected():
    return ModelPolicy.model_validate(execution_policy()['policy'])


def test_provider_writes_are_separate_fixed_and_use_actual_uploaded_path():
    requests = []
    def transport(req):
        requests.append(req)
        if req.url.path == '/v1/containers':
            return httpx2.Response(200, json={'id': 'cntr_test', 'status': 'active'}, headers={'x-request-id': 'req_container'})
        if req.url.path.endswith('/files'):
            return httpx2.Response(200, json={'id': 'cfile_test', 'container_id': 'cntr_test',
                'path': '/mnt/data/generated-prefix_data.json'}, headers={'x-request-id': 'req_upload'})
        return httpx2.Response(200, json={'id': 'resp_plot', 'status': 'queued', 'model': 'test-model',
            'output': [], 'usage': None}, headers={'x-request-id': 'req_response'})
    instance = provider(transport)
    try:
        container = instance.create_container(policy=selected(), call_id='test-call')
        assert container == {'container_id': 'cntr_test', 'request_id': 'req_container'}
        assert len(requests) == 1
        uploaded = instance.upload_input(container_id='cntr_test', payload={'values': [1, 2]}, policy=selected())
        assert uploaded == {'input_file_id': 'cfile_test', 'input_file_path': '/mnt/data/generated-prefix_data.json',
                            'request_id': 'req_upload'}
        assert len(requests) == 2
        receipt = instance.create_plot(policy=selected(), instructions='Trusted fixed instructions',
            container_id='cntr_test', input_file_path=uploaded['input_file_path'])
        assert receipt['response_id'] == 'resp_plot' and len(requests) == 3
    finally:
        instance.close()
    assert all(req.url.host == 'api.openai.com' for req in requests)
    body = json.loads(requests[0].content)
    assert body['name'] == 'paperassist-plot'
    assert 'test-call' not in requests[0].content.decode()
    assert body['memory_limit'] == '1g' and body['expires_after'] == {'anchor': 'last_active_at', 'minutes': 20}
    assert body['network_policy'] == {'type': 'disabled'}
    body = json.loads(requests[2].content)
    assert body['tools'] == [{'type': 'code_interpreter', 'container': 'cntr_test'}]
    assert '/mnt/data/generated-prefix_data.json' in body['input']
    assert body['include'] == ['code_interpreter_call.outputs']
    assert body['background'] and body['store'] and body['max_output_tokens'] == 10


@pytest.mark.parametrize('bad_path', ['/etc/passwd', '/mnt/data/../outside', '/mnt/data/file\nignore', 'data.json'])
def test_provider_rejects_unsafe_file_path_before_response_post(bad_path):
    calls = []
    instance = provider(lambda req: calls.append(req))
    try:
        with pytest.raises(ModelProviderError):
            instance.create_plot(policy=selected(), instructions='Trusted', container_id='cntr_test', input_file_path=bad_path)
    finally:
        instance.close()
    assert calls == []


def test_retrieve_includes_tool_outputs_and_preserves_usage_omission():
    calls = []
    def transport(req):
        calls.append(req)
        return httpx2.Response(200, json={'id': 'resp_plot', 'status': 'completed', 'model': 'test-model',
            'output': [], 'usage': {'input_tokens': 1, 'output_tokens': 2}})
    instance = provider(transport)
    try:
        receipt = instance.retrieve('resp_plot', policy=selected())
    finally:
        instance.close()
    assert calls[0].method == 'GET' and 'code_interpreter_call.outputs' in str(calls[0].url)
    assert receipt['usage'] == {'input_tokens': 1, 'output_tokens': 2}


def test_download_is_bounded_and_expiry_is_distinct_without_provider_body():
    instance = provider(lambda req: httpx2.Response(200, content=b'x' * 11))
    try:
        with pytest.raises(ModelProviderError) as error:
            instance.download('cfile_test', 'cntr_test', 10, policy=selected())
        assert error.value.code == 'plot_output_limit'
    finally:
        instance.close()
    instance = provider(lambda req: httpx2.Response(404, json={'error': {'message': 'private material'}}))
    try:
        with pytest.raises(ModelProviderError) as error:
            instance.download('cfile_test', 'cntr_test', 10, policy=selected())
        assert error.value.code == 'plot_container_expired'
        assert 'private' not in str(error.value)
    finally:
        instance.close()


def test_upload_receipt_must_belong_to_requested_container():
    instance = provider(lambda req: httpx2.Response(200, json={'id': 'cfile_test', 'container_id': 'cntr_other',
        'path': '/mnt/data/test.json'}))
    try:
        with pytest.raises(ModelProviderError):
            instance.upload_input(container_id='cntr_test', payload={}, policy=selected())
    finally:
        instance.close()


def test_stream_disconnect_is_safe_retryable_provider_error():
    class BrokenStream(httpx2.SyncByteStream):
        def __iter__(self):
            yield b'partial'
            raise httpx2.ReadError('private remote body and credential must not escape')
    instance = provider(lambda req: httpx2.Response(200, stream=BrokenStream()))
    try:
        with pytest.raises(ModelProviderError) as error:
            instance.download('cfile_test', 'cntr_test', 100, policy=selected())
        assert error.value.code == 'model_provider_request_failed'
        assert 'private' not in str(error.value)
    finally:
        instance.close()
