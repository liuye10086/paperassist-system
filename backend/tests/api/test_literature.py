"""Offline literature contracts: synthetic requests, isolated PostgreSQL only."""
import copy

import pytest

from tests.api.test_analysis import client  # noqa: F401


def project(client, kind='sci'):
    response = client.post('/api/v1/projects', json={'name': 'Offline literature contract', 'project_type': kind,
        'research_topic': 'A synthetic retrieval question'})
    assert response.status_code == 201, response.text
    return response.json()['id']


def request():
    return {'research_topic': 'A synthetic retrieval question',
        'source_context': {'kind': 'section', 'label': 'Introduction', 'text': 'Synthetic background question'},
        'query': 'aspirin[Title/Abstract]', 'year_from': None, 'year_to': None,
        'publication_types': [], 'sort': 'relevance', 'limit': 20, 'output_language': 'zh-CN'}


def create(client, project_id, body=None, key='literature-first'):
    return client.post(f'/api/v1/projects/{project_id}/literature/searches', json=body or request(),
        headers={'Idempotency-Key': key})


def test_literature_task_creation_is_idempotent_without_any_analysis_file(client, monkeypatch):
    monkeypatch.setenv('PAPERASSIST_NCBI_ENABLED', '0')
    pid = project(client)
    response = create(client, pid)
    assert response.status_code == 202, response.text
    task = response.json()
    assert task['task_type'] == 'literature_search' and task['phase'] == 'search'
    assert task['input_version']['kind'] == 'literature_search'
    replay = create(client, pid)
    assert replay.status_code == 200 and replay.json() == task
    changed = create(client, pid, {**request(), 'query': 'metformin[Title/Abstract]'})
    assert changed.status_code == 409
    detail = client.get(f'/api/v1/projects/{pid}/literature/searches/{task["id"]}')
    assert detail.status_code == 200, detail.text
    assert detail.json()['input'] == request()
    assert detail.json()['retrieved_count'] == 0 and detail.json()['matched_count'] is None
    workspace = client.get(f'/api/v1/tasks/{task["id"]}/workspace')
    assert workspace.status_code == 200, workspace.text
    assert workspace.json()['source']['file_id'] is None
    listing = client.get(f'/api/v1/projects/{pid}/tasks?task_type=literature_search')
    assert listing.status_code == 200 and listing.json()['total'] == 1
    assert client.get(f'/api/v1/projects/{pid}/literature/references').json()['total'] == 0


@pytest.mark.parametrize('changes', [{'limit': 101}, {'limit': True}, {'query': '   '},
    {'year_from': 2026, 'year_to': 2020}, {'publication_types': ['InventedType']},
    {'source_context': {'kind': 'manuscript', 'label': 'x', 'text': 'x'}}, {'extra': 'unaccepted'}])
def test_invalid_literature_inputs_do_not_create_tasks(client, changes):
    pid = project(client)
    response = create(client, pid, {**request(), **changes})
    assert response.status_code == 422, response.text
    from app.db.database import database_connection
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM tasks').fetchone()['n'] == 0


def test_literature_search_and_candidate_reads_require_the_same_project(client):
    pid = project(client)
    other = project(client, 'thesis')
    task = create(client, pid)
    assert task.status_code == 202, task.text
    assert client.get(f'/api/v1/projects/{other}/literature/searches/{task.json()["id"]}').status_code == 404
    config = client.get(f'/api/v1/projects/{pid}/literature/config')
    assert config.status_code == 200, config.text
    assert config.json()['available'] is False
    assert 'email' not in config.json() and 'api_key' not in config.json()


def test_saved_source_context_tracks_selected_search_and_remains_owner_scoped(client):
    from tests.helpers.literature import SyntheticNcbi
    from tests.integration.test_literature_workflow import execute
    from tests.integration.test_project_ownership import account_client

    pid = project(client)
    old_context = {'kind': 'section', 'label': '保存的原始背景', 'text': '真实回执离线重放（未再次外发）'}
    new_context = {'kind': 'feedback', 'label': 'Later feedback', 'text': 'Different saved background'}
    first = create(client, pid, {**request(), 'source_context': old_context}, key='context-old').json()
    assert execute(first, SyntheticNcbi(1))['status'] == 'succeeded'
    second = create(client, pid, {**request(), 'source_context': new_context}, key='context-new').json()
    assert execute(second, SyntheticNcbi(1))['status'] == 'succeeded'
    base = f'/api/v1/projects/{pid}/literature'
    old_listing = client.get(base + '/references', params={'search_id': first['id']})
    assert old_listing.status_code == 200, old_listing.text
    old_reference = old_listing.json()['items'][0]
    assert old_reference['source']['source_context'] == old_context
    url = base + '/references/' + old_reference['id']
    old = client.get(url, params={'search_id': first['id']})
    assert old.status_code == 200, old.text
    assert old.json()['source']['source_context'] == old_context
    contexts = {s['search_id']: s['source_context'] for s in old.json()['sources']['items']}
    assert contexts == {first['id']: old_context, second['id']: new_context}
    assert client.get(url).json()['source']['source_context'] == new_context
    selected = client.patch(url, json={'expected_revision': 1, 'status': 'shortlisted', 'note': ''})
    assert selected.status_code == 200, selected.text
    assert selected.json()['source']['source_context'] == new_context
    assert client.get(base + '/searches/' + first['id']).json()['input']['source_context'] == old_context
    with account_client('source-context-intruder@example.test')[0] as other:
        for path in (base + '/references', url, base + '/searches/' + first['id'],
                     old_reference['source']['source_download_url']):
            assert other.get(path).status_code == 404
