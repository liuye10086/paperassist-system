"""Read-only usage routes preserve ownership, strict paging and safe projection."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.api.test_task_request_id import assert_request_id
from tests.helpers.auth import login_test_client
from tests.integration.test_model_usage import context, configure, request  # noqa: F401


@pytest.fixture
def client():
    with TestClient(app) as instance:
        yield login_test_client(instance)


@pytest.mark.parametrize('scope', ['projects', 'tasks'])
def test_anonymous_usage_is_traced_and_requires_authentication(scope):
    with TestClient(app) as client:
        response = client.get(f'/api/v1/{scope}/missing/model-usage')
    assert response.status_code == 401
    assert_request_id(response)


@pytest.mark.parametrize('scope,code', [('projects', 'project_not_found'), ('tasks', 'task_not_found')])
def test_missing_usage_resource_is_hidden(client, scope, code):
    response = client.get(f'/api/v1/{scope}/missing/model-usage')
    assert response.status_code == 404
    assert response.json()['detail']['code'] == code
    assert_request_id(response)


@pytest.mark.parametrize('scope', ['projects', 'tasks'])
@pytest.mark.parametrize('name,value', [('page', '0'), ('page', '-1'), ('page', '+1'), ('page', '1.0'),
    ('page', '1e2'), ('page', ' 1'), ('page', '１'), ('page', ''), ('page', '2147483648'),
    ('page_size', '0'), ('page_size', '51'), ('page_size', '1.0'), ('page_size', '１')])
def test_usage_paging_is_strict(client, scope, name, value):
    response = client.get(f'/api/v1/{scope}/missing/model-usage', params={name: value})
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'invalid_request'
    assert_request_id(response)


@pytest.mark.parametrize('scope,method', [('projects', 'project_usage'), ('tasks', 'task_usage')])
def test_usage_is_scoped_to_authenticated_user_and_projects_sensitive_fields(client, monkeypatch, scope, method):
    from app.api import model_usage

    budget = {'scope_type': 'user', 'limit_micro_usd': None, 'revision': 0, 'estimated_micro_usd': 0,
              'reserved_micro_usd': 500, 'available_micro_usd': None, 'exceeded': False}
    item = {'id': 'call-safe', 'task_type': 'explanation', 'model': 'test-model', 'status': 'submission_unknown',
            'provider_status': None, 'usage_status': 'pending', 'estimated_cost_micro_usd': None,
            'created_at': '2026-10-08T01:00:00Z', 'updated_at': '2026-10-08T01:00:00Z'}
    expected = {'currency': 'USD', 'period': 'cumulative', 'enforcement_scope': 'unified_only',
        'user_budget': budget, 'project_budget': {**budget, 'scope_type': 'project'},
        'estimated_micro_usd': 0, 'reserved_micro_usd': 500, 'pending_count': 1,
        'items': [item], 'total': 1, 'page': 1, 'page_size': 10}
    if scope == 'tasks':
        expected['task_budget'] = {**budget, 'scope_type': 'task'}
    user_id = client.get('/api/v1/auth/me').json()['user']['id']
    service_type = model_usage.ModelUsageService
    observed = []

    def service(user):
        observed.append(user)
        return service_type(user)

    def read(self, resource_id, *, page, page_size):
        assert (resource_id, page, page_size) == ('safe', 1, 10)
        return {**expected, 'policy_snapshot': {'secret': 'private-marker'},
                'items': [{**item, 'input_digest': 'private-digest', 'provider_response_id': 'private-response',
                    'provider_request_id': 'private-request', 'error_code': 'private-error',
                    'server_path': 'C:/private/research.xlsx'}]}

    monkeypatch.setattr(service_type, method, read)
    monkeypatch.setattr(model_usage, 'ModelUsageService', service)
    response = client.get(f'/api/v1/{scope}/safe/model-usage', headers={'X-Request-ID': 'client-marker'})
    assert response.status_code == 200, response.text
    assert response.json() == expected
    assert observed == [user_id]
    assert 'private-' not in response.text
    assert_request_id(response)


def test_usage_has_only_get_routes():
    paths = {path: operations for path, operations in app.openapi()['paths'].items() if path.endswith('/model-usage')}
    assert set(paths) == {'/api/v1/projects/{project_id}/model-usage', '/api/v1/tasks/{task_id}/model-usage'}
    assert all(set(operations) == {'get'} for operations in paths.values())


def test_safe_usage_errors_and_unexpected_errors_are_traced(client, monkeypatch):
    from app.api.model_usage import ModelUsageService
    from app.core.exceptions import StorageError

    def conflict(self, resource_id, **kwargs):
        raise StorageError('model_budget_missing', '尚未配置预算。', 409, params={'secret': 'private-marker'})

    monkeypatch.setattr(ModelUsageService, 'project_usage', conflict)
    response = client.get('/api/v1/projects/safe/model-usage')
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'model_budget_missing'
    assert response.json()['detail']['params'] == {}
    assert_request_id(response)

    def broken(self, resource_id, **kwargs):
        raise RuntimeError('private-credential private-provider-body')

    monkeypatch.setattr(ModelUsageService, 'project_usage', broken)
    response = client.get('/api/v1/projects/safe/model-usage')
    assert response.status_code == 500
    assert response.json()['detail']['code'] == 'internal_error'
    assert 'private-' not in response.text
    assert_request_id(response)


@pytest.mark.parametrize('scope', ['projects', 'tasks'])
def test_real_usage_records_have_public_dates_negative_available_and_no_side_effects(context, scope):
    from app.db.database import database_connection

    service = configure(context)
    saved = service.reserve_call(request(context[3]))
    service.begin_submission(saved['id'])
    service.record_response(saved['id'], event_key='reply', response_id='private-response', request_id='private-request',
        model='test-model', status='completed', usage={'input_tokens': 200, 'output_tokens': 10,
            'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0}})
    with TestClient(app) as client:
        client.headers.update({'X-PaperAssist-Client': 'web', 'Origin': 'http://testserver'})
        login = client.post('/api/v1/auth/login', json={'email': 'model-test@local.test', 'password': 'safe-test-password-2026'})
        assert login.status_code == 200
        key = context[2] if scope == 'projects' else context[3]
        with database_connection() as db:
            before = {table: db.execute(f'SELECT count(*) AS n FROM {table}').fetchone()['n']
                      for table in ('model_calls', 'usage_events', 'budget_reservations', 'task_events')}
        response = client.get(f'/api/v1/{scope}/{key}/model-usage')
        assert response.status_code == 200, response.text
        assert response.json()['project_budget']['available_micro_usd'] == -100
        assert response.json()['project_budget']['exceeded'] is True
        assert response.json()['estimated_micro_usd'] == 220
        assert response.json()['items'][0]['estimated_cost_micro_usd'] == 220
        assert isinstance(response.json()['items'][0]['created_at'], str)
        assert 'private-' not in response.text
        assert_request_id(response)
        with database_connection() as db:
            after = {table: db.execute(f'SELECT count(*) AS n FROM {table}').fetchone()['n'] for table in before}
        assert after == before


@pytest.mark.parametrize('scope,code', [('projects', 'project_not_found'), ('tasks', 'task_not_found')])
def test_other_owner_cannot_read_existing_usage(client, context, scope, code):
    key = context[2] if scope == 'projects' else context[3]
    response = client.get(f'/api/v1/{scope}/{key}/model-usage')
    assert response.status_code == 404
    assert response.json()['detail']['code'] == code
    assert_request_id(response)
