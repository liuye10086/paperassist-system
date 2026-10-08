"""Project task reads preserve source ownership and never run business work."""
import json

import pytest

from app.db.database import database_connection
from app.domain.tasks.service import TaskService
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_boxplot import cloud  # noqa: F401
from tests.api.test_task_request_id import assert_request_id
from tests.helpers.tasks import boxplot_task_input, task_owner
from tests.api.test_plot_tasks import policy  # noqa: F401
from tests.integration.test_explanations import writer  # noqa: F401


def create_task(client, key='workspace-task'):
    project, request, base, result = boxplot_task_input(client)
    service = TaskService(task_owner(client))
    task, _ = service.create(project, request, idempotency_key=key)
    return project, request, base, result, service, task


def counts():
    with database_connection() as db:
        return {name: db.execute('SELECT count(*) AS n FROM ' + name).fetchone()['n']
                for name in ('tasks', 'task_events', 'task_outbox', 'model_calls', 'budget_reservations',
                             'task_waits', 'task_resume_requests')}


def test_workspace_reads_current_source_without_private_snapshot_or_writes(client, cloud):
    project, request, _, _, _, task = create_task(client)
    before = counts()
    response = client.get('/api/v1/tasks/' + task['id'] + '/workspace')
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['task'] == task
    assert data['source'] == {'file_id': request.file_id, 'filename': 'data.xlsx',
                              'analysis_run_id': request.analysis_run_id, 'is_current': True}
    assert data['wait'] is None and data['allowed_actions'] == []
    assert data['artifacts'] == {'figure': None, 'explanation': None, 'report': None}
    assert_request_id(response)
    page = client.get(f'/api/v1/projects/{project}/tasks').json()
    assert page['items'] == [{'task': task, 'source': data['source']}]
    assert counts() == before and cloud.calls == []
    for secret in ('input_snapshot', 'input_digest', 'source_sha256', 'boxplot_policy', 'provider_state', 'idempotency_key'):
        assert secret not in json.dumps(data)


def test_project_tasks_filter_and_page_stably(client):
    project, request, _, _, service, first = create_task(client, 'first')
    second, _ = service.create(project, request, idempotency_key='second')
    running = service.transition(first['id'], expected_revision=1, status='running')
    service.transition(first['id'], expected_revision=running['revision'], status='failed', reason_code='execution_failed')
    response = client.get(f'/api/v1/projects/{project}/tasks?page=1&page_size=1')
    assert response.status_code == 200, response.text
    assert_request_id(response)
    page = response.json()
    assert page['total'] == 2 and page['page'] == 1 and page['page_size'] == 1
    assert page['items'][0]['task']['id'] == second['id']
    assert client.get(f'/api/v1/projects/{project}/tasks?page=2&page_size=1').json()['items'][0]['task']['id'] == first['id']
    filtered = client.get(f'/api/v1/projects/{project}/tasks?status=failed&task_type=boxplot').json()
    assert filtered['total'] == 1 and filtered['items'][0]['task']['id'] == first['id']
    assert client.get(f'/api/v1/projects/{project}/tasks?task_type=word_report').json()['items'] == []
    # Equal timestamps still give deterministic pagination.
    with database_connection(write=True) as db:
        db.execute('UPDATE tasks SET created_at=%s WHERE project_id=%s', (first['created_at'], project))
    tied = client.get(f'/api/v1/projects/{project}/tasks').json()['items']
    assert [item['task']['id'] for item in tied] == sorted([first['id'], second['id']], reverse=True)
    other, *_ = create_task(client, 'other-project')
    assert client.get(f'/api/v1/projects/{project}/tasks').json()['total'] == 2
    assert client.get(f'/api/v1/projects/{other}/tasks').json()['total'] == 1


def test_stale_source_is_readable_but_not_recoverable(client):
    _, _, base, result, service, task = create_task(client)
    service.transition(task['id'], expected_revision=1, status='running')
    service.transition(task['id'], expected_revision=2, status='waiting_confirmation', reason_code='budget_exceeded')
    changed = client.put(base + '/analysis-setup', json={**result['selection'], 'expected_revision': 1, 'unit': 'changed'})
    assert changed.status_code == 200
    response = client.get('/api/v1/tasks/' + task['id'] + '/workspace')
    assert response.status_code == 200, response.text
    assert response.json()['source']['is_current'] is False
    assert response.json()['allowed_actions'] == []
    assert response.json()['task']['input_version']['setup_revision'] == 1


@pytest.mark.parametrize('params', [
    {'page': '0'}, {'page': '1.0'}, {'page': '１'}, {'page': '1000001'},
    {'page_size': '51'}, {'page_size': '0'}, {'page_size': ' 1'},
    {'status': 'done'}, {'task_type': 'unimplemented'},
])
def test_list_rejects_invalid_queries(client, params):
    response = client.get('/api/v1/projects/missing/tasks', params=params)
    assert response.status_code == 422
    assert_request_id(response)


def test_reads_hide_other_owner_and_disabled_account(client):
    from tests.integration.test_project_ownership import account_client
    from fastapi.testclient import TestClient
    from app.main import app
    project, _, _, _, _, task = create_task(client)
    endpoints = [f'/api/v1/projects/{project}/tasks', f'/api/v1/tasks/{task["id"]}/workspace']
    stranger, _ = account_client('task-reader@example.test')
    try:
        with TestClient(app) as anonymous:
            for endpoint in endpoints:
                response = stranger.get(endpoint)
                assert response.status_code == 404
                assert_request_id(response)
                response = anonymous.get(endpoint)
                assert response.status_code == 401
                assert_request_id(response)
    finally:
        stranger.close()
    owner = task_owner(client)
    with database_connection(write=True) as db:
        db.execute('UPDATE users SET active=FALSE WHERE id=%s', (owner,))
    assert all(client.get(endpoint).status_code == 401 for endpoint in endpoints)


def test_resume_http_requires_key_replays_receipt_and_traces_conflicts(client, policy):
    from tests.integration.test_task_resume import waiting, request_for
    task, _ = waiting(client)
    request = request_for(task)
    endpoint = '/api/v1/tasks/' + task['id'] + '/resume'
    for headers in ({}, {'Idempotency-Key': ''}, {'Idempotency-Key': 'has space'}, {'Idempotency-Key': 'x' * 129}):
        response = client.post(endpoint, json=request, headers=headers)
        assert response.status_code == 422
        assert_request_id(response)
    headers = {'Idempotency-Key': 'resume-http'}
    before = counts()
    response = client.post(endpoint, json=request, headers=headers)
    assert response.status_code == 202, response.text
    assert_request_id(response)
    accepted = response.json()
    assert accepted['status'] == 'queued'
    after = counts()
    assert after['task_resume_requests'] == before['task_resume_requests'] + 1
    assert client.post(endpoint, json=request, headers=headers).json() == accepted
    assert counts() == after
    conflict = client.post(endpoint, json={**request, 'expected_task_revision': 1}, headers=headers)
    assert conflict.status_code == 409 and conflict.json()['detail']['code'] == 'task_idempotency_conflict'
    assert_request_id(conflict)
    workspace = client.get('/api/v1/tasks/' + task['id'] + '/workspace').json()
    assert workspace['wait'] is None and workspace['allowed_actions'] == []


@pytest.mark.parametrize('kind', ['boxplot', 'explanation', 'word_report'])
def test_exact_saved_artifact_survives_new_setup_without_mutation(client, cloud, request, kind):
    if kind == 'boxplot':
        from tests.integration.test_boxplot_execution import queued, until_response, SyntheticPlotProvider
        task, _, base, result = queued(client)
        task = until_response(task, SyntheticPlotProvider(result, pending=False))
    elif kind == 'explanation':
        from tests.integration.test_explanation_execution import execution_setup, run, SyntheticProvider
        task, _, base, result, *_ = execution_setup(client)
        task = run(task, SyntheticProvider())
    else:
        request.getfixturevalue('writer')
        from tests.integration.test_task_execution import queued
        from app.domain.tasks.execution import run_word_task
        task, base, result, _ = queued(client)
        task = run_word_task(task['id'], task['revision'])
    assert task['status'] == 'succeeded'
    endpoint = '/api/v1/tasks/' + task['id'] + '/workspace'
    before = counts()
    response = client.get(endpoint)
    assert response.status_code == 200, response.text
    artifacts = response.json()['artifacts']
    artifact_kind = {'boxplot': 'figure', 'explanation': 'explanation', 'word_report': 'report'}[kind]
    artifact = artifacts[artifact_kind]
    assert artifact and all(value is None for key, value in artifacts.items() if key != artifact_kind)
    if kind == 'explanation':
        assert artifact['sections'] and set(artifact['sections'][0]) == {'key', 'title', 'text'}
    else:
        assert task['result_' + artifact_kind + '_id'] in artifact['download_url']
        assert client.get(artifact['download_url']).status_code == 200
    changed = client.put(base + '/analysis-setup', json={**result['selection'], 'expected_revision': 1, 'unit': 'new'})
    assert changed.status_code == 200
    historic = client.get(endpoint)
    assert historic.status_code == 200, historic.text
    assert historic.json()['artifacts'] == artifacts and not historic.json()['source']['is_current']
    if kind != 'explanation':
        assert client.get(artifact['download_url']).status_code == 200
    assert counts() == before
    table, column = {'boxplot': ('figures', 'figure_json'),
                     'explanation': ('explanations', 'explanation_json'),
                     'word_report': ('reports', 'report_json')}[kind]
    with database_connection(write=True) as db:
        row = db.execute('SELECT ' + column + ' AS payload FROM ' + table + ' WHERE id=%s',
                         (task['result_' + artifact_kind + '_id'],)).fetchone()
        payload = json.loads(row['payload'])
        payload['analysis_run_id'] = 'private-unrelated-run'
        db.execute('UPDATE ' + table + ' SET ' + column + '=%s WHERE id=%s',
                   (json.dumps(payload), task['result_' + artifact_kind + '_id']))
    rejected = client.get(endpoint)
    assert rejected.status_code == 409 and rejected.json()['detail']['code'] == 'task_source_conflict'
    assert 'private-unrelated-run' not in rejected.text
