"""Opt in explicitly to a real App/API browser session; disabled by default."""
from hashlib import sha256
import json
import os
from pathlib import Path

import pytest

from app.db.database import database_connection
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_boxplot import cloud  # noqa: F401
from tests.integration.test_explanations import writer  # noqa: F401
from tests.browser.task_browser_seed import matrix, project, source, request_for, saved_material
from tests.browser.task_browser_support import (ROOT, URL, BrowserControls, LoopbackServer,
    block_real_providers, deep_link, port_open, run_directory, save_json)


pytestmark = pytest.mark.skipif(os.environ.get('PAPERASSIST_RUN_BROWSER_TESTS') != '1',
    reason='Real browser fixture requires PAPERASSIST_RUN_BROWSER_TESTS=1 and an absolute evidence directory.')


@pytest.fixture(scope='session')
def cleanup_audit():
    """Runs after function-scoped schema teardown and verifies only recorded UUIDs."""
    records = []
    yield records
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool
    for directory, config in records:
        assert config.environment == 'test' and config.url.database == 'paperassist_system_test'
        engine = create_engine(config.url, poolclass=NullPool)
        try:
            with engine.connect() as db:
                assert db.exec_driver_sql('SELECT current_database()').scalar_one() == 'paperassist_system_test'
                absent = db.exec_driver_sql('SELECT 1 FROM pg_namespace WHERE nspname=%s',
                                           (config.schema,)).first() is None
            save_json(directory / 'cleanup.json', {'schema': config.schema,
                'schema_removed': absent, 'port_closed': not port_open()})
            assert absent and not port_open()
        finally:
            engine.dispose()


def test_task_browser_session(client, cloud, writer, postgres_schema, tmp_path, monkeypatch, cleanup_audit):
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.db.database import get_migration_database_config
    from app.domain.model_usage.contracts import ModelPolicy
    from app.domain.model_usage.pricing import reserve_micro_usd
    from app.domain.model_usage.service import ModelUsageService
    from app.domain.tasks.execution import run_boxplot_task, run_word_task
    from app.domain.tasks.service import TaskService
    from tests.api.test_external_processing import confirmation
    from tests.integration.test_budget_recovery import temporary_policy, assert_task_admission_empty
    from tests.integration.test_external_execution import ConfirmedPlotProvider

    directory = run_directory()
    cleanup_audit.append((directory, get_migration_database_config()))
    assert postgres_schema.environment == 'test' and postgres_schema.url.database == 'paperassist_system_test'
    monkeypatch.setenv('PAPERASSIST_AUTH_TRUSTED_ORIGINS', URL + ',http://testserver')
    monkeypatch.setenv('PAPERASSIST_PLOT_WORKER_ENABLED', '0')
    monkeypatch.setenv('OPENAI_API_KEY', 'step15-synthetic-not-a-real-key')
    monkeypatch.setenv('OPENAI_API_KEY_FILE', '')
    attempts = block_real_providers(monkeypatch)
    owner = client.get('/api/v1/auth/me').json()['user']['id']
    flow_project = project(client, '流程演练 · 合成预算与本地重试')
    contrast = project(client, '切换对照 · 合成空项目')
    display = project(client, '状态展示 · 合成只读状态与本地Word')

    # Old artifacts are produced before interactive flow; their exact bytes are retained.
    base, file, result = source(client, flow_project['id'], '旧成果保持与安全失败重试.xlsx')
    figure, explanation = saved_material(client, base, result)
    request = request_for(file, result, figure=figure, explanation=explanation)
    service = TaskService(owner, postgres_schema)
    historic, _ = service.create(flow_project['id'], request, idempotency_key='old-local-word')
    historic = run_word_task(historic['id'], historic['revision'], config=postgres_schema)
    assert historic['status'] == 'succeeded'
    retry, _ = service.create(flow_project['id'], request, idempotency_key='synthetic-safe-failure')
    execution = TaskExecutionStore(config=postgres_schema)
    lease = execution.claim(retry['id'], retry['revision'], task_type='word_report')
    assert lease
    retry = execution.fail(lease, 'report_render_failed')
    assert retry['status'] == 'failed' and retry['error_code'] == 'report_render_failed'
    states = matrix(client, owner, display['id'])
    assert cloud.calls == writer.calls == []

    # Task acceptance reads a real temporary policy and real HTTP confirmation.
    frozen = temporary_policy('boxplot')
    policy_file = tmp_path / 'synthetic-browser-plot-policy.json'
    policy_file.write_text(json.dumps(frozen), encoding='utf-8')
    monkeypatch.setenv('PAPERASSIST_PLOT_POLICY_FILE', str(policy_file))
    budget_base, _, budget_result = source(client, flow_project['id'], '合成预算等待流程.xlsx')
    plot_url = budget_base + '/analysis-runs/' + budget_result['id'] + '/boxplot'
    accepted = client.post(plot_url, json={'expected_revision': 1,
        'external_processing': confirmation(client, plot_url)}, headers={'Idempotency-Key': 'browser-budget-flow'})
    assert accepted.status_code == 202, accepted.text
    budget_task = accepted.json()['task']
    required = reserve_micro_usd(ModelPolicy.model_validate(frozen['policy']),
                                frozen['input_token_allowance'], frozen['tool_reserve_micro_usd'])
    budgets = ModelUsageService(owner, postgres_schema)
    for scope, key in [('user', owner), ('project', flow_project['id']), ('task', budget_task['id'])]:
        current = budgets.get_budget(scope, key)
        budgets.set_budget(scope, key, required - 1 if scope == 'task' else 1_000_000, current['revision'])
    provider = ConfirmedPlotProvider(budget_result, pending=False)
    waiting = run_boxplot_task(budget_task['id'], budget_task['revision'], config=postgres_schema,
                               provider_factory=lambda: provider)
    assert waiting['status'] == 'waiting_confirmation' and waiting['reason_code'] == 'budget_exceeded'
    assert waiting['error_code'] == 'model_budget_exceeded' and provider.posts == []
    assert_task_admission_empty(waiting['id'])
    # Finish setup with every legacy/default construction path disabled as well.
    def no_implicit_provider(*args, **kwargs):
        attempts.append('blocked_implicit_provider')
        raise AssertionError('Use only an explicit synthetic provider_factory.')
    monkeypatch.setattr('app.domain.boxplot.CloudPlot', no_implicit_provider)
    monkeypatch.setattr('app.domain.explanations.CloudExplanation', no_implicit_provider)
    monkeypatch.setattr('app.domain.tasks.explanation_execution.create_provider', no_implicit_provider)

    data = Path(os.environ['PAPERASSIST_DATA_DIR'])
    original_bytes = {}
    def old_snapshot():
        files = {'png': data / 'figures' / (figure['id'] + '.png'),
                 'word': data / 'reports' / (historic['result_report_id'] + '.docx')}
        result = {}
        for key, path in files.items():
            content = path.read_bytes()
            assert content == original_bytes.setdefault(key, content)
            result[key] = {'sha256': sha256(content).hexdigest(), 'bytes': len(content)}
        with database_connection() as db:
            for table, column, identifier in [('figures', 'figure_json', figure['id']),
                ('explanations', 'explanation_json', explanation['id']),
                ('reports', 'report_json', historic['result_report_id'])]:
                payload = db.execute(f'SELECT {column} FROM {table} WHERE id=%s', (identifier,)).fetchone()[column]
                content = payload.encode('utf-8')
                assert content == original_bytes.setdefault(table, content)
                result[table] = sha256(content).hexdigest()
        return result

    server = LoopbackServer(ROOT / 'frontend' / 'dist')
    flow = {'owner': owner, 'project_id': flow_project['id'], 'budget_task_id': waiting['id'],
            'retry_task_id': retry['id'], 'required_budget': required}
    controls = BrowserControls(client, postgres_schema, flow, old_snapshot, provider, server, attempts)
    page = client.get(f'/api/v1/projects/{display["id"]}/tasks?page_size=50')
    assert page.status_code == 200
    positions = {item['task']['id']: index for index, item in enumerate(page.json()['items'])}
    ready = {'url': URL, 'account': {'email': 'business-test@paperassist.local',
        'password': 'isolated-test-password-2026', 'synthetic': True},
        'projects': {key: {'id': value['id'], 'name': value['name'], 'url': deep_link(value['id'])}
                     for key, value in [('flow', flow_project), ('contrast', contrast), ('matrix', display)]},
        'tasks': {'budget': {'id': waiting['id'], 'name': '合成预算等待流程.xlsx',
                            'url': deep_link(flow_project['id'], waiting['id'])},
                  'retry': {'id': retry['id'], 'name': '旧成果保持与安全失败重试.xlsx',
                            'url': deep_link(flow_project['id'], retry['id']),
                            'failure_origin': 'explicitly_injected_synthetic_safe_failure'}},
        'matrix_list_total': page.json()['total'],
        'matrix_extra_rows': 'Two historical synthetic PNG/explanation rows support the actual local Word sample.',
        'matrix': [{**row, 'url': deep_link(display['id'], row['task_id']),
                    'list_page': positions[row['task_id']] // 10 + 1,
                    'list_row': positions[row['task_id']] % 10 + 1} for row in states]}
    try:
        server.start()
        save_json(directory / 'initial-snapshot.json', controls.snapshot())
        save_json(directory / 'ready.json', ready)
        controls.wait(directory)
    finally:
        try:
            save_json(directory / 'final-snapshot.json', controls.snapshot())
        finally:
            server.close()
            save_json(directory / 'server-closed.json', {'url': URL,
                'thread_stopped': not server.thread.is_alive(), 'port_closed': not port_open()})
