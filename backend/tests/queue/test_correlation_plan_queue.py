"""Opt-in real Linux v3 waits/restart and atomic publication; no paid providers."""
from tests.helpers.legacy_plans import seed_legacy_plan
from tests.helpers.statistics import statistics_post
import os
import copy
import json
import time
import pytest

from app.db.database import database_connection
from tests.api.test_analysis import client  # noqa: F401
from tests.domain.test_correlation_plan_contracts import research
from tests.integration.test_correlation_plan import prepared_correlations, create_correlation
from tests.helpers.analysis_plan import review_plan, plan_decision, decide_plan
from tests.queue.test_analysis_plan_queue import bootstrap
from tests.queue.test_dataset_queue import wait_task
from tests.queue.test_real_worker import isolated_worker_stack, worker_stack  # noqa: F401

pytestmark = pytest.mark.skipif(os.environ.get('PAPERASSIST_RUN_QUEUE_TESTS') != '1',
    reason='Explicit isolated Linux correlation-plan test is disabled.')


def wait_status(client, task, status, timeout=115):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = review_plan(client, task)
        assert value['task']['status'] != 'failed', value
        if value['task']['status'] == status:
            return value
        time.sleep(.2)
    pytest.fail('Correlation plan did not reach its durable ' + status + ' wait.')


def test_correlation_input_restart_and_independent_confirmation_publish_once(client, isolated_worker_stack, tmp_path):
    stack = isolated_worker_stack
    base, _, prepared = prepared_correlations(client)
    declaration = research(); declaration['observation_structure'] = 'unknown'
    first, body = create_correlation(client, base, prepared, changes={'research_request': declaration})
    second = seed_legacy_plan(client, base + '/analysis-plans', json=body,
        headers={'Idempotency-Key': 'second-v3-wait'})
    assert second.status_code == 202, second.text
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
    supplement = plan_decision(before, 'revise', before['selection'])
    supplement['research_request'] = research()
    updated = decide_plan(client, first, supplement, 'v3-supplement')
    assert updated.status_code == 202, updated.text
    assert decide_plan(client, first, supplement, 'v3-supplement').json() == updated.json()
    worker_stack.compose(stack, ['--file', str(override), 'up', '-d', '--wait', '--wait-timeout', '90'], timeout=180)
    candidate = wait_status(client, first, 'waiting_confirmation')
    assert candidate['plan_revision'] == 2 and candidate['wait_id'] != before['wait_id']
    assert candidate['result'] is None
    assert decide_plan(client, first, plan_decision(before), 'old-v3-approval').status_code == 409
    approval = plan_decision(candidate)
    accepted = decide_plan(client, first, approval, 'v3-confirm')
    assert accepted.status_code == 202, accepted.text
    assert wait_task(client, first['id'])['status'] == 'succeeded'
    assert decide_plan(client, first, approval, 'v3-confirm').json() == accepted.json()
    result = statistics_post(client, base + '/analysis-runs', json={'expected_revision': 1})
    assert result.status_code == 200, result.text
    assert result.json()['statistics']['n'] == 3
    assert result.json()['statistics']['coefficient'] == pytest.approx(1)
    assert result.json()['analysis_context']['plan'] == review_plan(client, first)['result']
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM confirmed_analysis_plans').fetchone()['n'] == 1
        assert db.execute('SELECT count(*) AS n FROM analysis_setups').fetchone()['n'] == 1
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0
        assert db.execute('SELECT count(*) AS n FROM budget_reservations').fetchone()['n'] == 0
    assert not (tmp_path / 'data' / '.unexpected-plan-network').exists()


def test_windows_saved_statistics_revalidate_in_linux_worker(client, isolated_worker_stack, tmp_path):
    """Actual platform boundary, including seeded permutations, with no cloud I/O."""
    from tests.integration.test_dataset_preparation import create_preparation, run, review, decide, decision
    from tests.helpers.analysis_plan import run_plan
    from tests.domain.test_correlation_plan_contracts import selection
    examples=[('pearson', [[1,2],[2,1],[3,4],[4,3],[5,5]]),
              ('spearman', [[1,1],[2,2],[2,3],[4,4]]),
              ('spearman', [[i, (i*7)%11] for i in range(1,9)])]
    for method, rows in examples:
        base, file, _, _, task=create_preparation(client,rows=[['X','Y'],*rows])
        run(task);view=review(client,task);recipe=copy.deepcopy(view['recipe'])
        for field in recipe['fields']:field['unit']={'status':'confirmed','value':''}
        changed=decide(client,task,decision(view,'revise',recipe),'units').json();run(changed)
        accepted=decide(client,task,decision(review(client,task)),'approve').json()
        assert run(accepted)['status']=='succeeded'
        prepared=review(client,task)['result']
        chosen=selection();chosen.update(method=method,sheet_name=prepared['source']['sheet_name'],units={'A':'','B':''})
        chosen['assumptions']['relationship_form']='linear' if method=='pearson' else 'monotonic'
        planned,_=create_correlation(client,base,prepared,changes={'selection':chosen})
        assert run_plan(planned)['status']=='waiting_confirmation'
        approved=decide_plan(client,planned,plan_decision(review_plan(client,planned))).json()
        assert run_plan(approved)['status']=='succeeded'
        result=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1})
        assert result.status_code==200,result.text
    stack=isolated_worker_stack;bootstrap(stack,tmp_path)
    code="""import json
from app.workers.config import load_secrets
load_secrets()
from app.db.database import database_connection
from app.core.config import get_data_dir
from app.adapters.storage import ProjectStore
with database_connection() as db:
    saved=db.execute('SELECT a.*,f.project_id,p.owner_id FROM analysis_runs a JOIN files f ON f.id=a.file_id JOIN projects p ON p.id=f.project_id').fetchall()
assert len(saved)==3
for row in saved:
    store=ProjectStore(get_data_dir(),owner_id=row['owner_id'])
    from app.domain.dataset_analysis import load_dataset
    from app.domain.correlation.checks import selected_records
    from app.domain.correlation.contracts import CorrelationSelection
    from app.domain.correlation.kernel import compute_correlation
    frozen=json.loads(row['result_json'])
    _,_,sheet=load_dataset(store,row['project_id'],row['file_id'],frozen['source']['dataset_id'],expected_source=frozen['source'])
    chosen=CorrelationSelection.model_validate(frozen['selection'],strict=True)
    rows,variables,audit=selected_records(sheet,chosen)
    computed=compute_correlation(rows,method=chosen.method,mode=chosen.mode)
    print('SYNTHETIC_PLATFORM_STATS:'+json.dumps({'saved':frozen['statistics'],'computed':computed,'variables_equal':variables==frozen['variables'],'audit_equal':audit==frozen['row_audit']}))
    value=store.analysis_result_by_id(row['project_id'],row['file_id'],row['id'])
    assert value['statistics']==json.loads(row['result_json'])['statistics']
print('WINDOWS_TO_LINUX_REVALIDATION_OK:3')
"""
    # Keep failure diagnostics bounded and credential-free despite Docker's safe
    # default suppression of third-party exception bodies.
    code="try:\n"+''.join('    '+line+'\n' for line in code.splitlines())+"except Exception as exc:\n    print('REVALIDATION_FAILED:'+type(exc).__name__+':'+str(getattr(exc,'code','')))\n"
    output=worker_stack.compose(stack,['exec','-T','worker','python','-c',code],timeout=60)
    assert 'WINDOWS_TO_LINUX_REVALIDATION_OK:3' in output, output
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']==0
