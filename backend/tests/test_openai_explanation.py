import json

import httpx2
from openai import OpenAI
import pytest

from app import openai_explanation
from app.openai_plot import PlotError


def response(**changes):
    return {'id': 'resp_explain', 'object': 'response', 'created_at': 1, 'model': 'test-model', 'status': 'completed',
            'output': [{'id': 'msg', 'type': 'message', 'role': 'assistant', 'status': 'completed',
                        'content': [{'type': 'output_text', 'text': '{"purpose":"example"}', 'annotations': []}]}],
            'usage': {'input_tokens': 100, 'output_tokens': 200, 'total_tokens': 300}, **changes}


def sdk(monkeypatch, handler):
    monkeypatch.setenv('OPENAI_API_KEY', 'test-secret')
    monkeypatch.setenv('OPENAI_MODEL', 'test-model')
    def factory(**kwargs):
        assert kwargs['base_url'] == 'https://api.openai.com/v1'
        assert kwargs['max_retries'] == 0
        return OpenAI(**kwargs, http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    monkeypatch.setattr(openai_explanation, 'OpenAI', factory)


def test_official_background_json_schema_contract_without_tools(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        body = json.loads(request.content)
        assert request.url.path == '/v1/responses'
        assert body['background'] and body['store']
        assert not body.get('tools')
        assert body['text']['format']['type'] == 'json_schema'
        assert body['text']['format']['strict']
        assert set(body['text']['format']['schema']['required']) == {'purpose', 'data', 'methods', 'results', 'interpretation', 'paper_text'}
        assert json.loads(body['input']) == {'facts': {'overall.mean': {'value': '3'}}}
        return httpx2.Response(200, json=response(status='queued', output=[]))
    sdk(monkeypatch, handler)
    assert openai_explanation.CloudExplanation().start({'facts': {'overall.mean': {'value': '3'}}}) == 'resp_explain'
    assert len(calls) == 1


def test_fetch_parses_text_and_retains_provenance(monkeypatch):
    sdk(monkeypatch, lambda request: httpx2.Response(200, json=response()))
    output = openai_explanation.CloudExplanation().fetch({'response_id': 'resp_explain', 'model': 'test-model'})
    assert output['draft'] == {'purpose': 'example'}
    assert output['provenance']['usage']['total_tokens'] == 300
    assert output['provenance']['response_id'] == 'resp_explain'


@pytest.mark.parametrize('status', ['queued', 'in_progress'])
def test_pending_is_not_failure(monkeypatch, status):
    sdk(monkeypatch, lambda request: httpx2.Response(200, json=response(status=status, output=[])))
    assert openai_explanation.CloudExplanation().fetch({'response_id': 'resp_explain'}) is None


@pytest.mark.parametrize('kind', ['refusal', 'incomplete', 'invalid_json', 'oversize'])
def test_invalid_or_refused_output_is_not_saved(monkeypatch, kind):
    data = response()
    if kind == 'refusal':
        data['output'][0]['content'] = [{'type': 'refusal', 'refusal': 'no'}]
    elif kind == 'incomplete':
        data['status'] = 'incomplete'
    else:
        data['output'][0]['content'][0]['text'] = 'not-json' if kind == 'invalid_json' else 'a' * 100_000
    sdk(monkeypatch, lambda request: httpx2.Response(200, json=data))
    with pytest.raises(PlotError):
        openai_explanation.CloudExplanation().fetch({'response_id': 'resp_explain'})


@pytest.mark.parametrize('status', [401, 403, 404, 429, 500])
def test_errors_are_sanitized_and_never_auto_retried(monkeypatch, status):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx2.Response(status, json={'error': {'message': 'test-secret private provider body'}})
    sdk(monkeypatch, handler)
    with pytest.raises(PlotError) as exc:
        openai_explanation.CloudExplanation().start({})
    assert 'test-secret' not in str(exc.value) and 'private' not in str(exc.value)
    assert len(calls) == 1


def test_submit_timeout_is_uncertain(monkeypatch):
    def handler(request):
        raise httpx2.ReadTimeout('private', request=request)
    sdk(monkeypatch, handler)
    with pytest.raises(PlotError) as exc:
        openai_explanation.CloudExplanation().start({})
    assert exc.value.uncertain
