"""Project summaries use persisted facts, owner scope and no cloud operations."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from threading import Event

import pytest
from fastapi.testclient import TestClient

from app.database import DatabaseConnection, database_connection
from app.main import app
from app.storage import ProjectStore
from test_analysis import client, selection  # noqa: F401
from test_boxplot import cloud  # noqa: F401
from test_explanations import writer  # noqa: F401
from test_project_ownership import account_client
from test_reports import report_ready, export


@pytest.mark.parametrize('project_type', ['sci', 'thesis'])
def test_empty_summary_has_explicit_type_specific_unavailable_contract(client, project_type):
    project = client.post('/api/v1/projects', json={
        'name': '摘要测试', 'research_topic': '真实记录', 'project_type': project_type,
    }).json()
    response = client.get(f'/api/v1/projects/{project["id"]}/summary')
    assert response.status_code == 200, response.text
    summary = response.json()
    assert summary['project_id'] == project['id'] and summary['project_type'] == project_type
    for key in ('tasks', 'artifacts'):
        assert summary[key] == {'items': [], 'total': 0, 'page': 1, 'page_size': 10}
    future = summary['future']
    assert future['writing'] == {'state': 'not_available', 'tasks': [], 'current_manuscript': None, 'versions': []}
    assert future['revision'] == {'state': 'not_available', 'tasks': [], 'current_round': None,
                                  'rounds': [], 'opinions': [], 'pending_materials': []}
    assert future[project_type]['state'] == 'not_available'
    assert future['thesis' if project_type == 'sci' else 'sci'] is None
    if project_type == 'sci':
        assert future['sci']['target_journal'] is None and future['sci']['submission_progress'] is None
    else:
        assert all(future['thesis'][key] is None for key in ('school', 'degree', 'template', 'review_progress'))


def test_success_history_links_sources_and_exact_downloads_without_cloud_or_writes(client, cloud, writer, monkeypatch):
    base, file, result, figure, explanation, report_url = report_ready(client)
    report = export(client, report_url, figure, explanation).json()['report']
    project_url = base.split('/files/')[0]
    # Summary is a read of saved state, including when completion reconciliation lags.
    with database_connection(write=True) as db:
        db.execute("UPDATE figure_jobs SET job_json=jsonb_set(job_json::jsonb, '{status}', '\"running\"')::text")
    with database_connection() as db:
        before = [dict(row) for row in db.execute('SELECT id, job_json FROM figure_jobs ORDER BY id')]
    def forbidden(*args, **kwargs):
        raise AssertionError('Summary must not contact the cloud')
    monkeypatch.setattr('app.boxplot.CloudPlot.fetch', forbidden)
    monkeypatch.setattr('app.explanations.CloudExplanation.fetch', forbidden)
    response = client.get(project_url + '/summary')
    assert response.status_code == 200, response.text
    summary = response.json()
    tasks = {item['kind']: item for item in summary['tasks']['items']}
    assert set(tasks) == {'statistics', 'boxplot', 'explanation', 'report'}
    assert tasks['boxplot']['status'] == 'running'
    for kind, task in tasks.items():
        assert task['status'] == ('running' if kind == 'boxplot' else 'completed')
        assert task['file_id'] == file['id'] and task['filename'] == file['filename']
        assert task['analysis_run_id'] == result['id']
        assert task['setup_revision'] == task['current_revision'] == 1
    assert tasks['explanation']['figure_id'] == figure['id']
    assert tasks['report']['explanation_id'] == explanation['id']
    artifacts = {item['kind']: item for item in summary['artifacts']['items']}
    assert set(artifacts) == {'figure', 'report'}
    assert artifacts['figure']['id'] == figure['id']
    assert artifacts['report']['id'] == report['id']
    assert artifacts['report']['figure_id'] == figure['id']
    assert artifacts['report']['explanation_id'] == explanation['id']
    for artifact in artifacts.values():
        download = client.get(artifact['download_url'])
        assert download.status_code == 200
        assert hashlib.sha256(download.content).hexdigest() == artifact['sha256']
    with database_connection() as db:
        assert [dict(row) for row in db.execute('SELECT id, job_json FROM figure_jobs ORDER BY id')] == before
    assert summary['future']['sci']['submission_progress'] is None
    assert all(key not in response.text for key in ('response_id', 'container_id', 'payload', 'provenance', 'input_json'))
    # A later configuration keeps history and reports its original revision.
    assert client.put(base + '/analysis-setup', json=selection(expected_revision=1, unit='g/L')).status_code == 200
    old = client.get(project_url + '/summary').json()
    assert all(item['setup_revision'] == 1 and item['current_revision'] == 2
               for item in old['tasks']['items'] + old['artifacts']['items'])
    assert client.get(artifacts['figure']['download_url']).status_code == 200


def test_all_job_attempts_keep_their_status_and_stable_independent_pages(client, cloud, writer):
    base, _, result, _, _, report_url = report_ready(client)
    timestamp = '2026-10-01T12:00:00+00:00'
    statuses = ['failed', 'uncertain', 'submitting', 'running', 'completed']
    with database_connection(write=True) as db:
        for index, status in enumerate(statuses):
            job_id = f'retry-{index}'
            db.execute('INSERT INTO figure_jobs (id, analysis_run_id, renderer_version, created_at, job_json) VALUES (%s,%s,%s,%s,%s)',
                       (job_id, result['id'], 'historical-renderer', timestamp,
                        json.dumps({'id': job_id, 'status': status, 'payload': 'private'})))
    url = base.split('/files/')[0] + '/summary'
    pages = [client.get(url, params={'task_page': page, 'page_size': 2}).json() for page in range(1, 5)]
    items = [item for page in pages for item in page['tasks']['items']]
    assert pages[0]['tasks']['total'] == 8
    assert len({(item['kind'], item['id']) for item in items}) == 8
    assert {item['id']: item['status'] for item in items if item['id'].startswith('retry-')} == dict(zip([f'retry-{i}' for i in range(5)], statuses))
    assert [item['id'] for item in items if item['id'].startswith('retry-')] == [f'retry-{i}' for i in range(5)]
    assert all(page['artifacts'] == pages[0]['artifacts'] for page in pages)
    assert client.get(url, params={'task_page': 99}).json()['tasks']['items'] == []
    assert client.get(url, params={'artifact_page': 99}).json()['artifacts']['items'] == []


@pytest.mark.parametrize('query', ['task_page=0', 'task_page=1.0', 'task_page=1000001',
                                  'artifact_page=-1', 'artifact_page=abc', 'page_size=51', 'page_size=0'])
def test_summary_rejects_invalid_pagination(client, query):
    response = client.get('/api/v1/projects/missing/summary?' + query)
    assert response.status_code == 422


@pytest.mark.parametrize('role', ['user', 'admin'])
def test_summary_and_downloads_are_private_even_for_admin(client, cloud, writer, role, tmp_path):
    base, _, _, figure, explanation, report_url = report_ready(client)
    export(client, report_url, figure, explanation)
    url = base.split('/files/')[0] + '/summary'
    response = client.get(url)
    assert response.status_code == 200
    downloads = [item['download_url'] for item in response.json()['artifacts']['items']]
    orphan = ProjectStore(tmp_path / 'orphan').create_project('无主', '不可访问', 'sci')
    with account_client('other@paperassist.local', role)[0] as other:
        for path in [url, *downloads, f'/api/v1/projects/{orphan["id"]}/summary']:
            denied = other.get(path)
            assert denied.status_code == 404, denied.text
            assert denied.json()['detail']['code'] == 'project_not_found'
    with TestClient(app) as anonymous:
        assert anonymous.get(url).status_code == 401


def test_historical_renderers_download_exact_id_and_preserve_missing_changed_errors(client, cloud, writer, tmp_path):
    base, _, result, figure, _, _ = report_ready(client)
    url = base.split('/files/')[0] + '/summary'
    original = client.get(base + f'/analysis-runs/{result["id"]}/boxplot/image').content
    historical_content = original + b'\n'
    historical = {**figure, 'id': 'historical-figure', 'engine': {'id': 'historical-renderer'},
                  'size_bytes': len(historical_content), 'sha256': hashlib.sha256(historical_content).hexdigest()}
    asset = tmp_path / 'data' / 'figures' / 'historical-figure.png'
    asset.write_bytes(historical_content)
    with database_connection(write=True) as db:
        db.execute('INSERT INTO figures VALUES (%s,%s,%s,%s)',
                   (historical['id'], result['id'], 'historical-renderer', json.dumps(historical)))
    items = client.get(url).json()['artifacts']['items']
    assert len(items) == 2
    for item in items:
        downloaded = client.get(item['download_url'])
        assert downloaded.status_code == 200
        assert hashlib.sha256(downloaded.content).hexdigest() == item['sha256']
    path = next(item['download_url'] for item in items if item['id'] == historical['id'])
    assert client.get(path.replace('/historical-figure/', '/missing/')).status_code == 404
    assert client.get(path.replace(result['id'], 'another-run')).status_code == 404
    other_base, _, other_run, _, _, _ = report_ready(client)
    assert client.get(other_base + f'/analysis-runs/{other_run["id"]}/figures/historical-figure/download').status_code == 404
    asset.write_bytes(b'corrupted')
    assert client.get(path).status_code == 409
    asset.rename(asset.with_suffix('.moved'))
    assert client.get(path).status_code == 410
    # A missing asset remains a saved record, not a fabricated failed job.
    assert client.get(url).json()['artifacts']['total'] == 2


def test_counts_and_rows_share_snapshot_during_configuration_and_job_change(client, cloud, writer, monkeypatch):
    base, file, result, _, _, _ = report_ready(client)
    counted, written = Event(), Event()
    execute = DatabaseConnection.execute
    observed = []

    def observe(db, sql, parameters=()):
        rows = execute(db, sql, parameters)
        if sql.startswith('WITH runs AS'):
            observed.append(db)
            assert execute(db, 'SHOW transaction_read_only').fetchone()['transaction_read_only'] == 'on'
            if not counted.is_set():
                counted.set()
                assert written.wait(10)
        return rows

    monkeypatch.setattr(DatabaseConnection, 'execute', observe)

    def change():
        assert counted.wait(10)
        try:
            with database_connection(write=True) as db:
                db.execute('UPDATE analysis_setups SET revision=2 WHERE file_id=%s', (file['id'],))
                db.execute('INSERT INTO figure_jobs (id, analysis_run_id, renderer_version, created_at, job_json) VALUES (%s,%s,%s,%s,%s)',
                           ('concurrent', result['id'], 'concurrent-v1', '2026-10-03T10:00:00Z', json.dumps({'status': 'running'})))
        finally:
            written.set()

    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(change)
        summary = client.get(base.split('/files/')[0] + '/summary').json()
        pending.result(timeout=10)
    assert summary['tasks']['total'] == len(summary['tasks']['items']) == 3
    assert all(item['current_revision'] == 1 for item in summary['tasks']['items'] + summary['artifacts']['items'])
    assert len(observed) == 4 and all(db is observed[0] for db in observed)
    later = client.get(base.split('/files/')[0] + '/summary').json()
    assert later['tasks']['total'] == 4
    assert all(item['current_revision'] == 2 for item in later['tasks']['items'])
