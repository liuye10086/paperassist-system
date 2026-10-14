"""Batch originals flow through all existing tasks without changing v1 JSON."""
from io import BytesIO
import json
from uuid import uuid4

from openpyxl import Workbook
from psycopg.types.json import Jsonb
import pytest

from app.db.database import database_connection
from app.domain.tasks.contracts import TaskCreateRequest
from app.domain.tasks.service import TaskService
from app.domain.tasks.execution import run_word_task
from app.domain.model_usage.service import ModelUsageService
from tests.api.test_analysis import client  # noqa: F401
from tests.integration.test_boxplot_execution import queued, run as run_plot, SyntheticPlotProvider
from tests.integration.test_explanation_execution import run as run_explanation, SyntheticProvider


def add_batch_file(client, rows=None):
    from tests.api.test_projects import create_project
    from tests.domain.test_file_parse_execution import deterministic
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    project = create_project(client)
    book = Workbook()
    book.active.title = '研究 & 数据'
    for row in rows or [['指标', '组别'], [1, 'A'], [2, 'A'], [4, 'B'], [5, 'B']]:
        book.active.append(row)
    stream = BytesIO()
    book.save(stream)
    book.close()
    content = stream.getvalue()
    item = {'client_id': str(uuid4()), 'filename': 'data.xlsx', 'size_bytes': len(content)}
    base = f"/api/v1/projects/{project['id']}/file-batches"
    batch = client.post(base, headers={'Idempotency-Key': 'batch-artifacts'}, json={'items': [item]}).json()
    accepted = client.post(base + '/' + batch['id'] + '/items/' + item['client_id'],
                           files={'file': ('data.xlsx', content)})
    assert accepted.status_code == 202, accepted.text
    saved = accepted.json()
    task = saved['task']
    assert run_parse_file_task(task['id'], task['revision'], parser=deterministic)['status'] == 'succeeded'
    url = f"/api/v1/projects/{project['id']}/files/{saved['file_id']}"
    record = client.get(url + '/details').json()
    return url, record


@pytest.mark.parametrize('entry', ['legacy', 'batch'])
def test_parsed_file_all_three_tasks_workspace_retry_and_download(client, monkeypatch, entry):
    from tests.api import test_descriptive
    if entry == 'batch':
        monkeypatch.setattr(test_descriptive, 'add_file', add_batch_file)
    plot_task, owner, base, result = queued(client)
    with database_connection() as db:
        source = db.execute('SELECT input_snapshot FROM tasks WHERE id=%s', (plot_task['id'],)).fetchone()['input_snapshot']
        file = db.execute('SELECT * FROM files WHERE id=%s', (source['file']['id'],)).fetchone()
        assert set(source['file']) == {'id', 'filename', 'sha256', 'size_bytes', 'file_type'}
        if entry == 'batch':
            assert file['object_key'].startswith('files/upload-')
    provider = SyntheticPlotProvider(result, pending=False)
    finished_plot = run_plot(plot_task, provider)
    for _ in range(5):
        if finished_plot['status'] != 'running':
            break
        finished_plot = run_plot(finished_plot, provider)
    assert finished_plot['status'] == 'succeeded', finished_plot
    service = TaskService(owner)
    explanation_task, _ = service.create(plot_task['project_id'], TaskCreateRequest(
        task_type='explanation', file_id=file['id'], analysis_run_id=result['id'], expected_revision=1,
        figure_id=finished_plot['result_figure_id']), idempotency_key='batch-explanation')
    frozen = {'policy': {'model': 'test-explanation', 'prompt_version': 'analysis_explanation_v1',
        'max_output_tokens': 10000, 'timeout_seconds': 15, 'tools': [],
        'output_format': 'analysis_explanation_v1', 'price': {'version': 'synthetic-only', 'currency': 'USD',
            'model': 'test-explanation', 'input_micro_usd_per_million': 100,
            'cached_input_micro_usd_per_million': 50, 'output_micro_usd_per_million': 200,
            'cache_write_micro_usd_per_million': 100}},
        'input_token_allowance': 100000, 'task_limit_micro_usd': 1000000}
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET input_snapshot=jsonb_set(input_snapshot,'{explanation_policy}',%s) WHERE id=%s",
                   (Jsonb(frozen), explanation_task['id']))
    ModelUsageService(owner).set_budget('task', explanation_task['id'], 1000000, 0)
    finished_explanation = run_explanation(explanation_task, SyntheticProvider())
    assert finished_explanation['status'] == 'succeeded', finished_explanation
    word_task, _ = service.create(plot_task['project_id'], TaskCreateRequest(
        task_type='word_report', file_id=file['id'], analysis_run_id=result['id'], expected_revision=1,
        figure_id=finished_plot['result_figure_id'], explanation_id=finished_explanation['result_explanation_id']),
        idempotency_key='batch-report')
    # Existing five-field v1 snapshots survive failure/resume without JSON rewriting.
    from app.adapters.task_execution_store import TaskExecutionStore
    repository = TaskExecutionStore()
    lease = repository.claim(word_task['id'], word_task['revision'])
    failed = repository.fail(lease, 'task_worker_interrupted')
    with database_connection() as db:
        before = db.execute('SELECT input_snapshot FROM tasks WHERE id=%s', (word_task['id'],)).fetchone()['input_snapshot']
    url = '/api/v1/tasks/' + word_task['id']
    workspace = client.get(url + '/workspace')
    assert workspace.status_code == 200 and workspace.json()['source']['is_current'] is True
    resumed = client.post(url + '/resume', headers={'Idempotency-Key': 'batch-word-retry'}, json={
        'operation': 'retry', 'wait_id': None, 'expected_task_revision': failed['revision'],
        'input_version': failed['input_version']})
    assert resumed.status_code == 202, resumed.text
    finished_word = run_word_task(word_task['id'], resumed.json()['revision'])
    assert finished_word['status'] == 'succeeded', finished_word
    with database_connection() as db:
        after = db.execute('SELECT input_snapshot FROM tasks WHERE id=%s', (word_task['id'],)).fetchone()['input_snapshot']
        assert before == after
    workspace = client.get(url + '/workspace').json()
    assert workspace['artifacts']['report'] is not None
    assert client.get(workspace['artifacts']['report']['download_url']).content.startswith(b'PK')
    assert client.get(base + '/download').status_code == 200
    assert client.get(f"/api/v1/projects/{plot_task['project_id']}/tasks").status_code == 200
