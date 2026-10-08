"""Word HTTP accepts work without executing it; all reads remain observational."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.db.database import database_connection
from app.domain.tasks.service import TaskService
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_boxplot import cloud  # noqa: F401
from tests.integration.test_explanations import writer  # noqa: F401
from tests.integration.test_reports import report_ready


def submit(client, url, figure, explanation, **kwargs):
    return client.post(url, json={'expected_revision': figure['setup_revision'],
        'figure_id': figure['id'], 'explanation_id': explanation['id']}, **kwargs)


def fail_task(client, task):
    service = TaskService(client.get('/api/v1/auth/me').json()['user']['id'])
    running = service.transition(task['id'], expected_revision=task['revision'], status='running')
    return service.transition(task['id'], expected_revision=running['revision'], status='failed', reason_code='execution_failed')


def test_post_accepts_word_without_render_and_read_recovers_exact_task(client, cloud, writer, monkeypatch):
    *_, figure, explanation, url = report_ready(client)
    def forbidden(*args, **kwargs):
        raise AssertionError('HTTP must not render Word')
    monkeypatch.setattr('app.domain.reports.build_report', forbidden)
    assert client.get(url).json()['task'] is None
    response = submit(client, url, figure, explanation)
    assert response.status_code == 202, response.text
    state = response.json()
    assert state['report'] is None and state['task']['status'] == 'queued'
    assert state['task']['task_type'] == 'word_report'
    before = client.get('/api/v1/tasks/' + state['task']['id'] + '/events').json()
    for _ in range(3):
        assert client.get(url).json()['task'] == state['task']
    assert client.get('/api/v1/tasks/' + state['task']['id'] + '/events').json() == before
    assert submit(client, url, figure, explanation).json()['task']['id'] == state['task']['id']
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM reports').fetchone()['n'] == 0
        assert db.execute('SELECT count(*) AS n FROM tasks').fetchone()['n'] == 1


def test_word_http_idempotency_header_is_validated_and_scoped_to_input(client, cloud, writer):
    *_, figure, explanation, url = report_ready(client)
    header = {'Idempotency-Key': 'same-word-request'}
    first = submit(client, url, figure, explanation, headers=header)
    assert first.status_code == 202
    assert submit(client, url, figure, explanation, headers=header).json()['task'] == first.json()['task']
    *_, other_figure, other_explanation, other_url = report_ready(client)
    # Both fixtures have distinct projects, so the same key is independent.
    assert submit(client, other_url, other_figure, other_explanation, headers=header).status_code == 202
    for key in ('', 'has space', 'a' * 129):
        assert submit(client, url, figure, explanation, headers={'Idempotency-Key': key}).status_code == 422


def test_failed_word_retry_is_explicit_atomic_and_repeated_revision_is_idempotent(client, cloud, writer):
    *_, figure, explanation, url = report_ready(client)
    failed = fail_task(client, submit(client, url, figure, explanation).json()['task'])
    endpoint = '/api/v1/tasks/' + failed['id'] + '/retry'
    with ThreadPoolExecutor(max_workers=3) as pool:
        responses = list(pool.map(lambda _: client.post(endpoint, json={'expected_revision': failed['revision']}), range(3)))
    assert all(response.status_code == 202 for response in responses)
    tasks = [response.json() for response in responses]
    assert {task['revision'] for task in tasks} == {failed['revision'] + 1}
    assert all(task['status'] == 'queued' for task in tasks)
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM task_outbox').fetchone()['n'] == 2
        assert db.execute('SELECT count(*) AS n FROM task_attempts').fetchone()['n'] == 1
    assert client.post(endpoint, json={'expected_revision': 1}).status_code == 409
    assert client.post(endpoint, json={'expected_revision': True}).status_code == 422


def test_retry_rejects_changed_sources_and_foreign_tasks(client, cloud, writer):
    base, _, result, figure, explanation, url = report_ready(client)
    failed = fail_task(client, submit(client, url, figure, explanation).json()['task'])
    client.put(base + '/analysis-setup', json={**result['selection'], 'expected_revision': 1, 'unit': 'changed'})
    endpoint = '/api/v1/tasks/' + failed['id'] + '/retry'
    assert client.post(endpoint, json={'expected_revision': failed['revision']}).status_code == 409
    assert client.get(url).json()['task']['status'] == 'failed'
    assert client.post('/api/v1/tasks/missing/retry', json={'expected_revision': 3}).status_code == 404


def test_legacy_cached_report_rechecks_revision_after_context_and_keeps_download(client, cloud, writer, monkeypatch):
    from app.adapters.storage import get_project_store
    from app.domain import reports
    base, _, result, figure, explanation, url = report_ready(client)
    parts = base.split('/')
    state, _ = reports.generate_report(parts[4], parts[6], result['id'],
        reports.ReportRequest(expected_revision=1, figure_id=figure['id'], explanation_id=explanation['id']), get_project_store())
    download = url + '/' + state['report']['id'] + '/download'
    original_bytes = client.get(download).content
    cached = submit(client, url, figure, explanation)
    assert cached.status_code == 200 and cached.json()['task'] is None
    assert cached.json()['report'] == state['report']
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM tasks').fetchone()['n'] == 0
    original_context = reports.context
    def changed(*args):
        value = original_context(*args)
        client.put(base + '/analysis-setup', json={**result['selection'], 'expected_revision': 1, 'unit': 'changed'})
        return value
    monkeypatch.setattr(reports, 'context', changed)
    response = submit(client, url, figure, explanation)
    assert response.status_code == 409, response.text
    assert client.get(download).content == original_bytes


def test_retry_hides_foreign_owner_and_rejects_non_word_task(client, cloud, writer):
    from tests.integration.test_project_ownership import account_client
    from tests.helpers.tasks import boxplot_task_input
    *_, figure, explanation, url = report_ready(client)
    failed = fail_task(client, submit(client, url, figure, explanation).json()['task'])
    stranger, _ = account_client('report-stranger@example.test')
    try:
        response = stranger.post('/api/v1/tasks/' + failed['id'] + '/retry', json={'expected_revision': failed['revision']})
        assert response.status_code == 404
    finally:
        stranger.close()
    project_id, request, _, _ = boxplot_task_input(client)
    service = TaskService(client.get('/api/v1/auth/me').json()['user']['id'])
    other, _ = service.create(project_id, request, idempotency_key='boxplot-only')
    response = client.post('/api/v1/tasks/' + other['id'] + '/retry', json={'expected_revision': other['revision']})
    assert response.status_code == 409
