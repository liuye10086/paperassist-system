"""Language settings persist independently without changing historical artifacts."""
from app.db.database import migration_connection
import os
from pathlib import Path
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.db.database import database_connection
from app.main import app
from app.adapters.storage import ProjectStore
from app.core.exceptions import StorageError
from tests.integration.test_project_ownership import account_client
from tests.api.test_projects import create_project, upload
from tests.api.test_boxplot import cloud  # noqa: F401
from tests.integration.test_explanations import writer  # noqa: F401
from tests.integration.test_reports import report_ready, export


@pytest.fixture
def client():
    with account_client('language-owner@example.local')[0] as client:
        yield client


def test_user_defaults_public_projection_and_persistent_preferences(client):
    assert client.get('/api/v1/auth/me').json()['user']['ui_language'] == 'zh-CN'
    assert client.get('/api/v1/auth/preferences').json() == {'ui_language': 'zh-CN'}
    assert client.patch('/api/v1/auth/preferences', json={'ui_language': 'en'}).json() == {'ui_language': 'en'}
    assert client.get('/api/v1/auth/preferences').json() == {'ui_language': 'en'}
    assert client.get('/api/v1/auth/me').json()['user']['ui_language'] == 'en'
    login = client.post('/api/v1/auth/login', json={'email': 'language-owner@example.local', 'password': 'Ownership-test-password-2026'})
    assert login.status_code == 200
    assert login.json()['user']['ui_language'] == 'en'
    assert set(login.json()['user']) == {'id', 'email', 'role', 'ui_language'}
    with database_connection() as db:
        assert db.execute('SELECT ui_language FROM users').fetchone()['ui_language'] == 'en'


@pytest.mark.parametrize('body', [{}, {'ui_language': 'fr'}, {'ui_language': None}, {'ui_language': 1}, {'ui_language': ' en '}, {'ui_language': 'en', 'role': 'admin'}, {'user_id': 'private-marker', 'ui_language': 'en'}, [], 'private-marker'])
def test_user_preferences_reject_invalid_or_extra_fields(client, body):
    response = client.patch('/api/v1/auth/preferences', json=body)
    assert response.status_code == 422
    assert 'private-marker' not in response.text
    assert client.get('/api/v1/auth/preferences').json() == {'ui_language': 'zh-CN'}


def test_preferences_require_csrf_origin_and_isolate_accounts(client):
    with account_client('language-other@example.local')[0] as other:
        assert client.patch('/api/v1/auth/preferences', json={'ui_language': 'en'}).status_code == 200
        assert other.get('/api/v1/auth/preferences').json() == {'ui_language': 'zh-CN'}
    response = client.patch('/api/v1/auth/preferences', json={'ui_language': 'zh-CN'}, headers={'X-CSRF-Token': 'wrong'})
    assert response.status_code == 403
    assert client.patch('/api/v1/auth/preferences', json={'ui_language': 'zh-CN'}, headers={'Origin': 'https://untrusted.example'}).status_code == 403
    assert client.get('/api/v1/auth/preferences').json() == {'ui_language': 'en'}
    with TestClient(app) as anonymous:
        assert anonymous.get('/api/v1/auth/preferences').status_code == 401
        assert anonymous.patch('/api/v1/auth/preferences', json={'ui_language': 'en'}).status_code == 401


@pytest.mark.parametrize('action', ['expired', 'idle', 'disabled', 'revoked', 'csrf'])
def test_preference_write_rechecks_session_in_transaction(client, action):
    from app.auth import service
    token = client.cookies.get('paperassist_session')
    csrf = client.headers['X-CSRF-Token']
    if action == 'revoked':
        service.revoke_session(token)
    elif action == 'csrf':
        csrf = 'wrong'
    else:
        with database_connection(write=True) as db:
            if action == 'expired':
                db.execute('UPDATE sessions SET expires_at = 0')
            elif action == 'idle':
                db.execute('UPDATE sessions SET last_seen_at = %s', (time.time() - 10_000,))
            else:
                db.execute('UPDATE users SET active = false')
    with pytest.raises(StorageError) as rejected:
        service.update_preferences(token, csrf, 'en')
    assert rejected.value.status == (403 if action == 'csrf' else 401)
    with database_connection() as db:
        assert db.execute('SELECT ui_language FROM users').fetchone()['ui_language'] == 'zh-CN'


def test_project_language_defaults_persist_and_all_projections_include_language(client):
    project = create_project(client)
    assert project['default_output_language'] == 'zh-CN'
    url = f'/api/v1/projects/{project["id"]}'
    assert client.get(url + '/language').json() == project
    changed = client.patch(url + '/language', json={'default_output_language': 'en'})
    assert changed.status_code == 200
    changed = changed.json()
    assert changed['default_output_language'] == 'en'
    for field in ('id', 'name', 'research_topic', 'project_type', 'created_at', 'file_count'):
        assert changed[field] == project[field]
    assert changed['updated_at'] > project['updated_at']
    assert client.patch(url + '/language', json={'default_output_language': 'en'}).json() == changed
    assert client.get(url).json() == changed
    assert client.get('/api/v1/projects').json() == [changed]
    assert client.get('/api/v1/projects?page=1').json()['items'] == [changed]
    assert client.patch(url, json={'name': 'new name'}).json()['default_output_language'] == 'en'
    explicit = client.post('/api/v1/projects', json={'name': 'English', 'research_topic': 'Original topic', 'project_type': 'thesis', 'default_output_language': 'en'})
    assert explicit.status_code == 201
    assert explicit.json()['default_output_language'] == 'en'


@pytest.mark.parametrize('body', [{}, {'default_output_language': 'fr'}, {'default_output_language': None}, {'default_output_language': 1}, {'default_output_language': 'en', 'name': 'bad'}, {'default_output_language': 'en', 'project_type': 'thesis'}, [], 'private-marker'])
def test_project_language_rejects_extra_fields_and_keeps_original_patch_contract(client, body):
    project = create_project(client)
    url = f'/api/v1/projects/{project["id"]}'
    assert client.patch(url + '/language', json=body).status_code == 422
    assert client.get(url).json() == project
    assert client.patch(url, json={'default_output_language': 'en'}).json()['detail']['code'] == 'project_update_invalid'
    assert client.patch(url, json={'project_type': 'thesis'}).json()['detail']['code'] == 'project_type_immutable'


def test_project_language_isolation_csrf_and_history(client):
    project = create_project(client)
    assert upload(client, project['id']).status_code == 201
    url = f'/api/v1/projects/{project["id"]}/language'
    with database_connection() as db:
        history = [dict(row) for row in db.execute('SELECT * FROM files')]
    assets = {p: p.read_bytes() for p in Path(os.environ['PAPERASSIST_DATA_DIR']).rglob('*.xlsx')}
    assert client.patch(url, json={'default_output_language': 'en'}, headers={'X-CSRF-Token': 'wrong'}).status_code == 403
    with account_client('language-admin@example.local', 'admin')[0] as other:
        assert other.get(url).status_code == 404
        assert other.patch(url, json={'default_output_language': 'en'}).status_code == 404
    assert client.patch(url, json={'default_output_language': 'en'}).status_code == 200
    with database_connection() as db:
        assert [dict(row) for row in db.execute('SELECT * FROM files')] == history
    assert {p: p.read_bytes() for p in assets} == assets
    assert client.get('/api/v1/auth/preferences').json() == {'ui_language': 'zh-CN'}


def test_language_change_preserves_complete_research_history_and_downloads(client, cloud, writer):
    base, file, result, figure, explanation, report_url = report_ready(client)
    report = export(client, report_url, figure, explanation).json()['report']
    project_url = base.split('/files/')[0]
    tables = ('files', 'analysis_setups', 'analysis_runs', 'figures', 'figure_jobs', 'explanations', 'explanation_jobs', 'reports')
    with database_connection() as db:
        history = {table: [dict(row) for row in db.execute(f'SELECT * FROM {table}')] for table in tables}
    directory = Path(os.environ['PAPERASSIST_DATA_DIR'])
    assets = {p: p.read_bytes() for p in directory.rglob('*') if p.is_file()}
    downloads = [base + '/download', base + '/analysis-runs/' + result['id'] + '/boxplot/image', report_url + '/' + report['id'] + '/download']
    content = {url: client.get(url).content for url in downloads}
    calls = (len(cloud.calls), len(writer.calls))
    assert client.patch(project_url + '/language', json={'default_output_language': 'en'}).status_code == 200
    assert client.patch('/api/v1/auth/preferences', json={'ui_language': 'en'}).status_code == 200
    with database_connection() as db:
        assert {table: [dict(row) for row in db.execute(f'SELECT * FROM {table}')] for table in tables} == history
    assert {p: p.read_bytes() for p in assets} == assets
    assert {url: client.get(url).content for url in downloads} == content
    assert (len(cloud.calls), len(writer.calls)) == calls == (1, 1)


def test_internal_language_validation_and_database_failure_are_atomic(client):
    project = create_project(client)
    store = ProjectStore(Path(os.environ['PAPERASSIST_DATA_DIR']))
    with pytest.raises(StorageError) as rejected:
        store.update_project_language(project['id'], 'fr')
    assert rejected.value.code == 'project_language_invalid'
    with pytest.raises(StorageError):
        store.create_project('name', 'topic', 'sci', 'fr')
    with migration_connection(write=True) as db:
        db.execute("CREATE FUNCTION reject_language() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic language failure'; END $$")
        for table in ('users', 'projects'):
            db.execute(f'CREATE TRIGGER reject_language BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION reject_language()')
    try:
        for url, body in [('/api/v1/auth/preferences', {'ui_language': 'en'}), (f'/api/v1/projects/{project["id"]}/language', {'default_output_language': 'en'})]:
            response = client.patch(url, json=body)
            assert response.status_code == 503
            assert response.json()['detail']['code'] == 'storage_unavailable'
        assert client.get('/api/v1/auth/preferences').json() == {'ui_language': 'zh-CN'}
        assert client.get(f'/api/v1/projects/{project["id"]}').json() == project
    finally:
        with migration_connection(write=True) as db:
            for table in ('users', 'projects'):
                db.execute(f'DROP TRIGGER reject_language ON {table}')
            db.execute('DROP FUNCTION reject_language()')


@pytest.mark.parametrize('table,column', [('users', 'ui_language'), ('projects', 'default_output_language')])
@pytest.mark.parametrize('value', ['fr', None])
def test_database_language_constraints(client, table, column, value):
    create_project(client)
    with pytest.raises(IntegrityError):
        with database_connection(write=True) as db:
            db.execute(f'UPDATE {table} SET {column} = %s', (value,))


def test_language_migration_roundtrip_preserves_legacy_columns_json_and_assets(client, postgres_schema, postgres_migration_config):
    from alembic import command
    from sqlalchemy import inspect
    from app.db.database import alembic_config, migrate_database, SCHEMA_HEAD
    from app.db.schema import metadata
    project = create_project(client)
    assert upload(client, project['id']).status_code == 201
    assets = {p: p.read_bytes() for p in Path(os.environ['PAPERASSIST_DATA_DIR']).rglob('*.xlsx')}
    tables = ('users', 'sessions', 'projects', 'files', 'analysis_setups', 'analysis_runs', 'figures', 'figure_jobs', 'explanations', 'explanation_jobs', 'reports')
    with migration_connection(write=True) as db:
        config = alembic_config()
        config.attributes['connection'] = db.raw_connection
        config.attributes['database_config'] = postgres_migration_config
        command.downgrade(config, '0003_password_security')
        originals = {table: [dict(row) for row in db.execute(f'SELECT * FROM {table}')] for table in tables}
        assert 'ui_language' not in {col['name'] for col in inspect(db.raw_connection).get_columns('users')}
    for cycle in range(2):
        migrate_database(postgres_migration_config)
        assert SCHEMA_HEAD == '0005_ownership_indexes'
        with migration_connection(write=True) as db:
            for table, expected in originals.items():
                actual = [dict(row) for row in db.execute(f'SELECT * FROM {table}')]
                for row in actual:
                    if table in ('users', 'projects'):
                        column = 'ui_language' if table == 'users' else 'default_output_language'
                        assert row.pop(column) == 'zh-CN'
                assert actual == expected
            for table in ('users', 'projects'):
                assert {c['name'] for c in inspect(db.raw_connection).get_columns(table)} == set(metadata.tables[table].columns.keys())
            if cycle == 0:
                config.attributes['connection'] = db.raw_connection
                command.downgrade(config, '0003_password_security')
    assert {p: p.read_bytes() for p in assets} == assets
