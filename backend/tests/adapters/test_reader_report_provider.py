import base64
import io
import json
from types import SimpleNamespace

import httpx2
import pytest
from PIL import Image


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def material():
    stream = io.BytesIO(); Image.new('RGB', (20, 20)).save(stream, 'PNG')
    return {'standard_version': 'reader-report-v1', 'language': 'en', 'report_kind': 'research',
            'facts': {'count': 12}, 'figures': [{'number': 1, 'title': 'Distribution',
            'image_url': 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode()}]}


def test_reader_provider_sends_real_images_with_structured_schema():
    from app.adapters.models.openai_responses import OpenAIResponsesProvider
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx2.Response(200, json={'id': 'resp_reader', 'object': 'response', 'created_at': 1,
            'model': 'test-model', 'status': 'queued', 'output': [], 'usage': None})
    p = SimpleNamespace(tools=[], output_format='reader_report_v1', model='test-model',
                        max_output_tokens=22000, timeout_seconds=45)
    source = material()
    with httpx2.Client(transport=httpx2.MockTransport(handler)) as http:
        provider = OpenAIResponsesProvider(api_key='synthetic', http_client=http)
        receipt = provider.create(policy=p, instructions='Use recorded facts.', payload=source)
    body = calls[0]; parts = body['input'][0]['content']
    assert receipt['response_id'] == 'resp_reader'
    assert parts[-1] == {'type': 'input_image', 'image_url': source['figures'][0]['image_url'], 'detail': 'high'}
    assert 'base64' not in parts[0]['text'] and json.loads(parts[0]['text'])['facts']['count'] == 12
    assert body['text']['format']['name'] == 'reader_report_v1'
    assert body['background'] and body['store'] and not body.get('tools')


def test_reader_provider_rejects_remote_image_without_network():
    from app.adapters.models.openai_responses import OpenAIResponsesProvider, ModelProviderError
    source = material(); source['figures'][0]['image_url'] = 'https://private.invalid/image.png'
    p = SimpleNamespace(tools=[], output_format='reader_report_v1', model='test-model', max_output_tokens=22000, timeout_seconds=45)
    calls = []
    with httpx2.Client(transport=httpx2.MockTransport(lambda r: calls.append(r))) as http:
        with pytest.raises(ModelProviderError):
            OpenAIResponsesProvider(api_key='synthetic', http_client=http).create(policy=p, instructions='Use facts.', payload=source)
    assert calls == []
