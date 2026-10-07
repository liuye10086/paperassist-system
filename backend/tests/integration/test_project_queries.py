"""Owner-scoped pagination and literal search against isolated PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db.database import DatabaseConnection
from app.main import app
from app.adapters.storage import ProjectStore
from app.core.exceptions import StorageError
from tests.integration.test_project_ownership import account_client
from tests.api.test_projects import client, create_project, upload  # noqa: F401


PROJECT_FIELDS = {'id', 'name', 'research_topic', 'project_type',
                  'default_output_language', 'created_at', 'updated_at', 'file_count'}


def scoped_store(client):
    owner_id = client.get('/api/v1/auth/me').json()['user']['id']
    return ProjectStore(Path(os.environ['PAPERASSIST_DATA_DIR']), owner_id=owner_id)


def page_response(client, params):
    response = client.get('/api/v1/projects', params=params)
    assert response.status_code == 200, response.text
    result = response.json()
    assert isinstance(result, dict), 'explicit list parameters must enable the paginated object'
    assert set(result) == {'items', 'total', 'page', 'page_size'}
    for item in result['items']:
        assert set(item) == PROJECT_FIELDS
    return result


def test_legacy_array_and_each_explicit_parameter_enables_pagination(client):
    projects = [create_project(client, f'项目{i}') for i in range(3)]
    assert upload(client, projects[0]['id']).status_code == 201
    legacy = client.get('/api/v1/projects').json()
    assert isinstance(legacy, list) and len(legacy) == 3
    assert all(set(item) == PROJECT_FIELDS for item in legacy)
    for params in ({'page': 1}, {'page_size': 10}, {'q': ''}, {'type': 'sci'}):
        result = page_response(client, params)
        assert result == {'items': legacy, 'total': 3, 'page': 1, 'page_size': 10}
    result = page_response(client, {'page': 1, 'page_size': 2})
    assert len(result['items']) == 2
    assert result['total'] == 3 and result['page'] == 1 and result['page_size'] == 2
    file_counts = {item['id']: item['file_count'] for item in legacy}
    assert file_counts[projects[0]['id']] == 1
    assert scoped_store(client).query_projects()['items'] == legacy


def test_literal_name_search_normalization_and_combined_type(client):
    examples = [('Alpha研究', 'sci'), ('alpha毕业', 'thesis'), ('百分%项目', 'sci'),
                ('下划_项目', 'sci'), ('反斜\\项目', 'thesis'), ('普通项目', 'sci'),
                ("quote' OR 1=1 --", 'sci')]
    projects = {name: create_project(client, name, kind) for name, kind in examples}
    for query, names in [
        ('研究', ['Alpha研究']), (' ALPHA ', ['Alpha研究', 'alpha毕业']),
        (' \t\n ', list(projects)), ('%', ['百分%项目']), ('_', ['下划_项目']),
        ('\\', ['反斜\\项目']), ("' OR 1=1 --", ["quote' OR 1=1 --"]),
        ('治疗组', []), ('不存在', []),
    ]:
        result = page_response(client, {'q': query})
        assert {item['name'] for item in result['items']} == set(names)
        assert result['total'] == len(names)
    combined = page_response(client, {'q': ' alpha ', 'type': 'thesis'})
    assert combined['items'] == [projects['alpha毕业']] and combined['total'] == 1
    for kind in ('sci', 'thesis'):
        filtered = page_response(client, {'type': kind, 'page_size': 100})
        assert filtered['total'] == sum(project['project_type'] == kind for project in projects.values())
        assert all(item['project_type'] == kind for item in filtered['items'])


def test_order_is_stable_across_pages_and_out_of_range_keeps_total(client):
    projects = [create_project(client, f'项目{i}') for i in range(5)]
    store = scoped_store(client)
    with store.connection(write=True) as db:
        db.execute('UPDATE projects SET updated_at = %s', ('2030-01-01T00:00:00+00:00',))
        db.execute('UPDATE projects SET updated_at = %s WHERE id = %s',
                   ('2030-01-02T00:00:00+00:00', projects[0]['id']))
    expected = [projects[0]['id']] + sorted(item['id'] for item in projects[1:])
    pages = [page_response(client, {'page': page, 'page_size': 2}) for page in (1, 2, 3)]
    actual = [item['id'] for result in pages for item in result['items']]
    assert actual == expected and len(set(actual)) == 5
    assert all(result['total'] == 5 for result in pages)
    for page in (4, 1_000_000):
        assert page_response(client, {'page': page, 'page_size': 2}) == {
            'items': [], 'total': 5, 'page': page, 'page_size': 2,
        }


def test_empty_result_and_parameter_boundaries(client):
    assert page_response(client, {'page': 1, 'page_size': 1}) == {
        'items': [], 'total': 0, 'page': 1, 'page_size': 1,
    }
    assert page_response(client, {'page': 1_000_000, 'page_size': 100}) == {
        'items': [], 'total': 0, 'page': 1_000_000, 'page_size': 100,
    }
    assert page_response(client, {'q': ' ' + 'x' * 120 + ' '})['total'] == 0
    invalid = [('page', value) for value in ('', 'abc', '1.5', '0', '-1', '1000001')]
    invalid += [('page_size', value) for value in ('', 'abc', '1.5', '0', '-1', '101')]
    invalid += [('type', value) for value in ('', 'other', 'SCI', ' thesis ')]
    invalid += [('q', 'x' * 121)]
    for key, value in invalid:
        response = client.get('/api/v1/projects', params={key: value})
        assert response.status_code == 422, (key, value, response.text)


def test_persistence_boundary_rejects_invalid_parameters_safely(client):
    store = scoped_store(client)
    invalid = [{'page': value} for value in (0, -1, 1_000_001, True, 1.0, '1', None)]
    invalid += [{'page_size': value} for value in (0, -1, 101, False, 1.0, '10', None)]
    invalid += [{'q': value} for value in (None, 1, [], {}, 'private-marker' * 10)]
    invalid += [{'project_type': value} for value in ('', 'SCI', 'other', [], {}, 1)]
    for params in invalid:
        with pytest.raises(StorageError) as rejected:
            store.query_projects(**params)
        assert rejected.value.status == 422
        assert rejected.value.code == 'project_query_invalid'
        assert 'private-marker' not in rejected.value.message


@pytest.mark.parametrize('key, maximum', [('page', 1_000_000), ('page_size', 100)])
def test_http_pagination_accepts_only_decimal_integer_strings(client, key, maximum):
    for value in ('1.0', '1e0', '+1', ' 1 ', '1_0', '１', '١'):
        response = client.get('/api/v1/projects', params={key: value})
        assert response.status_code == 422, (key, value, response.text)
    for value in ('1', '0001', str(maximum)):
        result = page_response(client, {key: value})
        assert result[key] == int(value)
    operation = client.get('/openapi.json').json()['paths']['/api/v1/projects']['get']
    parameter = next(item for item in operation['parameters'] if item['name'] == key)
    integer_schema = next(item for item in parameter['schema']['anyOf'] if item['type'] == 'integer')
    assert integer_schema['minimum'] == 1 and integer_schema['maximum'] == maximum


def test_pagination_totals_and_items_are_private_for_two_users_and_admin(client):
    create_project(client, '共享搜索自己的', 'sci')
    create_project(client, '共享搜索自己的论文', 'thesis')
    for email, role in [('query-other@paperassist.local', 'user'), ('query-admin@paperassist.local', 'admin')]:
        with account_client(email, role)[0] as other:
            assert page_response(other, {'q': '共享搜索'})['total'] == 0
            own = create_project(other, '共享搜索他人的', 'sci')
            result = page_response(other, {'q': '共享搜索', 'type': 'sci'})
            assert result['items'] == [own] and result['total'] == 1
    result = page_response(client, {'q': '共享搜索', 'type': 'sci'})
    assert [item['name'] for item in result['items']] == ['共享搜索自己的']
    assert result['total'] == 1
    with TestClient(app) as anonymous:
        for params in ({}, {'page': 1}, {'q': ''}):
            assert anonymous.get('/api/v1/projects', params=params).status_code == 401


def test_count_and_items_share_repeatable_read_snapshot_during_concurrent_insert(client, monkeypatch):
    first = create_project(client, '一致搜索', 'thesis')
    store = scoped_store(client)
    counted, inserted = Event(), Event()
    original_execute = DatabaseConnection.execute
    count_connections = []
    item_connections = []

    def observe_query(db, sql, parameters=()):
        result = original_execute(db, sql, parameters)
        if sql.startswith('SELECT count(*) AS total FROM projects'):
            count_connections.append(db)
            isolation = original_execute(db, 'SHOW transaction_isolation').fetchone()
            assert isolation['transaction_isolation'] == 'repeatable read'
            counted.set()
            assert inserted.wait(10), 'concurrent synthetic insert did not complete'
        elif 'FROM projects' in sql and 'LIMIT' in sql:
            item_connections.append(db)
        return result

    monkeypatch.setattr(DatabaseConnection, 'execute', observe_query)

    def concurrent_insert():
        assert counted.wait(10), 'count query did not execute'
        try:
            return store.create_project('一致搜索新项目', '合成主题', 'thesis')
        finally:
            inserted.set()

    with ThreadPoolExecutor(max_workers=1) as executor:
        writer = executor.submit(concurrent_insert)
        try:
            result = store.query_projects(q='一致搜索', project_type='thesis')
        finally:
            counted.set()
        new_project = writer.result(timeout=10)
    assert result == {'items': [first], 'total': 1, 'page': 1, 'page_size': 10}
    assert count_connections == item_connections and len(count_connections) == 1
    subsequent = store.query_projects(q='一致搜索', project_type='thesis')
    assert subsequent['total'] == 2
    assert {item['id'] for item in subsequent['items']} == {first['id'], new_project['id']}
