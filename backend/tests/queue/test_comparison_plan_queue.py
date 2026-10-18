"""Opt-in real Linux comparison waits and Windows result revalidation."""
from tests.helpers.legacy_plans import seed_legacy_plan
from tests.helpers.statistics import statistics_post
import json
import os

import pytest

from app.db.database import database_connection
from tests.api.test_analysis import client  # noqa: F401
from tests.domain.test_correlation_plan_contracts import research
from tests.helpers.analysis_plan import decide_plan, plan_decision, review_plan
from tests.integration.test_comparison_plan import approve, independent_rows, make_plan, selection
from tests.integration.test_correlation_plan import prepared_correlations
from tests.queue.test_analysis_plan_queue import bootstrap
from tests.queue.test_correlation_plan_queue import wait_status
from tests.queue.test_dataset_queue import wait_task
from tests.queue.test_real_worker import isolated_worker_stack, worker_stack  # noqa: F401

pytestmark = pytest.mark.skipif(os.environ.get('PAPERASSIST_RUN_QUEUE_TESTS') != '1',
    reason='Explicit isolated Linux comparison-plan test is disabled.')


def test_comparison_wait_releases_worker_and_restart_publishes_once(client, isolated_worker_stack, tmp_path):
    base, _, prepared = prepared_correlations(client, rows=independent_rows())
    chosen = selection(prepared['source']['sheet_name'], 'welch_anova')
    chosen['posthoc'] = 'all_pairs_holm'
    chosen['assumptions']['inference_confirmed'] = False
    first, body = make_plan(client, base, prepared, chosen)
    second = seed_legacy_plan(client, base + '/analysis-plans', json=body,
        headers={'Idempotency-Key': 'second-comparison-wait'})
    assert second.status_code == 202, second.text
    stack = isolated_worker_stack
    override = bootstrap(stack, tmp_path)
    before = wait_status(client, first, 'waiting_input')
    wait_status(client, second.json(), 'waiting_input')
    with database_connection() as db:
        attempts = db.execute('SELECT * FROM task_attempts WHERE task_id=ANY(%s)',
            ([first['id'], second.json()['id']],)).fetchall()
        assert len(attempts) == 2
        assert all(a['finished_at'] and a['lease_owner'] is None for a in attempts)
        assert db.execute('SELECT count(*) AS n FROM confirmed_analysis_plans').fetchone()['n'] == 0
    worker_stack.compose(stack, ['stop', '--timeout', '45', 'worker'], timeout=100)
    assert review_plan(client, first) == before
    corrected = dict(before['selection'])
    corrected['assumptions'] = {**corrected['assumptions'], 'inference_confirmed': True}
    supplement = plan_decision(before, 'revise', corrected)
    updated = decide_plan(client, first, supplement, 'comparison-supplement')
    assert updated.status_code == 202, updated.text
    assert decide_plan(client, first, supplement, 'comparison-supplement').json() == updated.json()
    worker_stack.compose(stack, ['--file', str(override), 'up', '-d', '--wait', '--wait-timeout', '90'], timeout=180)
    candidate = wait_status(client, first, 'waiting_confirmation')
    assert candidate['plan_revision'] == 2 and candidate['wait_id'] != before['wait_id']
    assert candidate['result'] is None
    assert decide_plan(client, first, plan_decision(before), 'stale-comparison-confirm').status_code == 409
    approval = plan_decision(candidate)
    accepted = decide_plan(client, first, approval, 'comparison-confirm')
    assert accepted.status_code == 202, accepted.text
    assert wait_task(client, first['id'])['status'] == 'succeeded'
    assert decide_plan(client, first, approval, 'comparison-confirm').json() == accepted.json()
    result = statistics_post(client, base + '/analysis-runs', json={'expected_revision': 1})
    assert result.status_code == 200, result.text
    assert result.json()['statistics']['sample_sizes'] == [5, 5, 5]
    assert len(result.json()['statistics']['pairwise']) == 3
    assert result.json()['analysis_context']['plan'] == review_plan(client, first)['result']
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM confirmed_analysis_plans').fetchone()['n'] == 1
        assert db.execute('SELECT count(*) AS n FROM analysis_setups').fetchone()['n'] == 1
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0
        assert db.execute('SELECT count(*) AS n FROM budget_reservations').fetchone()['n'] == 0
    assert not (tmp_path / 'data' / '.unexpected-plan-network').exists()


def test_six_windows_saved_methods_revalidate_in_real_linux_worker(client, isolated_worker_stack, tmp_path):
    from app.adapters.task_store import TaskStore
    from app.domain.external_processing import freeze_confirmation
    from app.domain.tasks.contracts import TaskCreateRequest
    from tests.helpers.tasks import task_owner
    external_confirmations = {}
    examples = [(method, 0) for method in ('welch_t', 'mann_whitney_u', 'paired_t', 'wilcoxon', 'welch_anova', 'kruskal_wallis')]
    examples += [(method, 10_000_000_000.) for method in ('welch_t', 'paired_t', 'welch_anova')]
    for method, offset in examples:
        paired = method in ('paired_t', 'wilcoxon')
        rows = [['ID', 'Before', 'After']] + [[f'synthetic-{i}', a, b] for i, (a, b) in enumerate(zip(
            [4, 6, 8, 11, 13, 15], [2, 5, 4, 5, 12, 12]))] if paired else independent_rows()
        if offset:
            for row in rows[1:]:
                for column in ([1, 2] if paired else [0]):
                    if row[column] is not None:
                        row[column] += offset
        base, _, prepared = prepared_correlations(client, rows=rows)
        chosen = selection(prepared['source']['sheet_name'], method)
        if chosen['design'] == 'multiple':
            chosen['posthoc'] = 'all_pairs_holm'
        declaration = research()
        if paired:
            declaration.update(observation_structure='paired', relationship_description='Same synthetic unit at two visits')
        task, _ = make_plan(client, base, prepared, chosen, declaration)
        approve(client, task)
        response = statistics_post(client, base + '/analysis-runs', json={'expected_revision': 1})
        assert response.status_code == 200, response.text
        result = response.json()
        preview = client.get(base + '/analysis-runs/' + result['id'] + '/boxplot/disclosure')
        assert preview.status_code == 200, preview.text
        disclosed = preview.json()
        assert disclosed['version'] == 5
        confirmation = dict(version=disclosed['version'], confirmed=True, source_digest=disclosed['source_digest'],
            labels={item['key']:item['value'] for item in disclosed['labels']})
        owner = task_owner(client)
        store = TaskStore(owner)
        request = TaskCreateRequest(task_type='boxplot',file_id=result['file_id'],analysis_run_id=result['id'],expected_revision=1)
        with store.connection() as db:
            snapshot=store.source_snapshot(db,store.require_project(db,task['project_id']),request)
        # Use the same confirmation normalizer as task creation without queuing a paid node.
        external_confirmations[result['id']] = freeze_confirmation(snapshot,'boxplot',owner,confirmation)
    stack = isolated_worker_stack
    bootstrap(stack, tmp_path)
    code = """import json
from app.workers.config import load_secrets
load_secrets()
from app.db.database import database_connection
from app.core.config import get_data_dir
from app.adapters.storage import ProjectStore
from app.domain.comparison.service import load_comparison_input
from app.domain.comparison_material import build_material
# WINDOWS_EXTERNAL_CONFIRMATIONS
with database_connection() as db:
    rows=db.execute('SELECT a.*,f.project_id,p.owner_id FROM analysis_runs a JOIN files f ON f.id=a.file_id JOIN projects p ON p.id=f.project_id').fetchall()
assert len(rows)==9
for row in rows:
    frozen=json.loads(row['result_json'])
    assets=ProjectStore(get_data_dir(),owner_id=row['owner_id'])
    actual=assets.analysis_result_by_id(row['project_id'],row['file_id'],row['id'])
    assert actual['statistics']==frozen['statistics']
    assert actual['groups']==frozen['groups']
    assert actual['row_audit']==frozen['row_audit']
    data=load_comparison_input(assets,row['project_id'],row['file_id'],actual)
    payload,expected=build_material(actual,data['groups'],external=external_confirmations[frozen['id']])
    assert payload['schema_version']==3 and expected['statistics']['sample_sizes']==frozen['statistics']['sample_sizes']
    metrics=('n','mean','std','min','q1','median','q3','max','iqr')
    assert expected['groups']==[{'label':group['label'],'statistics':{key:group['statistics'][key] for key in metrics}} for group in frozen['groups']]
    if frozen['selection']['design']=='paired':
        assert expected['paired_summary']['n_pairs']==frozen['check']['valid_count']
    print('COMPARISON_MATERIAL_OK:'+frozen['statistics']['method'])
    print('COMPARISON_PLATFORM_OK:'+frozen['statistics']['method'])
print('WINDOWS_TO_LINUX_COMPARISON_OK:9')
"""
    code=code.replace('# WINDOWS_EXTERNAL_CONFIRMATIONS','external_confirmations=json.loads('+repr(json.dumps(external_confirmations,ensure_ascii=True))+')')
    code = "try:\n" + ''.join('    ' + line + '\n' for line in code.splitlines()) + "except Exception as exc:\n    print('REVALIDATION_FAILED:'+type(exc).__name__+':'+str(getattr(exc,'code','')))\n"
    output = worker_stack.compose(stack, ['exec', '-T', 'worker', 'python', '-c', code], timeout=60)
    assert 'WINDOWS_TO_LINUX_COMPARISON_OK:9' in output, output
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0
