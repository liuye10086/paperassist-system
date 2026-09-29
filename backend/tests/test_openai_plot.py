from io import BytesIO
import json
from types import SimpleNamespace

import httpx2
import pytest
from openai import OpenAI
from PIL import Image

from app import openai_plot


def png():
    buffer = BytesIO()
    Image.new('RGB', (1600, 1000), 'white').save(buffer, format='PNG')
    return buffer.getvalue()


def sdk(monkeypatch, handler):
    monkeypatch.setenv('OPENAI_API_KEY', 'test-secret-never-real')
    monkeypatch.setenv('OPENAI_MODEL', 'test-model')
    real = OpenAI
    def factory(**kwargs):
        assert kwargs['base_url'] == 'https://api.openai.com/v1'
        assert kwargs['max_retries'] == 0
        return real(**kwargs, http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    monkeypatch.setattr(openai_plot, 'OpenAI', factory)


def completed():
    return {'id': 'resp_1', 'object': 'response', 'created_at': 1, 'model': 'test-model', 'status': 'completed',
        'output': [{'id': 'ci_1', 'type': 'code_interpreter_call', 'status': 'completed', 'container_id': 'cntr_1',
                    'code': 'print("real execution record")', 'outputs': []},
            {'id': 'msg_1', 'type': 'message', 'role': 'assistant', 'status': 'completed', 'content': [
                {'type': 'output_text', 'text': 'Files', 'annotations': [
                    {'type': 'container_file_citation', 'container_id': 'cntr_1', 'file_id': 'file_png',
                     'filename': '/mnt/data/boxplot.png', 'start_index': 0, 'end_index': 1},
                    {'type': 'container_file_citation', 'container_id': 'cntr_1', 'file_id': 'file_json',
                     'filename': '/mnt/data/result.json', 'start_index': 0, 'end_index': 1}]}]}],
        'usage': {'input_tokens': 100, 'output_tokens': 200, 'total_tokens': 300}}


def test_sdk_submits_only_to_official_container_and_background_response(monkeypatch):
    calls, container_saved = [], []
    def handler(request):
        calls.append(request)
        path = request.url.path
        if path == '/v1/containers':
            body = json.loads(request.content)
            assert body['memory_limit'] == '1g'
            return httpx2.Response(200, json={'id': 'cntr_1', 'created_at': 1, 'name': 'test', 'object': 'container', 'status': 'running'})
        if path == '/v1/containers/cntr_1/files':
            assert b'data.json' in request.content and b'"values": [1, 2, 3]' in request.content
            return httpx2.Response(200, json={'id': 'file_1', 'container_id': 'cntr_1', 'object': 'container.file', 'created_at': 1, 'bytes': 30, 'path': '/mnt/data/data.json', 'source': 'user'})
        if path == '/v1/responses':
            body = json.loads(request.content)
            assert body['background'] and body['store']
            assert body['model'] == 'test-model'
            assert body['tools'] == [{'type': 'code_interpreter', 'container': 'cntr_1'}]
            assert 'code_interpreter_call.outputs' in body['include']
            assert body['tool_choice'] == {'type': 'code_interpreter'}
            return httpx2.Response(200, json={**completed(), 'status': 'queued', 'output': []})
        raise AssertionError(path)
    sdk(monkeypatch, handler)
    assert openai_plot.CloudPlot().start({'values': [1, 2, 3]}, 'task', container_saved.append) == 'resp_1'
    assert container_saved == ['cntr_1'] and len(calls) == 3


def test_sdk_retrieves_executed_code_and_downloads_cited_files(monkeypatch):
    routes = []
    def handler(request):
        routes.append(request.url.path)
        if request.url.path == '/v1/responses/resp_1':
            return httpx2.Response(200, json=completed())
        if request.url.path.endswith('/file_json/content'):
            return httpx2.Response(200, content=b'{"value":1,"environment":{"font":"Noto"}}')
        if request.url.path.endswith('/file_png/content'):
            return httpx2.Response(200, content=png())
        raise AssertionError(str(request.url))
    sdk(monkeypatch, handler)
    result = openai_plot.CloudPlot().fetch({'response_id': 'resp_1', 'container_id': 'cntr_1', 'model': 'test-model'})
    assert result['manifest']['value'] == 1 and result['png'].startswith(b'\x89PNG')
    assert result['provenance']['code'] == ['print("real execution record")']
    assert result['provenance']['usage']['total_tokens'] == 300
    assert routes == ['/v1/responses/resp_1', '/v1/containers/cntr_1/files/file_json/content', '/v1/containers/cntr_1/files/file_png/content']


@pytest.mark.parametrize('status', [401, 403, 404, 429, 500])
def test_provider_errors_are_sanitized_and_never_automatically_retried(monkeypatch, status):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx2.Response(status, json={'error': {'message': 'SECRET must not reach UI', 'type': 'test', 'code': 'test'}})
    sdk(monkeypatch, handler)
    with pytest.raises(openai_plot.PlotError) as error:
        openai_plot.CloudPlot().start({}, 'task', lambda _: None)
    assert 'SECRET' not in error.value.message and len(calls) == 1


def test_timeout_after_response_submission_is_uncertain(monkeypatch):
    def handler(request):
        if request.url.path == '/v1/containers':
            return httpx2.Response(200, json={'id': 'cntr_1'})
        if request.url.path.endswith('/files'):
            return httpx2.Response(200, json={'id': 'file_1'})
        raise httpx2.ReadTimeout('simulated network timeout', request=request)
    sdk(monkeypatch, handler)
    with pytest.raises(openai_plot.PlotError) as error:
        openai_plot.CloudPlot().start({}, 'task', lambda _: None)
    assert error.value.uncertain


@pytest.mark.parametrize('change', ['no_execution', 'wrong_container', 'missing_png', 'invalid_json', 'incomplete'])
def test_does_not_accept_unexecuted_or_incomplete_cloud_output(monkeypatch, change):
    response = completed()
    if change == 'no_execution':
        response['output'] = response['output'][1:]
    elif change == 'wrong_container':
        response['output'][0]['container_id'] = 'cntr_unrelated'
    elif change == 'missing_png':
        response['output'][1]['content'][0]['annotations'].pop(0)
    elif change == 'incomplete':
        response['status'] = 'incomplete'
    def handler(request):
        if request.url.path.endswith('resp_1'):
            return httpx2.Response(200, json=response)
        return httpx2.Response(200, content=b'not JSON')
    sdk(monkeypatch, handler)
    with pytest.raises(openai_plot.PlotError):
        openai_plot.CloudPlot().fetch({'response_id': 'resp_1', 'container_id': 'cntr_1', 'model': 'test-model'})


@pytest.mark.parametrize('bad', [True, '2', float('nan'), float('inf'), 3.0, None, 10**400])
def test_validator_rejects_wrong_types_nonfinite_and_wrong_numeric_values(bad):
    with pytest.raises(openai_plot.PlotError, match='核对'):
        openai_plot.validate_output({'manifest': {'mean': bad}, 'png': png()}, {'mean': 2.0})


def test_validator_accepts_roundoff_but_checks_provenance_labels_and_png():
    expected = {'id': 'run-1', 'n': 3, 'mean': 2.0, 'std': None, 'labels': ['甲', '乙']}
    output = {'manifest': {**expected, 'mean': 2.000000000001}, 'png': png()}
    openai_plot.validate_output(output, expected)
    for changed in [{'id': 'other'}, {'n': 3.2}, {'labels': ['乙', '甲']}, {'std': 0}]:
        with pytest.raises(openai_plot.PlotError):
            openai_plot.validate_output({'manifest': {**expected, **changed}, 'png': png()}, expected)
    with pytest.raises(openai_plot.PlotError, match='图片'):
        openai_plot.validate_output({'manifest': expected, 'png': b'not a PNG'}, expected)
