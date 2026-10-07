"""Exercise owner isolation against the real PostgreSQL test schema."""

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.main import app
from app.db.database import database_connection
from app.adapters.storage import ProjectStore, get_request_project_store
from app.core.exceptions import StorageError
from tests.api.test_analysis import selection
from tests.api.test_boxplot import cloud  # noqa: F401
from tests.integration.test_explanations import writer  # noqa: F401
from tests.integration.test_reports import report_ready, export


def test_scoped_store_hides_unassigned_history(tmp_path):
    internal = ProjectStore(tmp_path / 'assets')
    historical = internal.create_project('历史项目', '主题', 'sci')
    scoped = ProjectStore(tmp_path / 'assets', owner_id='another-user')
    assert scoped.projects() == []
    with pytest.raises(StorageError) as rejected:
        scoped.project(historical['id'])
    assert rejected.value.status == 404
    assert internal.project(historical['id'])['name'] == '历史项目'


def account_client(email, role='user'):
    from app.auth.service import create_user

    password = 'Ownership-test-password-2026'
    user = create_user(email, password, role=role)
    client = TestClient(app)
    client.headers['X-PaperAssist-Client'] = 'web'
    login = client.post('/api/v1/auth/login', json={'email': email, 'password': password})
    assert login.status_code == 200
    client.headers['X-CSRF-Token'] = login.json()['csrf_token']
    return client, user


def test_request_store_never_falls_back_to_unscoped_internal_store():
    request = Request({'type': 'http', 'state': {}})
    with pytest.raises(StorageError) as rejected:
        get_request_project_store(request)
    assert rejected.value.status == 401


def test_creation_uses_authenticated_owner_and_preserves_response_contract():
    with account_client('owner@paperassist.local')[0] as owner:
        identity = owner.get('/api/v1/auth/me').json()['user']
        payload = {'name': '我的课题', 'research_topic': '研究主题', 'project_type': 'thesis'}
        response = owner.post('/api/v1/projects', json=payload)
        assert response.status_code == 201
        project = response.json()
        assert set(project) == {'id', 'name', 'research_topic', 'project_type',
                                'default_output_language', 'created_at', 'updated_at', 'file_count'}
        with database_connection() as db:
            row = db.execute('SELECT owner_id FROM projects WHERE id = %s', (project['id'],)).fetchone()
        assert row['owner_id'] == identity['id']
        assert owner.post('/api/v1/projects', json={**payload, 'owner_id': 'someone-else'}).status_code == 422
        assert len(owner.get('/api/v1/projects').json()) == 1


@pytest.mark.parametrize('other_role', ['user', 'admin'])
def test_all_research_resources_and_mutations_are_private(cloud, writer, other_role):
    with account_client('alice@paperassist.local')[0] as owner:
        base, file, result, figure, explanation, report_url = report_ready(owner)
        exported = export(owner, report_url, figure, explanation)
        assert exported.status_code == 201
        report = exported.json()['report']
        project_url = base.split('/files/')[0]
        run_url = base + '/analysis-runs/' + result['id']
        download = report_url + '/' + report['id'] + '/download'
        report_content = owner.get(download).content
        reads = [project_url, project_url + '/files', base + '/preview', base + '/download',
                 base + '/analysis-profile?sheet=研究%20%26%20数据', base + '/analysis-setup',
                 base + '/analysis-result', run_url + '/boxplot', run_url + '/boxplot/image',
                 run_url + '/boxplot/image?download=true', run_url + '/explanation', report_url, download]
        with account_client('bob@paperassist.local', role=other_role)[0] as other:
            assert other.get('/api/v1/projects').json() == []
            own_project = other.post('/api/v1/projects', json={
                'name': '另一个用户', 'research_topic': '私有资料', 'project_type': 'thesis',
            }).json()
            assert [p['id'] for p in other.get('/api/v1/projects').json()] == [own_project['id']]
            assert [p['id'] for p in owner.get('/api/v1/projects').json()] == [project_url.rsplit('/', 1)[1]]
            for url in reads:
                response = other.get(url)
                assert response.status_code == 404, (url, response.text)
                assert response.json()['detail']['code'] == 'project_not_found'
            # Substituting an owned project into another user's nested resource is also refused.
            swapped = base.replace(project_url, '/api/v1/projects/' + own_project['id'])
            assert other.get(swapped + '/download').status_code == 404
            mutations = [
                ('post', project_url + '/files', {'files': {'file': ('foreign.xlsx', b'not-used')}}),
                ('post', base + '/analysis-check', {'json': selection()}),
                ('put', base + '/analysis-setup', {'json': selection(expected_revision=1)}),
                ('post', base + '/analysis-runs', {'json': {'expected_revision': 1}}),
                ('post', run_url + '/boxplot', {'json': {'expected_revision': 1}}),
                ('post', run_url + '/explanation', {'json': {'expected_revision': 1, 'figure_id': figure['id']}}),
                ('post', report_url, {'json': {'expected_revision': 1, 'figure_id': figure['id'],
                                             'explanation_id': explanation['id']}}),
            ]
            for method, url, options in mutations:
                response = getattr(other, method)(url, **options)
                assert response.status_code == 404, (method, url, response.text)
        # Denied operations cause neither data changes nor extra cloud requests.
        assert owner.get(base + '/analysis-setup').json()['revision'] == 1
        assert owner.get(download).content == report_content
        assert len(owner.get(project_url + '/files').json()) == 1
        assert len(cloud.calls) == len(writer.calls) == 1
        with TestClient(app) as anonymous:
            for url in reads:
                assert anonymous.get(url).status_code == 401
