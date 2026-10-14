"""File metadata contracts and immutable legacy assets."""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.db.database import database_connection
from tests.api.test_projects import client, create_project, upload  # noqa: F401
from tests.integration.test_project_ownership import account_client
from tests.api.test_boxplot import cloud  # noqa: F401
from tests.integration.test_explanations import writer  # noqa: F401


def saved(client):
    project = create_project(client)
    result = upload(client, project['id']).json()
    return project, result, f"/api/v1/projects/{project['id']}/files"


def test_explicit_pagination_keeps_old_array_and_upload_contract(client):
    project, upload_result, base = saved(client)
    first = upload_result['file']
    second = upload(client, project['id']).json()['file']
    with database_connection(write=True) as db:
        db.execute('UPDATE files SET uploaded_at=%s WHERE project_id=%s', ('2026-10-09T00:00:00Z', project['id']))
    legacy = client.get(base).json()
    assert all(set(item) == set(first) for item in legacy)
    page = client.get(base + '?page=2&page_size=1').json()
    assert page['total'] == 2 and page['page'] == 2 and page['page_size'] == 1
    assert page['items'][0]['id'] == sorted([first['id'], second['id']])[1]
    assert page['items'][0]['purposes'] == []
    assert page['items'][0]['metadata_revision'] == 1
    assert page['items'][0]['uploader_recorded'] is True
    assert client.get(base + '?page_size=1').json()['page'] == 1
    assert client.get(base + '?page=10&page_size=1').json()['items'] == []


@pytest.mark.parametrize('query', ['page=0', 'page=1000001', 'page=1.0', 'page_size=101', 'page_size=0', 'page_size=true'])
def test_file_page_rejects_invalid_query(client, query):
    _, _, base = saved(client)
    assert client.get(base + '?' + query).status_code == 422


def test_purposes_revision_idempotency_conflict_and_original_preservation(client):
    project, result, base = saved(client)
    file = result['file']
    url = base + '/' + file['id']
    original = client.get(url + '/download').content
    changed = client.put(url + '/purposes', json={'expected_revision': 1, 'purposes': ['paper', 'raw_data']})
    assert changed.status_code == 200, changed.text
    assert changed.json()['metadata_revision'] == 2
    assert changed.json()['purposes'] == ['raw_data', 'paper']
    replay = client.put(url + '/purposes', json={'expected_revision': 1, 'purposes': ['raw_data', 'paper']})
    assert replay.json() == changed.json()
    rejected = client.put(url + '/purposes', json={'expected_revision': 1, 'purposes': []})
    assert rejected.status_code == 409
    assert rejected.json()['detail']['code'] == 'file_metadata_conflict'
    assert client.get(base).json() == [file]
    assert client.get(url + '/preview').json() == result['preview']
    assert client.get(url + '/download').content == original
    details = client.get(url + '/details').json()
    assert details['source'] == {'kind': 'legacy_excel', 'preview_available': True, 'preview_row_limit': 20, 'parser_version': None}
    assert details['references'] == dict.fromkeys(['structure_versions', 'dataset_versions', 'prepared_dataset_versions', 'analysis_setups', 'analysis_runs', 'figures', 'explanations', 'reports', 'tasks', 'legacy_jobs', 'active_tasks', 'recovery_candidates'], 0)
    assert details['retention'] == {'policy': 'internal_testing_keep', 'automatic_deletion': False, 'deletion_available': False}
    assert not {'object_key', 'storage_backend', 'uploader_id', 'preview_json', 'input_snapshot'} & details.keys()


@pytest.mark.parametrize('body', [
    {'expected_revision': 1, 'purposes': ['paper', 'paper']},
    {'expected_revision': 1, 'purposes': ['unknown']},
    {'expected_revision': 0, 'purposes': []},
    {'expected_revision': True, 'purposes': []},
    {'expected_revision': 1, 'purposes': [], 'secret': 'forbidden'},
    {'expected_revision': 1, 'purposes': ['paper'] * 7},
])
def test_purposes_rejects_invalid_contract(client, body):
    _, result, base = saved(client)
    assert client.put(base + '/' + result['file']['id'] + '/purposes', json=body).status_code == 422


def test_metadata_routes_hide_other_project_and_owner(client):
    _, result, base = saved(client)
    other_project = create_project(client, 'other')
    wrong = f"/api/v1/projects/{other_project['id']}/files/{result['file']['id']}"
    assert client.get(wrong + '/details').status_code == 404
    assert client.put(wrong + '/purposes', json={'expected_revision': 1, 'purposes': []}).status_code == 404
    with account_client('file-other@example.test')[0] as other:
        assert other.get(base + '?page=1').status_code == 404
        assert other.get(base + '/' + result['file']['id'] + '/details').status_code == 404
        assert other.put(base + '/' + result['file']['id'] + '/purposes', json={'expected_revision': 1, 'purposes': []}).status_code == 404


def test_details_counts_persisted_chains_and_task_snapshot_sources(client):
    from tests.db.test_task_schema import task_row, insert_row
    project, result, base = saved(client)
    file = result['file']
    user = client.get('/api/v1/auth/me').json()['user']['id']
    other = create_project(client, 'unrelated')
    with database_connection(write=True) as db:
        db.execute('INSERT INTO analysis_setups VALUES (%s,1,%s)', (file['id'], '{}'))
        db.execute('INSERT INTO analysis_runs VALUES (%s,%s,1,%s,%s,%s)', ('run', file['id'], 'v', file['uploaded_at'], '{}'))
        db.execute("INSERT INTO figures VALUES ('fig','run','v','{}')")
        db.execute("INSERT INTO explanations VALUES ('exp','run','fig','v','{}')")
        db.execute("INSERT INTO reports VALUES ('rep','run','exp','v','{}','{}')")
        db.execute("INSERT INTO figure_jobs(id,analysis_run_id,renderer_version,created_at,job_json) VALUES ('job','run','v',%s,%s)", (file['uploaded_at'], json.dumps({'status': 'uncertain', 'secret': 'hidden'})))
        db.execute("INSERT INTO explanation_jobs(id,analysis_run_id,figure_id,engine_version,created_at,job_json) VALUES ('ejob','run','fig','v',%s,%s)", (file['uploaded_at'], json.dumps({'status': 'running'})))
        for key, snapshot, status in [
            ('direct', {'file': {'id': file['id']}, 'secret': 'hidden'}, 'queued'),
            ('result', {'result': {'id': 'run'}}, 'waiting_confirmation'),
            ('failed', {'result': {'file_id': file['id']}}, 'failed'),
            ('finished', {'file': {'id': file['id']}}, 'succeeded'),
        ]:
            candidate = {'figure': {'id': 'pending-figure', 'analysis_run_id': 'run'}, 'path': 'internal-candidate'} if key == 'failed' else None
            insert_row(db, 'tasks', task_row(id=key, idempotency_key=key, project_id=project['id'], user_id=user, input_snapshot=snapshot, status=status, figure_candidate=candidate))
        insert_row(db, 'tasks', task_row(id='other', idempotency_key='other', project_id=other['id'], user_id=user, input_snapshot={'file': {'id': file['id']}}, status='queued'))
    details = client.get(base + '/' + file['id'] + '/details')
    assert details.status_code == 200, details.text
    assert details.json()['references'] == {'structure_versions': 0, 'dataset_versions': 0, 'prepared_dataset_versions': 0, 'analysis_setups': 1, 'analysis_runs': 1, 'figures': 1, 'explanations': 1, 'reports': 1, 'tasks': 4, 'legacy_jobs': 2, 'active_tasks': 2, 'recovery_candidates': 1}
    assert 'hidden' not in details.text and 'input_snapshot' not in details.text


def test_concurrent_purposes_updates_use_one_revision(client):
    _, result, base = saved(client)
    url = base + '/' + result['file']['id'] + '/purposes'
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda purposes: client.put(url, json={'expected_revision': 1, 'purposes': purposes}),
                                  [['raw_data'], ['paper']]))
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert client.get(base + '?page=1').json()['items'][0]['metadata_revision'] == 2


def test_metadata_preserves_frozen_task_sources_and_completed_artifacts(client, cloud, writer):
    from tests.integration.test_reports import report_ready
    from app.domain.tasks.execution import run_word_task
    base, file, result, figure, explanation, report_url = report_ready(client)
    accepted = client.post(report_url, json={'expected_revision': figure['setup_revision'],
                                            'figure_id': figure['id'], 'explanation_id': explanation['id']})
    assert accepted.status_code == 202, accepted.text
    task = accepted.json()['task']
    tables = ('file_structure_versions', 'dataset_versions', 'analysis_setups', 'analysis_runs', 'figures', 'explanations', 'reports', 'tasks',
              'figure_jobs', 'explanation_jobs', 'task_attempts', 'task_events', 'task_outbox',
              'model_calls', 'model_budgets', 'budget_reservations', 'usage_events')
    def snapshot():
        with database_connection() as db:
            return {table: [dict(row) for row in db.execute('SELECT * FROM ' + table + ' ORDER BY 1')] for table in tables}
    before = snapshot()
    original = client.get(base + '/download').content
    png = client.get(base + '/analysis-runs/' + result['id'] + '/boxplot/image').content
    changed = client.put(base + '/purposes', json={'expected_revision': 1, 'purposes': ['paper']})
    assert changed.status_code == 200, changed.text
    assert snapshot() == before
    assert client.get(base + '/download').content == original
    assert client.get(base + '/analysis-runs/' + result['id'] + '/boxplot/image').content == png
    run_word_task(task['id'], task['revision'])
    report = client.get(report_url).json()['report']
    assert report is not None
    content = client.get(report_url + '/' + report['id'] + '/download').content
    with database_connection() as db:
        frozen = db.execute('SELECT input_snapshot FROM tasks WHERE id=%s', (task['id'],)).fetchone()['input_snapshot']
    expected = next(row['input_snapshot'] for row in before['tasks'] if row['id'] == task['id'])
    assert frozen == expected and frozen['schema_version'] == 1
    assert 'metadata_revision' not in frozen['file'] and frozen['output_language'] == task['input_version']['output_language']
    completed = snapshot()
    assert client.put(base + '/purposes', json={'expected_revision': 2, 'purposes': ['revision_material']}).status_code == 200
    assert snapshot() == completed
    assert client.get(report_url + '/' + report['id'] + '/download').content == content


def test_details_counts_preparation_tasks_and_published_versions(client):
    from tests.integration.test_dataset_preparation import create_preparation, run, review, decide, decision
    base, _, _, _, task = create_preparation(client)
    queued = client.get(base+'/details').json()['references']
    assert queued['tasks'] == 2 and queued['active_tasks'] == 1
    assert queued['prepared_dataset_versions'] == 0
    run(task)
    accepted = decide(client, task, decision(review(client, task))).json()
    assert run(accepted)['status'] == 'succeeded'
    response = client.get(base+'/details')
    assert response.status_code == 200, response.text
    refs = response.json()['references']
    assert refs['prepared_dataset_versions'] == 1
    assert refs['structure_versions'] == 1 and refs['dataset_versions'] == 3
    assert refs['tasks'] == 2 and refs['active_tasks'] == 0
    assert 'object_key' not in response.text and 'input_snapshot' not in response.text
