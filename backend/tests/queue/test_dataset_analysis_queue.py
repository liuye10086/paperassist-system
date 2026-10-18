"""Full dataset lineage with real Linux leases and synthetic-only SDK transports."""
from tests.helpers.statistics import statistics_post
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
from zipfile import ZipFile

import pytest

from app.db.database import database_connection
from app.domain.model_usage.service import ModelUsageService
from tests.api.test_analysis import add_file, client, selection  # noqa: F401
from tests.queue.test_dataset_queue import create_version, get_version, wait_task
from tests.queue.test_real_worker import isolated_worker_stack, worker_stack  # noqa: F401

pytestmark = pytest.mark.skipif(os.environ.get('PAPERASSIST_RUN_QUEUE_TESTS') != '1',
                               reason='Explicit isolated dataset analysis queue test is disabled.')


def synthetic_policies(tmp_path, monkeypatch):
    price = {'version': 'dataset-synthetic-only', 'input_micro_usd_per_million': 100,
             'cached_input_micro_usd_per_million': 50, 'output_micro_usd_per_million': 200}
    policies = {
        'PAPERASSIST_PLOT_POLICY_FILE': {
            'policy': {'model': 'test-plot', 'prompt_version': 'openai_boxplot_v1',
                'max_output_tokens': 16000, 'output_format': 'text', 'tools': ['code_interpreter'],
                'price': {**price, 'model': 'test-plot'}}, 'input_token_allowance': 100000,
            'task_limit_micro_usd': 1000000, 'tool_reserve_micro_usd': 1000,
            'tool_reserve_version': 'synthetic-tool-only'},
        'PAPERASSIST_EXPLANATION_POLICY_FILE': {
            'policy': {'model': 'test-model', 'prompt_version': 'analysis_explanation_v1',
                'max_output_tokens': 10000, 'output_format': 'analysis_explanation_v1',
                'price': {**price, 'model': 'test-model'}}, 'input_token_allowance': 100000,
            'task_limit_micro_usd': 1000000},
    }
    for name, value in policies.items():
        path = tmp_path / (name.lower() + '.json')
        path.write_text(json.dumps(value), encoding='utf-8')
        monkeypatch.setenv(name, str(path))
    monkeypatch.setenv('OPENAI_API_KEY', 'isolated-test-key')
    monkeypatch.delenv('OPENAI_API_KEY_FILE', raising=False)


def combined_override(tmp_path):
    names = ('dataset_analysis_bootstrap.py', 'plot_bootstrap.py', 'explanation_bootstrap.py')
    override = tmp_path / 'dataset-analysis-worker.json'
    override.write_text(json.dumps({'services': {'worker': {
        'command': ['python', '/app/dataset_analysis_bootstrap.py', 'worker'],
        'volumes': [{'type': 'bind', 'source': str(Path(__file__).with_name(name).resolve()),
                     'target': '/app/' + name, 'read_only': True} for name in names],
    }}}), encoding='utf-8')
    return override


def dataset_confirmation(client, url, source):
    response = client.get(url + '/disclosure')
    assert response.status_code == 200, response.text
    disclosure = response.json()
    assert disclosure['version'] == 2
    assert disclosure['source']['dataset_version'] == source['dataset_version']
    assert disclosure['source']['sheet_name'] == source['sheet_name']
    assert set(disclosure['source']) == {'filename', 'sheet_name', 'dataset_version'}
    return {'version': 2, 'confirmed': True, 'source_digest': disclosure['source_digest'],
            'labels': {item['key']: item['value'] for item in disclosure['labels']}}


def saved_analysis(client, base, dataset_id, revision):
    response = client.put(base + '/analysis-setup',
                          json=selection(dataset_id=dataset_id, expected_revision=revision))
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved['source']['dataset_id'] == dataset_id
    response = statistics_post(client, base + '/analysis-runs', json={'expected_revision': saved['revision']})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['source'] == saved['source']
    return saved, result


def test_full_dataset_chain_candidate_and_receipt_recovery_without_original_reads(
        client, isolated_worker_stack, tmp_path, monkeypatch):
    stack = isolated_worker_stack
    synthetic_policies(tmp_path, monkeypatch)
    rows = [['测量值', '组别']] + [[value, 'A' if value % 2 else 'B'] for value in range(1, 31)]
    base, file = add_file(client, rows)
    project_id = base.split('/')[4]
    original = client.get(base + '/download').content
    owner = client.get('/api/v1/auth/me').json()['user']['id']
    budgets = ModelUsageService(owner)
    for scope, key in (('user', owner), ('project', project_id)):
        budgets.set_budget(scope, key, 10000000, 0)
    version = create_version(client, base, 0)
    override = combined_override(tmp_path)
    worker_stack.compose(stack, ['--file', str(override), 'up', '-d', '--wait', '--wait-timeout', '90'], timeout=180)
    assert wait_task(client, version['task']['id'])['status'] == 'succeeded'
    first = get_version(client, base, version['id'])
    dataset = first['datasets'][0]

    # Both HTTP statistics and the independent worker fail the test if any new
    # dataset path tries to reread the original. Structure extraction stays real.
    guard = tmp_path / 'data' / '.forbid-original-reader'
    guard.write_text('enabled', encoding='ascii')
    from app.adapters.file_objects import LocalFileObjects
    original_reader = LocalFileObjects.original

    def no_original(self, record):
        raise AssertionError('New dataset HTTP path read the original.')

    monkeypatch.setattr(LocalFileObjects, 'original', no_original)
    saved, result = saved_analysis(client, base, dataset['id'], 0)
    source = result['source']
    assert result['overall']['n'] == 30 and result['overall']['mean'] == 15.5
    assert result['engine']['id'] == 'descriptive_statistics_dataset_v1'
    run_url = base + '/analysis-runs/' + result['id']
    plot_url = run_url + '/boxplot'
    response = client.post(plot_url, headers={'Idempotency-Key': 'plot-queue-candidate'}, json={
        'expected_revision': saved['revision'], 'external_processing': dataset_confirmation(client, plot_url, source)})
    assert response.status_code == 202, response.text
    plot = wait_task(client, response.json()['task']['id'], timeout=150)
    assert plot['status'] == 'succeeded' and plot['current_attempt'] == 2, plot
    figure_response = client.get(plot_url)
    assert figure_response.status_code == 200, figure_response.text
    figure = figure_response.json()['figure']
    assert figure['source'] == source
    assert (tmp_path / 'data' / ('.crash-' + plot['id'])).exists()

    explanation_url = run_url + '/explanation'
    response = client.post(explanation_url, headers={'Idempotency-Key': 'queue-receipt'}, json={
        'expected_revision': saved['revision'], 'figure_id': figure['id'],
        'external_processing': dataset_confirmation(client, explanation_url, source)})
    assert response.status_code == 202, response.text
    explained = wait_task(client, response.json()['task']['id'], timeout=150)
    assert explained['status'] == 'succeeded' and explained['current_attempt'] == 2, explained
    explanation_response = client.get(explanation_url)
    assert explanation_response.status_code == 200, explanation_response.text
    explanation = explanation_response.json()['explanation']
    assert explanation['source'] == source
    assert (tmp_path / 'data' / ('.crash-' + explained['id'])).exists()

    report_url = run_url + '/report'
    response = client.post(report_url, headers={'Idempotency-Key': 'dataset-word'}, json={
        'expected_revision': saved['revision'], 'figure_id': figure['id'], 'explanation_id': explanation['id']})
    assert response.status_code == 202, response.text
    word = wait_task(client, response.json()['task']['id'])
    assert word['status'] == 'succeeded', word
    report_response = client.get(report_url)
    assert report_response.status_code == 200, report_response.text
    report = report_response.json()['report']
    assert report['source'] == source
    downloaded = client.get(report_url + '/' + report['id'] + '/download')
    assert downloaded.status_code == 200
    assert sha256(downloaded.content).hexdigest() == report['sha256']
    with ZipFile(BytesIO(downloaded.content)) as archive:
        document = archive.read('word/document.xml').decode()
        assert source['sheet_name'].replace('&', '&amp;') in document
        assert '数据版本' in document

    for task in (plot, explained, word):
        assert task['input_version']['source'] == source
        workspace = client.get('/api/v1/tasks/' + task['id'] + '/workspace')
        assert workspace.status_code == 200, workspace.text
        assert workspace.json()['source']['dataset_source'] == source
        assert workspace.json()['source']['is_current']
    with database_connection() as db:
        for task in (plot, explained, word):
            persisted = db.execute('SELECT * FROM tasks WHERE id=%s', (task['id'],)).fetchone()
            assert persisted['workflow_version'] == task['task_type'] + '_v2'
            assert persisted['input_snapshot']['source'] == source
            assert set(persisted['input_snapshot']['file']) == {'id', 'filename', 'sha256', 'size_bytes', 'file_type'}
        calls = db.execute('SELECT * FROM model_calls ORDER BY created_at').fetchall()
        assert len(calls) == 2 and all(call['status'] == 'completed' for call in calls)
    plot_calls = (tmp_path / 'data' / ('.calls-' + plot['id'])).read_text().splitlines()
    explanation_calls = (tmp_path / 'data' / ('.calls-' + explained['id'])).read_text().splitlines()
    assert plot_calls.count('POST response') == 1
    assert explanation_calls.count('POST') == 1
    assert not (tmp_path / 'data' / '.unexpected-original-read').exists()

    monkeypatch.setattr(LocalFileObjects, 'original', original_reader)
    guard.unlink()
    second = create_version(client, base, 1)
    assert wait_task(client, second['task']['id'])['status'] == 'succeeded'
    second_dataset = get_version(client, base, second['id'])['datasets'][0]
    state = client.get(base + '/analysis-result').json()
    assert state['is_current'] and state['result']['source'] == source
    assert client.get(base + '/analysis-setup').json() == saved
    saved2, result2 = saved_analysis(client, base, second_dataset['id'], saved['revision'])
    assert saved2['revision'] == 2 and result2['id'] != result['id']
    assert result2['source']['dataset_version'] == 2 and result2['overall'] == result['overall']
    workspace = client.get('/api/v1/tasks/' + word['id'] + '/workspace').json()
    assert not workspace['source']['is_current']
    assert workspace['source']['dataset_source'] == source and workspace['artifacts']['report']
    assert client.get(workspace['artifacts']['report']['download_url']).content == downloaded.content
    assert client.get(base + '/download').content == original
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 2
