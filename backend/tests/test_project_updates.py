"""Project edits preserve ownership and every previously generated artifact."""

from datetime import datetime, timedelta, timezone
from io import BytesIO
import os
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from app.database import database_connection
from app.main import app
from app.storage import ProjectStore, StorageError
from test_projects import client, create_project, upload  # noqa: F401
from test_project_ownership import account_client
from test_boxplot import cloud  # noqa: F401
from test_explanations import writer  # noqa: F401
from test_reports import report_ready, export


def project_row(project_id):
    with database_connection() as db:
        return dict(db.execute('SELECT * FROM projects WHERE id = %s', (project_id,)).fetchone())


@pytest.mark.parametrize('project_type', ['sci', 'thesis'])
@pytest.mark.parametrize('changes', [
    {'name': '  新名称  '}, {'research_topic': '  新主题  '},
    {'name': '新名称', 'research_topic': '新主题'},
    {'name': '名' * 120, 'research_topic': '题' * 500},
])
def test_patch_updates_only_supplied_fields(client, project_type, changes):
    project = create_project(client, project_type=project_type)
    assert upload(client, project['id']).status_code == 201
    url = f'/api/v1/projects/{project["id"]}'
    original = client.get(url).json()
    row = project_row(project['id'])
    response = client.patch(url, json=changes)
    assert response.status_code == 200, response.text
    updated = response.json()
    assert set(updated) == set(original)
    for field in ('name', 'research_topic'):
        assert updated[field] == changes.get(field, original[field]).strip()
    for field in ('id', 'project_type', 'created_at', 'file_count'):
        assert updated[field] == original[field]
    assert updated['updated_at'] > original['updated_at']
    assert project_row(project['id'])['owner_id'] == row['owner_id']
    assert client.get(url).json() == updated
    assert client.get('/api/v1/projects').json() == [updated]


def test_same_values_keep_timestamp_and_partial_edits_keep_other_changes(client):
    project = create_project(client)
    url = f'/api/v1/projects/{project["id"]}'
    response = client.patch(url, json={'name': f'  {project["name"]}  ', 'research_topic': project['research_topic']})
    assert response.status_code == 200
    assert response.json() == project
    first = client.patch(url, json={'name': '第一个标签的名称'}).json()
    second = client.patch(url, json={'research_topic': '第二个标签的主题'}).json()
    assert second['name'] == first['name']
    assert second['research_topic'] == '第二个标签的主题'
    last = client.patch(url, json={'name': '最后成功保存的名称'}).json()
    assert last['name'] == '最后成功保存的名称'
    assert last['research_topic'] == second['research_topic']


INVALID_UPDATES = [
    {}, None, [], 'private-marker',
    {'name': ''}, {'name': ' \t\n '}, {'name': 'x' * 121},
    {'research_topic': ''}, {'research_topic': ' '}, {'research_topic': 'x' * 501},
    {'name': None}, {'name': 42}, {'name': True}, {'name': []}, {'name': {}},
    {'research_topic': None}, {'research_topic': 42}, {'research_topic': False},
    {'research_topic': []}, {'research_topic': {}},
    {'name': 'valid', 'research_topic': None},
    {'unknown': 'private-marker'}, {'owner_id': 'private-marker'},
    {'id': 'private-marker'}, {'created_at': 'private-marker'},
    {'updated_at': 'private-marker'}, {'file_count': 4},
    {'project_type': 'thesis'}, {'project_type': 'sci'}, {'project_type': None},
    {'name': 'valid', 'project_type': 'sci', 'unknown': 'private-marker'},
]


@pytest.mark.parametrize('changes', INVALID_UPDATES)
def test_http_and_internal_store_reject_invalid_edits_without_partial_changes(client, changes):
    project = create_project(client)
    original = project_row(project['id'])
    code = 'project_type_immutable' if isinstance(changes, dict) and 'project_type' in changes else 'project_update_invalid'
    response = client.patch(f'/api/v1/projects/{project["id"]}', content='null' if changes is None else None,
                            json=changes if changes is not None else None,
                            headers={'Content-Type': 'application/json'})
    assert response.status_code == 422, response.text
    assert set(response.json()['detail']) == {'code', 'message'}
    assert response.json()['detail']['code'] == code
    assert 'private-marker' not in response.text
    internal = ProjectStore(Path(os.environ['PAPERASSIST_DATA_DIR']))
    with pytest.raises(StorageError) as rejected:
        internal.update_project(project['id'], changes)
    assert rejected.value.status == 422
    assert rejected.value.code == code
    assert project_row(project['id']) == original


def test_scoped_store_and_http_cannot_update_other_users_or_unknown_projects():
    with account_client('edit-owner@paperassist.local')[0] as owner:
        project = create_project(owner)
        original = project_row(project['id'])
        for email, role in [('edit-other@paperassist.local', 'user'), ('edit-admin@paperassist.local', 'admin')]:
            other, user = account_client(email, role)
            with other:
                for project_id in (project['id'], 'missing'):
                    response = other.patch(f'/api/v1/projects/{project_id}', json={'name': '越权更改'})
                    assert response.status_code == 404
                    assert response.json()['detail']['code'] == 'project_not_found'
                    scoped = ProjectStore(Path(os.environ['PAPERASSIST_DATA_DIR']), owner_id=user['id'])
                    with pytest.raises(StorageError) as rejected:
                        scoped.update_project(project_id, {'name': '越权更改'})
                    assert rejected.value.status == 404
                    assert rejected.value.code == 'project_not_found'
        assert project_row(project['id']) == original


def test_patch_requires_authentication_and_csrf(client):
    project = create_project(client)
    url = f'/api/v1/projects/{project["id"]}'
    with TestClient(app) as anonymous:
        assert anonymous.patch(url, json={'name': '拒绝'}).status_code == 401
    token = client.headers.pop('X-CSRF-Token')
    assert client.patch(url, json={'name': '拒绝'}).status_code == 403
    client.headers['X-CSRF-Token'] = token
    assert client.get(url).json() == project


def test_internal_update_keeps_future_timestamp_and_list_order(client):
    first = create_project(client)
    second = create_project(client, '较新的项目')
    store = ProjectStore(Path(os.environ['PAPERASSIST_DATA_DIR']))
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    with store.connection(write=True) as db:
        db.execute('UPDATE projects SET updated_at = %s WHERE id = %s', (future, first['id']))
    updated = store.update_project(first['id'], {'name': '  将来时间仍保留  '})
    assert updated['name'] == '将来时间仍保留'
    assert updated['updated_at'] == future
    assert [item['id'] for item in client.get('/api/v1/projects').json()] == [first['id'], second['id']]


def test_update_database_failure_rolls_back_project(client):
    project = create_project(client)
    original = project_row(project['id'])
    with database_connection(write=True) as db:
        db.execute("""CREATE FUNCTION reject_project_edit() RETURNS trigger LANGUAGE plpgsql
            AS $$ BEGIN RAISE EXCEPTION 'synthetic edit failure'; END $$""")
        db.execute('CREATE TRIGGER reject_project_edit BEFORE UPDATE ON projects '
                   'FOR EACH ROW EXECUTE FUNCTION reject_project_edit()')
    try:
        response = client.patch(f'/api/v1/projects/{project["id"]}', json={'name': '更改', 'research_topic': '更改'})
        assert response.status_code == 503
        assert response.json()['detail']['code'] == 'storage_unavailable'
        assert project_row(project['id']) == original
    finally:
        with database_connection(write=True) as db:
            db.execute('DROP TRIGGER reject_project_edit ON projects')
            db.execute('DROP FUNCTION reject_project_edit()')


def business_snapshot():
    # Only fixed, known business tables in the dedicated per-test schema.
    tables = ('projects', 'files', 'analysis_setups', 'analysis_runs', 'figure_jobs',
              'figures', 'explanation_jobs', 'explanations', 'reports')
    with database_connection() as db:
        return {table: sorted((dict(row) for row in db.execute(f'SELECT * FROM {table}')), key=repr)
                for table in tables}


@pytest.mark.parametrize('export_before_edit', [True, False])
def test_project_edit_preserves_artifacts_and_uses_project_at_first_report_export(client, cloud, writer, export_before_edit):
    base, file, result, figure, explanation, report_url = report_ready(client)
    project_url = base.split('/files/')[0]
    project = client.get(project_url).json()
    report = export(client, report_url, figure, explanation).json()['report'] if export_before_edit else None
    downloads = [base + '/download', base + '/analysis-runs/' + result['id'] + '/boxplot/image']
    if report:
        downloads.append(report_url + '/' + report['id'] + '/download')
    content = {url: client.get(url).content for url in downloads}
    before = business_snapshot()
    directory = Path(os.environ['PAPERASSIST_DATA_DIR'])
    assets = {str(path.relative_to(directory)): path.read_bytes() for path in directory.rglob('*') if path.is_file()}
    calls = (len(cloud.calls), len(writer.calls))
    response = client.patch(project_url, json={'name': '编辑后的独特名称', 'research_topic': '编辑后的独特主题'})
    assert response.status_code == 200
    after = business_snapshot()
    for table in before:
        if table == 'projects':
            assert [{key: value for key, value in row.items() if key not in {'name', 'research_topic', 'updated_at'}}
                    for row in after[table]] == [{key: value for key, value in row.items()
                    if key not in {'name', 'research_topic', 'updated_at'}} for row in before[table]]
        else:
            assert after[table] == before[table], table
    assert {str(path.relative_to(directory)): path.read_bytes() for path in directory.rglob('*') if path.is_file()} == assets
    for url, expected in content.items():
        assert client.get(url).content == expected
    exported = export(client, report_url, figure, explanation)
    assert exported.status_code == (200 if export_before_edit else 201)
    if report:
        assert exported.json()['report'] == report
        assert business_snapshot() == after
    report = exported.json()['report']
    download = report_url + '/' + report['id'] + '/download'
    word = client.get(download).content
    with ZipFile(BytesIO(word)) as archive:
        xml = archive.read('word/document.xml').decode()
    expected = project if export_before_edit else response.json()
    assert expected['name'] in xml and expected['research_topic'] in xml
    assert export(client, report_url, figure, explanation).json()['report'] == report
    assert client.get(download).content == word
    assert (len(cloud.calls), len(writer.calls)) == calls == (1, 1)
