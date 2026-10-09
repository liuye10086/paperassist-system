"""Synthetic paid receipts exercise frozen aliases through both workers and Word."""
import copy
import json
from io import BytesIO

import pytest
from psycopg.types.json import Jsonb
from openpyxl import Workbook

from app.core.exceptions import StorageError
from app.db.database import database_connection
from app.domain.external_processing import disclosure, freeze_confirmation
from app.domain.tasks.contracts import TaskCreateRequest
from app.domain.tasks.service import TaskService
from tests.api.test_analysis import client  # noqa: F401
from tests.integration.test_boxplot_execution import queued, run, SyntheticPlotProvider
from tests.integration.test_explanation_execution import SyntheticProvider


def attach_confirmation(task, owner, task_type):
    with database_connection(write=True) as db:
        snapshot = db.execute('SELECT input_snapshot FROM tasks WHERE id=%s', (task['id'],)).fetchone()['input_snapshot']
        preview = disclosure(snapshot, task_type, owner)
        labels = {item['key']: item['value'] for item in preview['labels']}
        labels.update(numeric_name='本次指标', unit='本次单位')
        if 'group_name' in labels:
            labels['group_name'] = '本次分组'
        for key in labels:
            if key.startswith('group:'):
                labels[key] = '匿名' + key
        if task_type == 'explanation':
            labels['figure_title'] = '本次解释标题'
        external = freeze_confirmation(snapshot, task_type, owner,
            {'version': 1, 'confirmed': True, 'source_digest': preview['source_digest'], 'labels': labels})
        db.execute("UPDATE tasks SET input_snapshot=jsonb_set(input_snapshot,'{external_processing}',%s) WHERE id=%s",
                   (Jsonb(external), task['id']))
    return external


class ConfirmedPlotProvider(SyntheticPlotProvider):
    def create_plot(self, *, instructions, **kwargs):
        self.instructions = instructions
        return super().create_plot(instructions=instructions, **kwargs)

    def download(self, file_id, container_id, limit, *, policy):
        value = super().download(file_id, container_id, limit, policy=policy)
        if file_id == 'cfile_result':
            manifest = json.loads(value)
            manifest.pop('analysis_run_id')
            manifest.pop('source_sha256')
            for index, group in enumerate(manifest['groups']):
                group['label'] = self.payload['groups'][index]['label']
            value = json.dumps(manifest, ensure_ascii=False).encode('utf-8')
        return value


class ConfirmedExplanationProvider(SyntheticProvider):
    def create(self, *, instructions, **kwargs):
        self.instructions = instructions
        return super().create(instructions=instructions, **kwargs)


def test_confirmed_workers_preserve_aliases_and_report_checks(client, monkeypatch):
    from app.domain.model_usage.service import ModelUsageService
    from app.domain.reports import validate_sources
    from app.domain.tasks.explanation_execution import run_explanation_task
    from tests.domain.test_explanation_policy import execution_policy
    from tests.api.test_analysis import selection
    from tests.api.test_descriptive import run as statistics_run
    from tests.integration import test_boxplot_execution
    project = client.post('/api/v1/projects', json={'name': 'PRIVATE_PROJECT_SENTINEL',
        'research_topic': 'PRIVATE_TOPIC_SENTINEL', 'project_type': 'sci'}).json()
    book = Workbook()
    book.active.title = 'PRIVATE_SHEET_SENTINEL'
    rows = [['PRIVATE_NUMERIC_SENTINEL', 'PRIVATE_GROUP_SENTINEL', 'PRIVATE_IDENTITY_COLUMN'],
            [1, 'PRIVATE_GROUP_A', 'PRIVATE_PERSON_A'], [2, 'PRIVATE_GROUP_A', 'PRIVATE_PERSON_B'],
            [4, 'PRIVATE_GROUP_B', 'PRIVATE_PERSON_C'], [None, 'PRIVATE_GROUP_B', 'PRIVATE_PERSON_D']]
    for row in rows:
        book.active.append(row)
    buffer = BytesIO()
    book.save(buffer)
    book.close()
    record = client.post(f'/api/v1/projects/{project["id"]}/files',
        files={'file': ('PRIVATE_FILENAME.xlsx', buffer.getvalue())}).json()['file']
    base = f'/api/v1/projects/{project["id"]}/files/{record["id"]}'
    setup = client.put(base + '/analysis-setup', json=selection(expected_revision=0,
        sheet_name='PRIVATE_SHEET_SENTINEL', unit='PRIVATE_UNIT_SENTINEL'))
    assert setup.status_code == 200, setup.text
    result = statistics_run(client, base)
    monkeypatch.setattr(test_boxplot_execution, 'boxplot_task_input', lambda unused: (
        project['id'], TaskCreateRequest(task_type='boxplot', file_id=record['id'],
        analysis_run_id=result['id'], expected_revision=1), base, result))
    task, owner, base, result = queued(client)
    external = attach_confirmation(task, owner, 'boxplot')
    provider = ConfirmedPlotProvider(result, pending=False)
    current = task
    for _ in range(4):
        current = run(current, provider)
        assert current is not None, 'Confirmed worker must publish using the confirmed material contract'
        if current['status'] == 'succeeded':
            break
    assert current['status'] == 'succeeded', current
    assert set(provider.payload) == {'labels', 'values', 'groups'}
    assert provider.payload['values'] == [1, 2, 4]
    assert [group['values'] for group in provider.payload['groups']] == [[1, 2], [4]]
    assert 'PRIVATE_' not in json.dumps(provider.payload, ensure_ascii=False)
    assert 'analysis_run_id' not in provider.instructions
    url = base + '/analysis-runs/' + result['id']
    figure = client.get(url + '/boxplot').json()['figure']
    assert figure['external_processing'] == external
    assert figure['analysis_run_id'] == result['id']
    assert figure['title'] == '图 1. 本次指标箱线图'
    from app.adapters.task_execution_store import TaskExecutionStore
    changed_figure = copy.deepcopy(figure)
    changed_figure['external_processing']['labels']['numeric_name'] = 'unapproved'
    expected = {key: figure[key] for key in ('title', 'x_label', 'y_label', 'caption', 'overall', 'groups', 'series')}
    with pytest.raises(StorageError):
        TaskExecutionStore._validate_boxplot_figure({'result': result, 'external_processing': external},
            changed_figure, provider.png, expected)
    inherited = client.get(url + '/explanation/disclosure').json()
    inherited_labels = {item['key']: item['value'] for item in inherited['labels']}
    assert inherited_labels['numeric_name'] == '本次指标' and inherited_labels['unit'] == '本次单位'
    task, _ = TaskService(owner).create(base.split('/')[4], TaskCreateRequest(
        task_type='explanation', file_id=result['file_id'], analysis_run_id=result['id'],
        expected_revision=1, figure_id=figure['id']), idempotency_key='confirmed-explanation')
    confirmed = attach_confirmation(task, owner, 'explanation')
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET input_snapshot=jsonb_set(input_snapshot,'{explanation_policy}',%s) WHERE id=%s",
                   (Jsonb(execution_policy()), task['id']))
    ModelUsageService(owner).set_budget('task', task['id'], 1000000, 0)
    explanation_provider = ConfirmedExplanationProvider()
    completed = run_explanation_task(task['id'], 1, provider_factory=lambda: explanation_provider)
    assert completed['status'] == 'succeeded', completed
    outbound = explanation_provider.posts[0][1]
    assert 'sheet' not in outbound['facts'] and 'analysis_run_id' not in outbound
    assert 'sheet' not in explanation_provider.instructions
    assert 'PRIVATE_' not in json.dumps(outbound, ensure_ascii=False)
    explanation = client.get(url + '/explanation').json()['explanation']
    assert explanation['provenance']['external_processing'] == confirmed
    assert '本次指标' in explanation['sections'][0]['text']
    validate_sources(result, figure, explanation)
    changed = copy.deepcopy(explanation)
    changed['sections'][0]['evidence'][0]['value'] = 'tampered'
    with pytest.raises(StorageError):
        validate_sources(result, figure, changed)
    changed = copy.deepcopy(explanation)
    changed['provenance']['external_processing']['labels']['unknown'] = 'unapproved'
    with pytest.raises(StorageError):
        validate_sources(result, figure, changed)
    report = client.post(url + '/report', json={'expected_revision': 1, 'figure_id': figure['id'],
                                               'explanation_id': explanation['id']})
    assert report.status_code == 202, report.text
    from app.domain.tasks.execution import run_word_task
    report_task = report.json()['task']
    done = run_word_task(report_task['id'], report_task['revision'])
    assert done['status'] == 'succeeded', done
    assert client.get(url + '/report').json()['report'] is not None


def test_configuration_budget_recovery_preserves_frozen_confirmation(client, monkeypatch):
    from app.domain import plot_policy
    task, owner, base, result = queued(client)
    external = attach_confirmation(task, owner, 'boxplot')
    with database_connection(write=True) as db:
        frozen = db.execute('SELECT input_snapshot FROM tasks WHERE id=%s', (task['id'],)).fetchone()['input_snapshot']['boxplot_policy']
        db.execute("UPDATE tasks SET input_snapshot=input_snapshot-'boxplot_policy' WHERE id=%s", (task['id'],))
    provider = ConfirmedPlotProvider(result, pending=False)
    waiting = run(task, provider)
    assert waiting['status'] == 'waiting_confirmation' and not provider.posts
    monkeypatch.setattr(plot_policy, 'get_execution_policy', lambda: frozen)
    response = client.post('/api/v1/tasks/' + task['id'] + '/retry', json={'expected_revision': waiting['revision']})
    assert response.status_code == 202, response.text
    current = response.json()
    assert current['id'] == task['id']
    with database_connection() as db:
        restored = db.execute('SELECT input_snapshot FROM tasks WHERE id=%s', (task['id'],)).fetchone()['input_snapshot']
        assert restored['external_processing'] == external
    for _ in range(4):
        current = run(current, provider)
        assert current is not None
        if current['status'] == 'succeeded':
            break
    assert current['status'] == 'succeeded', current
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls WHERE task_id=%s', (task['id'],)).fetchone()['n'] == 1
        assert db.execute('SELECT input_snapshot FROM tasks WHERE id=%s', (task['id'],)).fetchone()['input_snapshot']['external_processing'] == external


def test_long_original_labels_can_be_replaced_before_material_rebuild(client, monkeypatch):
    from tests.api.test_boxplot import prepared
    from tests.integration import test_boxplot_execution
    base, record, result, _ = prepared(client, [['PRIVATE_' + 'n' * 180, 'PRIVATE_' + 'g' * 180],
        [1, 'PRIVATE_' + 'a' * 180], [2, 'PRIVATE_' + 'b' * 180]])
    monkeypatch.setattr(test_boxplot_execution, 'boxplot_task_input', lambda unused: (
        base.split('/')[4], TaskCreateRequest(task_type='boxplot', file_id=record['id'],
        analysis_run_id=result['id'], expected_revision=1), base, result))
    task, owner, _, _ = queued(client)
    attach_confirmation(task, owner, 'boxplot')
    from app.adapters.task_execution_store import TaskExecutionStore
    repository = TaskExecutionStore()
    lease = repository.claim(task['id'], 1, task_type='boxplot')
    _, _, payload, _ = repository.load_boxplot(lease)
    assert payload['values'] == [1, 2]
    assert 'PRIVATE_' not in json.dumps(payload, ensure_ascii=False)
