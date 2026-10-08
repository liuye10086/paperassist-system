"""Task request tracing must cover errors without changing older API envelopes."""
import asyncio
import json
import re

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.helpers.auth import login_test_client


def assert_request_id(response):
    request_id = response.headers.get('X-Request-ID')
    assert request_id is not None
    assert re.fullmatch(r'[0-9a-f]{32}', request_id)
    if response.status_code >= 400:
        assert response.json()['detail']['request_id'] == request_id
        assert response.json()['detail']['details'] == {}
    return request_id


def test_word_submission_errors_are_traced_but_old_reads_and_downloads_are_unchanged():
    endpoint = '/api/v1/projects/p/files/f/analysis-runs/r/report'
    with TestClient(app) as client:
        submission = client.post(endpoint, json={})
        read = client.get(endpoint)
        download = client.get(endpoint + '/report-id/download')
    assert submission.status_code == read.status_code == download.status_code == 401
    assert_request_id(submission)
    for response in (read, download):
        assert 'X-Request-ID' not in response.headers
        assert set(response.json()['detail']) == {'code', 'message', 'params'}


@pytest.mark.parametrize('path', ['/api/v1/tasks', '/api/v1/tasks/missing', '/api/v1/tasks/missing/events'])
def test_unauthenticated_task_errors_have_server_generated_request_id(path):
    with TestClient(app) as client:
        first = client.get(path, headers={'X-Request-ID': 'untrusted-client-marker'})
        second = client.get(path)
    assert first.status_code == second.status_code == 401
    assert first.json()['detail']['code'] == 'authentication_required'
    assert assert_request_id(first) != assert_request_id(second)
    assert 'untrusted-client-marker' not in first.text


def test_authenticated_missing_task_path_has_request_id():
    with TestClient(app) as client:
        login_test_client(client)
        response = client.get('/api/v1/tasks/missing/no-such-route')
    assert response.status_code == 404
    assert response.json()['detail']['code'] == 'not_found'
    assert_request_id(response)


def test_authentication_failure_remains_sanitized_with_request_id(monkeypatch):
    def fail_session(token):
        raise RuntimeError('secret-provider-body C:/private/research.xlsx')

    monkeypatch.setattr('app.auth.middleware.resolve_session', fail_session)
    with TestClient(app) as client:
        client.cookies.set('paperassist_session', 'session-token')
        response = client.get('/api/v1/tasks/missing')
    assert response.status_code == 500
    assert response.json()['detail']['code'] == 'internal_error'
    assert 'secret-provider-body' not in response.text
    assert 'research.xlsx' not in response.text
    assert_request_id(response)


@pytest.mark.parametrize('path', ['/api/v1/projects', '/api/v1/tasksgiving', '/api/v1/tasks-other'])
def test_old_unauthenticated_error_envelope_is_exactly_unchanged(path):
    with TestClient(app) as client:
        response = client.get(path, headers={'X-Request-ID': 'untrusted-client-marker'})
    assert response.status_code == 401
    assert response.json() == {'detail': {
        'code': 'authentication_required', 'message': '请登录后继续。', 'params': {},
    }}
    assert 'X-Request-ID' not in response.headers


def test_old_authorized_validation_error_envelope_is_exactly_unchanged():
    with TestClient(app) as client:
        login_test_client(client)
        response = client.post('/api/v1/projects', json={})
    assert response.status_code == 422
    assert response.json() == {'detail': {
        'code': 'invalid_request', 'message': '请求格式无效，请检查填写的内容后重试。', 'params': {},
    }}
    assert 'X-Request-ID' not in response.headers


@pytest.mark.parametrize('path,status,headers', [
    ('/api/v1/tasks/one', 200, [(b'content-type', b'application/json')]),
    ('/api/v1/projects/file', 404, [(b'content-type', b'application/json')]),
    ('/api/v1/tasks/one', 404, [(b'content-type', b'application/octet-stream')]),
    ('/api/v1/tasks/one', 404, [(b'content-type', b'application/json'), (b'content-disposition', b'attachment')]),
])
def test_success_files_and_old_paths_are_forwarded_without_buffering(path, status, headers):
    from app.core.request_id import RequestIdMiddleware

    sent = []

    async def send(message):
        sent.append(message)

    async def downstream(scope, receive, send):
        await send({'type': 'http.response.start', 'status': status, 'headers': headers})
        assert len(sent) == 1
        await send({'type': 'http.response.body', 'body': b'first', 'more_body': True})
        assert len(sent) == 2
        await send({'type': 'http.response.body', 'body': b'second', 'more_body': False})

    asyncio.run(RequestIdMiddleware(downstream)({'type': 'http', 'path': path}, None, send))
    assert [message.get('body') for message in sent[1:]] == [b'first', b'second']
    assert (b'x-request-id' in dict(sent[0]['headers'])) == path.startswith('/api/v1/tasks/')


@pytest.mark.parametrize('chunks', [[b'{"detail":', b'invalid}'], [b'x' * 65536, b'secret-over-limit']])
def test_malformed_or_oversized_task_json_errors_are_bounded_and_sanitized(chunks):
    from app.core.request_id import RequestIdMiddleware

    sent = []

    async def send(message):
        sent.append(message)

    async def downstream(scope, receive, send):
        await send({'type': 'http.response.start', 'status': 503,
                    'headers': [(b'content-type', b'application/json')]})
        for index, chunk in enumerate(chunks):
            await send({'type': 'http.response.body', 'body': chunk, 'more_body': index < len(chunks) - 1})

    asyncio.run(RequestIdMiddleware(downstream)({'type': 'http', 'path': '/api/v1/tasks/one'}, None, send))
    assert len(sent) == 2
    assert sent[0]['status'] == 500
    payload = json.loads(sent[1]['body'])
    assert payload['detail']['code'] == 'internal_error'
    assert payload['detail']['details'] == {}
    assert payload['detail']['request_id'].encode('ascii') == dict(sent[0]['headers'])[b'x-request-id']
    assert int(dict(sent[0]['headers'])[b'content-length']) == len(sent[1]['body'])
    assert len(sent[1]['body']) < 1024
    assert b'secret-over-limit' not in sent[1]['body']
