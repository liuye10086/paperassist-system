"""Real budget denial and HTTP recovery in disposable PostgreSQL, with synthetic models."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from app.db.database import database_connection
from app.domain.explanation_policy import get_execution_policy as read_explanation_policy
from app.domain.model_usage.contracts import ModelPolicy
from app.domain.model_usage.pricing import reserve_micro_usd
from app.domain.model_usage.service import ModelUsageService
from app.domain.tasks.execution import run_boxplot_task, run_explanation_task
from tests.api.test_analysis import client, selection  # noqa: F401
from tests.api.test_boxplot import cloud, generate  # noqa: F401
from tests.api.test_descriptive import run as statistics_run
from tests.api.test_external_processing import confirmation
from tests.integration.test_explanation_execution import SyntheticProvider
from tests.integration.test_explanations import writer  # noqa: F401
from tests.integration.test_external_execution import ConfirmedPlotProvider
from tests.integration.test_reports import export, report_ready


@pytest.fixture
def historical_artifacts(client, cloud, writer, monkeypatch):
    base, _, _, figure, explanation, report_url = report_ready(client)
    response = export(client, report_url, figure, explanation)
    assert response.status_code == 200, response.text
    report = response.json()['report']
    # The legacy writer fixture only prepares old material. New HTTP acceptance
    # must read the actual temporary policy file rather than its policy stub.
    monkeypatch.setattr('app.domain.explanation_policy.get_execution_policy', read_explanation_policy)
    plot_url = report_url.replace('/report', '/boxplot')
    data = Path(os.environ['PAPERASSIST_DATA_DIR'])

    def snapshot():
        with database_connection() as db:
            original_json = {
                table: db.execute(f'SELECT {column} FROM {table} WHERE id=%s', (item['id'],))
                    .fetchone()[column].encode('utf-8')
                for table, column, item in [
                    ('figures', 'figure_json', figure),
                    ('explanations', 'explanation_json', explanation),
                    ('reports', 'report_json', report)]}
        png = client.get(plot_url + '/image')
        word = client.get(report_url + '/' + report['id'] + '/download')
        assert png.status_code == word.status_code == 200
        assert png.content == (data / 'figures' / (figure['id'] + '.png')).read_bytes()
        assert word.content == (data / 'reports' / (report['id'] + '.docx')).read_bytes()
        assert hashlib.sha256(png.content).hexdigest() == figure['sha256']
        assert hashlib.sha256(word.content).hexdigest() == report['sha256']
        assert cloud.calls == writer.calls == []
        return original_json, png.content, word.content

    before = snapshot()
    return base, snapshot, before


def temporary_policy(task_type):
    from app.domain.explanation_content import VERSION
    plot = task_type == 'boxplot'
    model = 'test-plot' if plot else 'test-explanation'
    value = {'policy': {
        'model': model, 'prompt_version': 'openai_boxplot_v1' if plot else VERSION,
        'max_output_tokens': 16000 if plot else 10000, 'timeout_seconds': 15,
        'tools': ['code_interpreter'] if plot else [],
        'output_format': 'text' if plot else 'analysis_explanation_v1',
        'price': {'version': 'budget-recovery-synthetic-only', 'currency': 'USD', 'model': model,
            'input_micro_usd_per_million': 100, 'cached_input_micro_usd_per_million': 50,
            'output_micro_usd_per_million': 200, 'cache_write_micro_usd_per_million': 100}},
        'input_token_allowance': 100000, 'task_limit_micro_usd': 1000000}
    if plot:
        value.update(tool_reserve_micro_usd=1000, tool_reserve_version='synthetic-tool-only')
    return value


def assert_task_admission_empty(task_id):
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls WHERE task_id=%s',
                          (task_id,)).fetchone()['n'] == 0
        assert db.execute('''SELECT count(*) AS n FROM budget_reservations r
            JOIN model_calls c ON c.id=r.call_id WHERE c.task_id=%s''', (task_id,)).fetchone()['n'] == 0


@pytest.mark.parametrize('task_type', ['boxplot', 'explanation'])
@pytest.mark.parametrize('limited_scope', ['user', 'project', 'task'])
def test_budget_denial_http_resume_completes_original_task_and_preserves_old_bytes(
        client, historical_artifacts, postgres_schema, tmp_path, monkeypatch, task_type, limited_scope):
    base, old_snapshot, old_bytes = historical_artifacts
    owner = client.get('/api/v1/auth/me').json()['user']['id']
    project = base.split('/')[4]
    changed = client.put(base + '/analysis-setup', json=selection(expected_revision=1, unit='mmol/L'))
    assert changed.status_code == 200, changed.text
    result = statistics_run(client, base, 2)
    plot_url = base + '/analysis-runs/' + result['id'] + '/boxplot'
    url = plot_url if task_type == 'boxplot' else plot_url.replace('/boxplot', '/explanation')
    body = {'expected_revision': 2}
    if task_type == 'explanation':
        figure = generate(client, plot_url, revision=2)
        body['figure_id'] = figure['id']
    body['external_processing'] = confirmation(client, url)
    frozen = temporary_policy(task_type)
    policy_file = tmp_path / (task_type + '-policy.json')
    policy_file.write_text(json.dumps(frozen), encoding='utf-8')
    env_key = 'PAPERASSIST_PLOT_POLICY_FILE' if task_type == 'boxplot' else 'PAPERASSIST_EXPLANATION_POLICY_FILE'
    monkeypatch.setenv(env_key, str(policy_file))
    accepted = client.post(url, json=body, headers={'Idempotency-Key': 'new-budget-recovery'})
    assert accepted.status_code == 202, accepted.text
    task = accepted.json()['task']
    with database_connection() as db:
        snapshot = db.execute('SELECT input_snapshot FROM tasks WHERE id=%s',
                              (task['id'],)).fetchone()['input_snapshot']
    policy_key = 'boxplot_policy' if task_type == 'boxplot' else 'explanation_policy'
    assert snapshot[policy_key] == frozen
    assert snapshot['external_processing']['version'] == 1
    required = reserve_micro_usd(ModelPolicy.model_validate(frozen['policy']),
        frozen['input_token_allowance'], frozen.get('tool_reserve_micro_usd', 0))
    service = ModelUsageService(owner, postgres_schema)
    scopes = {'user': owner, 'project': project, 'task': task['id']}
    for scope, key in scopes.items():
        current = service.get_budget(scope, key)
        service.set_budget(scope, key, required - 1 if scope == limited_scope else 1000000,
                           current['revision'])
    provider = ConfirmedPlotProvider(result, pending=False) if task_type == 'boxplot' else SyntheticProvider()
    executor = run_boxplot_task if task_type == 'boxplot' else run_explanation_task

    def execute(current):
        return executor(current['id'], current['revision'], config=postgres_schema,
                        provider_factory=lambda: provider)

    waiting = execute(task)
    assert waiting['id'] == task['id'] and waiting['status'] == 'waiting_confirmation'
    assert waiting['reason_code'] == 'budget_exceeded' and waiting['error_code'] == 'model_budget_exceeded'
    assert waiting['current_attempt'] == 1
    assert provider.posts == []
    assert_task_admission_empty(task['id'])
    assert old_snapshot() == old_bytes
    workspace_response = client.get('/api/v1/tasks/' + task['id'] + '/workspace')
    assert workspace_response.status_code == 200, workspace_response.text
    workspace = workspace_response.json()
    wait = workspace['wait']
    assert workspace['allowed_actions'] == ['resume']
    assert wait['kind'] == 'budget_confirmation' and wait['status'] == 'open'
    assert wait['task_revision'] == waiting['revision']
    resume_body = {'operation': 'resume', 'wait_id': wait['id'],
        'expected_task_revision': workspace['task']['revision'],
        'input_version': workspace['task']['input_version']}
    # Change only the bottleneck budget in this fixture-owned schema.
    key = scopes[limited_scope]
    budget_before = {scope: service.get_budget(scope, scope_key) for scope, scope_key in scopes.items()}
    service.set_budget(limited_scope, key, required, budget_before[limited_scope]['revision'])
    for scope, scope_key in scopes.items():
        if scope != limited_scope:
            assert service.get_budget(scope, scope_key) == budget_before[scope]
    endpoint = '/api/v1/tasks/' + task['id'] + '/resume'
    headers = {'Idempotency-Key': 'resume-after-budget-increase'}
    resumed_response = client.post(endpoint, json=resume_body, headers=headers)
    assert resumed_response.status_code == 202, resumed_response.text
    resumed = resumed_response.json()
    assert resumed['id'] == task['id'] and resumed['status'] == 'queued'
    assert resumed['revision'] == waiting['revision'] + 1
    repeated = client.post(endpoint, json=resume_body, headers=headers)
    assert repeated.status_code == 202 and repeated.json() == resumed
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM task_resume_requests WHERE task_id=%s',
                          (task['id'],)).fetchone()['n'] == 1
        outbox = db.execute('SELECT task_revision FROM task_outbox WHERE task_id=%s ORDER BY task_revision',
                            (task['id'],)).fetchall()
        assert [row['task_revision'] for row in outbox] == [task['revision'], resumed['revision']]
        saved_wait = db.execute('SELECT * FROM task_waits WHERE id=%s', (wait['id'],)).fetchone()
        assert saved_wait['status'] == 'resolved'
        assert saved_wait['resolved_task_revision'] == resumed['revision']
    assert provider.posts == []
    assert_task_admission_empty(task['id'])
    assert old_snapshot() == old_bytes
    current = resumed
    for _ in range(4):
        current = execute(current)
        assert current is not None
        if current['status'] == 'succeeded':
            break
    assert current['status'] == 'succeeded' and current['id'] == task['id']
    assert current['current_attempt'] == 2
    if task_type == 'boxplot':
        assert provider.posts == ['container', 'upload', 'response']
        artifact_id = current['result_figure_id']
        table, column = 'figures', 'figure_json'
    else:
        assert len(provider.posts) == 1
        artifact_id = current['result_explanation_id']
        table, column = 'explanations', 'explanation_json'
    with database_connection() as db:
        calls = db.execute('SELECT * FROM model_calls WHERE task_id=%s', (task['id'],)).fetchall()
        assert len(calls) == 1
        call = calls[0]
        assert call['user_id'] == owner and call['project_id'] == project and call['attempt_no'] == 2
        assert call['status'] == call['provider_status'] == 'completed'
        rows = db.execute('''SELECT r.*,b.scope_type,b.scope_key FROM budget_reservations r
            JOIN model_budgets b ON b.id=r.budget_id WHERE r.call_id=%s''', (call['id'],)).fetchall()
        assert len(rows) == 3
        assert {(row['scope_type'], row['scope_key']) for row in rows} == set(scopes.items())
        assert {row['reserved_micro_usd'] for row in rows} == {required}
        assert {row['accounted_micro_usd'] for row in rows} == {1}
        assert {row['status'] for row in rows} == ({'held'} if task_type == 'boxplot' else {'settled'})
        assert db.execute('SELECT count(*) AS n FROM usage_events WHERE call_id=%s',
                          (call['id'],)).fetchone()['n'] >= 1
        saved = json.loads(db.execute(f'SELECT {column} FROM {table} WHERE id=%s',
                                     (artifact_id,)).fetchone()[column])
        assert saved['analysis_run_id'] == result['id']
        assert saved['provenance']['model_call_id'] == call['id']
        if task_type == 'boxplot':
            assert saved['sha256'] == hashlib.sha256(provider.png).hexdigest()
        else:
            assert saved['figure_id'] == figure['id']
        attempts = db.execute('SELECT attempt_no,status FROM task_attempts WHERE task_id=%s ORDER BY attempt_no',
                              (task['id'],)).fetchall()
        assert [(row['attempt_no'], row['status']) for row in attempts] == [
            (1, 'waiting_confirmation'), (2, 'succeeded')]
        events = db.execute('SELECT event_type FROM task_events WHERE task_id=%s', (task['id'],)).fetchall()
        assert sum(row['event_type'] == 'created' for row in events) == 1
        assert sum(row['event_type'] == 'succeeded' for row in events) == 1
        assert db.execute('SELECT input_snapshot FROM tasks WHERE id=%s',
                          (task['id'],)).fetchone()['input_snapshot'] == snapshot
        outbox_before_replay = db.execute('SELECT * FROM task_outbox WHERE task_id=%s ORDER BY task_revision',
                                         (task['id'],)).fetchall()
    usage = service.task_usage(task['id'])
    assert usage['total'] == 1
    assert {usage[scope + '_budget']['accounted_micro_usd'] for scope in scopes} == {1}
    assert {usage[scope + '_budget']['reserved_micro_usd'] for scope in scopes} == {
        required - 1 if task_type == 'boxplot' else 0}
    state_response = client.get(url)
    assert state_response.status_code == 200, state_response.text
    artifact_key = 'figure' if task_type == 'boxplot' else 'explanation'
    assert state_response.json()[artifact_key]['id'] == artifact_id
    if task_type == 'boxplot':
        new_png = client.get(url + '/image')
        assert new_png.status_code == 200 and new_png.content == provider.png
    assert old_snapshot() == old_bytes
    # The historical response of the same resume key remains stable after completion.
    final_replay = client.post(endpoint, json=resume_body, headers=headers)
    assert final_replay.status_code == 202 and final_replay.json() == resumed
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM task_resume_requests WHERE task_id=%s',
                          (task['id'],)).fetchone()['n'] == 1
        assert db.execute('SELECT * FROM task_outbox WHERE task_id=%s ORDER BY task_revision',
                          (task['id'],)).fetchall() == outbox_before_replay
