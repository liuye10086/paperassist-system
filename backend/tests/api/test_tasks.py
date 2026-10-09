"""Only authenticated task views and bounded event reads are public."""
import pytest
from fastapi.testclient import TestClient

from app.core.errors import PUBLIC_CODES
from app.core.exceptions import StorageError
from app.main import app
from tests.api.test_task_request_id import assert_request_id
from tests.helpers.auth import login_test_client


@pytest.fixture
def client():
    with TestClient(app) as instance:
        yield login_test_client(instance)


@pytest.mark.parametrize('suffix', ['', '/events'])
def test_missing_task_uses_safe_task_error(client, suffix):
    response = client.get('/api/v1/tasks/missing' + suffix)
    assert response.status_code == 404
    assert response.json()['detail']['code'] == 'task_not_found'
    assert response.json()['detail']['params'] == {}
    assert_request_id(response)


@pytest.mark.parametrize('name,value', [
    ('after', '-1'), ('after', '1.0'), ('after', '1e2'), ('after', '+1'),
    ('after', ' 1'), ('after', '１'), ('after', ''), ('after', '2147483648'),
    ('limit', '0'), ('limit', '101'), ('limit', '1.0'), ('limit', '1e2'),
    ('limit', '-1'), ('limit', ' 1'), ('limit', '１'), ('limit', ''),
])
def test_event_query_rejects_non_ascii_decimal_or_out_of_bounds(client, name, value):
    response = client.get('/api/v1/tasks/missing/events', params={name: value})
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'invalid_request'
    assert_request_id(response)


def test_unified_task_codes_are_public():
    assert {
        'task_not_found', 'task_idempotency_conflict', 'task_revision_conflict',
        'task_transition_invalid', 'task_input_invalid', 'task_source_conflict',
    } <= PUBLIC_CODES


def test_only_versioned_recovery_is_public_task_mutation_and_no_generic_collection_exists():
    task_paths = {path: item for path, item in app.openapi()['paths'].items()
                  if path == '/api/v1/tasks' or path.startswith('/api/v1/tasks/')}
    assert set(task_paths) == {'/api/v1/tasks/{task_id}', '/api/v1/tasks/{task_id}/events',
                               '/api/v1/tasks/{task_id}/retry', '/api/v1/tasks/{task_id}/model-usage',
                               '/api/v1/tasks/{task_id}/workspace', '/api/v1/tasks/{task_id}/resume'}
    assert set(task_paths['/api/v1/tasks/{task_id}/retry']) == {'post'}
    assert set(task_paths['/api/v1/tasks/{task_id}/resume']) == {'post'}
    assert all(set(task_paths[path]) == {'get'} for path in ('/api/v1/tasks/{task_id}',
        '/api/v1/tasks/{task_id}/events', '/api/v1/tasks/{task_id}/model-usage', '/api/v1/tasks/{task_id}/workspace'))


def test_task_response_projects_public_fields_and_scopes_store_to_authenticated_user(client, monkeypatch):
    from app.api import tasks

    expected = {
        'id': 'task-safe', 'origin': 'unified', 'project_id': 'project-safe', 'task_type': 'boxplot',
        'status': 'queued', 'phase': 'parse', 'display_status': 'queued',
        'revision': 1, 'current_attempt': 0, 'retry_count': 0, 'reason_code': None,
        'created_at': '2026-10-08T01:00:00Z', 'updated_at': '2026-10-08T01:00:00Z',
        'input_version': {'setup_revision': 3, 'output_language': 'zh-CN'},
        'result_report_id': None, 'result_explanation_id': None, 'result_figure_id': None, 'error_code': None,
    }
    store_users = []
    store_type = tasks.TaskStore

    def scoped_store(user_id):
        store_users.append(user_id)
        return store_type(user_id)

    def read_task(self, task_id):
        assert task_id == expected['id']
        return {**expected, 'user_id': 'private-user', 'input_snapshot': {'secret': 'private-marker'},
                'input_digest': 'private-digest', 'idempotency_key': 'private-key',
                'lease_owner': 'private-worker', 'server_path': 'C:/private/research.xlsx',
                'figure_candidate': {'private_path': 'C:/private/plot.png'},
                'provider_state': {'container_id': 'private-container'}}

    monkeypatch.setattr(tasks, 'TaskStore', scoped_store)
    monkeypatch.setattr(store_type, 'get', read_task)
    user = client.get('/api/v1/auth/me').json()['user']
    response = client.get('/api/v1/tasks/task-safe', headers={'X-Request-ID': 'untrusted-client-marker'})
    assert response.status_code == 200, response.text
    assert response.json() == expected
    assert store_users == [user['id']]
    assert_request_id(response)
    assert 'private-' not in response.text
    assert 'untrusted-client-marker' not in response.text


@pytest.mark.parametrize('params,expected_after,expected_limit', [
    ({}, 0, 50), ({'after': '0', 'limit': '1'}, 0, 1),
    ({'after': '2147483647', 'limit': '100'}, 2_147_483_647, 100),
    ({'after': '001', 'limit': '050'}, 1, 50),
])
def test_events_parse_valid_raw_query_and_project_event_fields(client, monkeypatch, params, expected_after, expected_limit):
    from app.adapters.task_store import TaskStore

    event = {'seq': 2, 'task_revision': 2, 'event_type': 'started', 'status': 'running',
             'phase': 'parse', 'reason_code': None, 'created_at': '2026-10-08T01:00:00Z',
             'error_code': None, 'error_category': None, 'retry_reason': None,
             'retry_count': None, 'retry_delay_seconds': None}

    def read_events(self, task_id, *, after, limit):
        assert (task_id, after, limit) == ('task-safe', expected_after, expected_limit)
        return {'task_id': task_id, 'items': [{**event, 'private_input': 'private-marker'}],
                'next_cursor': 2, 'has_more': True, 'private_metadata': 'private-marker'}

    monkeypatch.setattr(TaskStore, 'events', read_events)
    response = client.get('/api/v1/tasks/task-safe/events', params=params)
    assert response.status_code == 200, response.text
    assert response.json() == {'task_id': 'task-safe', 'items': [event], 'next_cursor': 2, 'has_more': True}
    assert_request_id(response)


@pytest.mark.parametrize('method,suffix', [('get', ''), ('events', '/events')])
def test_storage_conflicts_keep_safe_error_contract_and_request_id(client, monkeypatch, method, suffix):
    from app.adapters.task_store import TaskStore

    def fail_read(self, task_id, **kwargs):
        raise StorageError('task_revision_conflict', '任务状态已变化，请读取最新状态后重试。', 409,
                           params={'private_input': 'private-marker'})

    monkeypatch.setattr(TaskStore, method, fail_read)
    response = client.get('/api/v1/tasks/task-safe' + suffix)
    assert response.status_code == 409
    assert response.json()['detail'] == {
        'code': 'task_revision_conflict', 'message': '任务状态已变化，请读取最新状态后重试。',
        'params': {}, 'details': {}, 'request_id': response.headers.get('X-Request-ID'),
    }
    assert_request_id(response)


def test_unexpected_task_read_error_has_safe_body_and_request_id(client, monkeypatch, caplog):
    from app.adapters.task_store import TaskStore

    def fail_read(self, task_id):
        raise RuntimeError('private-provider-body private-research-path private-credential')

    monkeypatch.setattr(TaskStore, 'get', fail_read)
    response = client.get('/api/v1/tasks/task-safe')
    assert response.status_code == 500
    assert response.json()['detail']['code'] == 'internal_error'
    assert 'private-' not in response.text
    assert 'private-' not in caplog.text
    assert_request_id(response)
