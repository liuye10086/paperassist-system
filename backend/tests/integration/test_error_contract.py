from app.core.paths import BACKEND_ROOT, PROJECT_ROOT
"""Stable public errors, safe translation parameters and legacy compatibility."""
import ast
import json
from pathlib import Path
import re

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.adapters.storage import ProjectStore
from tests.api.test_excel import client  # noqa: F401


def assert_error(response, status, code, params=None):
    assert response.status_code == status, response.text
    detail = response.json()['detail']
    assert set(detail) == {'code', 'message', 'params'}
    assert detail['code'] == code
    assert isinstance(detail['message'], str) and detail['message']
    assert detail['params'] == (params or {})
    assert response.headers['cache-control'] == 'no-store'


def test_frontend_catalog_covers_public_codes():
    from app.core.errors import PUBLIC_CODES
    root = PROJECT_ROOT
    path = root / 'frontend/src/shared/i18n/errorMessages.ts'
    assert path.exists(), 'The bilingual error catalog is missing.'
    catalog = path.read_text(encoding='utf-8')
    codes = {'invalid_request', 'internal_error', 'not_found', 'method_not_allowed',
             'openai_not_found', 'openai_request_failed', 'project_language_invalid', 'ai_configured'}
    codes.update('task_' + state for state in ('submitting', 'running', 'completed', 'uncertain', 'failed', 'unknown'))
    for module in (root / 'backend/app').rglob('*.py'):
        for node in ast.walk(ast.parse(module.read_text(encoding='utf-8-sig'))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in {'fail', 'StorageError', 'PlotError'} and node.args
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                codes.add(node.args[0].value)
    entries = set(re.findall(r'^  ([a-z][a-z0-9_]+): \{', catalog, re.MULTILINE))
    assert codes <= entries, f'Missing translations: {sorted(codes - entries)}'
    assert codes <= PUBLIC_CODES, f'Codes rejected by the public envelope: {sorted(codes - PUBLIC_CODES)}'
    assert PUBLIC_CODES <= entries


def test_unauthenticated_and_origin_errors_have_shared_contract():
    with TestClient(app) as api:
        assert_error(api.get('/api/v1/projects'), 401, 'authentication_required')
        assert_error(api.post('/api/v1/auth/login', json={}), 403, 'csrf_invalid')


@pytest.mark.parametrize('method,url,body,status,code', [
    ('post', '/api/v1/projects', {'name': 'private-marker'}, 422, 'invalid_request'),
    ('get', '/api/v1/projects/missing', None, 404, 'project_not_found'),
    ('get', '/api/v1/projects?page=private-marker', None, 422, 'invalid_request'),
    ('get', '/api/v1/not-a-route', None, 404, 'not_found'),
    ('put', '/api/v1/projects', {}, 405, 'method_not_allowed'),
    ('post', '/api/v1/excel/preview', None, 422, 'missing_file'),
])
def test_validation_resource_framework_and_upload_errors(client, method, url, body, status, code):
    response = client.request(method, url, json=body)
    assert_error(response, status, code)
    assert 'private-marker' not in response.text
    if status == 405:
        assert response.headers.get('allow')


def test_auth_validation_and_rate_limit_headers(client, monkeypatch):
    from app.auth import routes
    from app.core.exceptions import StorageError
    secret = 'private-password-marker' * 20
    invalid = client.post('/api/v1/auth/login', json={'email': secret, 'password': secret})
    assert_error(invalid, 422, 'invalid_request')
    assert secret not in invalid.text

    def limited(*args):
        raise StorageError('login_rate_limited', '登录尝试过多，请稍后重试。', 429)
    monkeypatch.setattr(routes, 'authenticate', limited)
    result = client.post('/api/v1/auth/login', json={'email': 'test@local.invalid', 'password': 'dummy'})
    assert_error(result, 429, 'login_rate_limited')
    assert result.headers['retry-after'] == '900'


@pytest.mark.parametrize('error', [RuntimeError('private-runtime-marker'), ValueError('private-value-marker')])
def test_unexpected_business_errors_are_safe_internal_errors(client, monkeypatch, error):
    def broken(self):
        raise error
    monkeypatch.setattr(ProjectStore, 'projects', broken)
    with TestClient(app, raise_server_exceptions=False, cookies=client.cookies, headers=client.headers) as api:
        response = api.get('/api/v1/projects')
    assert_error(response, 500, 'internal_error')
    assert 'private-' not in response.text


def test_unexpected_api_exception_does_not_escape_to_server_logging(client, monkeypatch, caplog):
    def broken(self):
        raise RuntimeError('private-exception-marker')
    monkeypatch.setattr(ProjectStore, 'projects', broken)
    # The default TestClient rethrows errors escaping the ASGI app, just as a
    # server could print their traceback. A safe handler must consume them.
    response = client.get('/api/v1/projects')
    assert_error(response, 500, 'internal_error')
    assert 'private-exception-marker' not in caplog.text
    assert 'RuntimeError' in caplog.text


@pytest.mark.parametrize('status,code', [(400, 'invalid_request'), (403, 'permission_denied'), (500, 'internal_error')])
def test_unknown_http_exception_detail_is_not_exposed(client, monkeypatch, status, code):
    def broken(self):
        raise HTTPException(status, detail={'message': 'private-provider-marker', 'input': 'private-input-marker'})
    monkeypatch.setattr(ProjectStore, 'projects', broken)
    response = client.get('/api/v1/projects')
    assert_error(response, status, code)
    assert 'private-' not in response.text


def test_upload_limit_params_survive_both_upload_paths(client, monkeypatch):
    monkeypatch.setenv('EXCEL_MAX_UPLOAD_BYTES', '3')
    direct = client.post('/api/v1/excel/preview', files={'file': ('test.xlsx', b'1234')})
    assert_error(direct, 413, 'file_too_large', {'max_bytes': 3})
    streamed = client.post('/api/v1/excel/preview', content=b'x' * (64 * 1024 + 4))
    assert_error(streamed, 413, 'file_too_large', {'max_bytes': 3})


def test_error_params_are_code_specific_and_never_echo_arbitrary_values():
    from app.core.errors import error_detail
    result = error_detail('numeric_precision', 'safe', {
        'column': 'AB', 'row': 23, 'password': 'private-marker', 'body': {'password': 'secret'},
    })
    assert result == {'code': 'numeric_precision', 'message': 'safe', 'params': {'column': 'AB', 'row': 23}}
    assert error_detail('numeric_precision', 'safe', {'column': 'private-marker', 'row': True})['params'] == {}
    assert error_detail('file_too_large', 'safe', {'max_bytes': 'private-marker'})['params'] == {}
    unknown = error_detail('private-code-marker', 'private-message-marker', {'secret': 'private-value-marker'})
    assert unknown['code'] == 'internal_error'
    assert 'private-' not in json.dumps(unknown)


def test_legacy_failed_file_is_read_without_rewriting_error_json(client):
    from app.db.database import database_connection
    project = client.post('/api/v1/projects', json={'name': 'test', 'research_topic': 'test', 'project_type': 'sci'}).json()
    uploaded = client.post(f'/api/v1/projects/{project["id"]}/files', files={'file': ('test.xlsx', b'broken')}).json()
    file_id = uploaded['file']['id']
    legacy = json.dumps({'code': 'invalid_workbook', 'message': '旧错误记录'}, ensure_ascii=False)
    with database_connection(write=True) as db:
        db.execute('UPDATE files SET error_json = %s WHERE id = %s', (legacy, file_id))
    root = f'/api/v1/projects/{project["id"]}/files'
    assert client.get(root).json()[0]['error']['params'] == {}
    assert_error(client.get(root + f'/{file_id}/preview'), 422, 'invalid_workbook')
    with database_connection() as db:
        assert db.execute('SELECT error_json FROM files WHERE id = %s', (file_id,)).fetchone()['error_json'] == legacy


def test_legacy_job_translation_is_a_read_only_projection():
    from app.domain.boxplot import public_job
    original = {'id': 'old', 'status': 'failed', 'message': 'private legacy text', 'response_id': 'old-response'}
    snapshot = json.dumps(original)
    result = public_job(original)
    assert result['message_code'] == 'task_failed'
    assert result['message_params'] == {}
    assert result['message'] == original['message']
    assert json.dumps(original) == snapshot


def test_ai_configuration_has_localizable_message_without_credentials(client):
    result = client.get('/api/v1/ai/config').json()
    assert result['message_code'] == 'openai_not_configured'
    assert result['message_params'] == {}
