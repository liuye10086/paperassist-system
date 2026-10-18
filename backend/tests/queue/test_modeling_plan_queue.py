"""Real isolated Linux recovery and independent Windows result reconstruction."""
from tests.helpers.legacy_plans import seed_legacy_plan
from tests.helpers.statistics import statistics_post
import json
import os
import pytest
from app.db.database import database_connection
from tests.api.test_analysis import client
from tests.helpers.modeling import sample,selection,approve,prepared_modeling
from tests.integration.test_correlation_plan import prepared_correlations
from tests.integration.test_comparison_plan import make_plan
from tests.helpers.analysis_plan import review_plan,plan_decision,decide_plan
from tests.queue.test_analysis_plan_queue import bootstrap
from tests.queue.test_correlation_plan_queue import wait_status as wait_review_status
from tests.queue.test_dataset_queue import wait_task
from tests.queue.test_real_worker import isolated_worker_stack,worker_stack

pytestmark=pytest.mark.skipif(os.environ.get('PAPERASSIST_RUN_QUEUE_TESTS')!='1',reason='Explicit isolated Linux modeling test disabled.')


def wait_status(client,task,status):
    try:
        return wait_review_status(client,task,status)
    except AssertionError:
        # Only the synthetic test task's public error is printed; no worker
        # configuration, raw database exception or provider response is logged.
        current=review_plan(client,task)['task']
        pytest.fail(f"Expected {status}; got {current['status']} / {current.get('error_code')}")


def test_modeling_missing_role_releases_worker_and_recovers_once(client,isolated_worker_stack,tmp_path):
    base,_,prepared=prepared_correlations(client,rows=sample('roc_auc'))
    chosen=selection('roc_auc',prepared['source']['sheet_name']);chosen['score_column']=None
    task,body=make_plan(client,base,prepared,chosen,key='modeling-wait')
    second=seed_legacy_plan(client, base+'/analysis-plans',json=body,headers={'Idempotency-Key':'modeling-second'})
    assert second.status_code==202,second.text
    stack=isolated_worker_stack;override=bootstrap(stack,tmp_path)
    before=wait_status(client,task,'waiting_input')
    wait_status(client,second.json(),'waiting_input')
    with database_connection() as db:
        attempts=db.execute('SELECT * FROM task_attempts WHERE task_id=ANY(%s)',([task['id'],second.json()['id']],)).fetchall()
        assert len(attempts)==2 and all(a['finished_at'] and a['lease_owner'] is None for a in attempts)
    worker_stack.compose(stack,['stop','--timeout','45','worker'],timeout=100)
    assert review_plan(client,task)==before
    supplement=plan_decision(before,'revise',selection('roc_auc',prepared['source']['sheet_name']))
    updated=decide_plan(client,task,supplement,'modeling-supplement')
    assert updated.status_code==202,updated.text
    assert decide_plan(client,task,supplement,'modeling-supplement').json()==updated.json()
    worker_stack.compose(stack,['--file',str(override),'up','-d','--wait','--wait-timeout','90'],timeout=180)
    candidate=wait_status(client,task,'waiting_confirmation')
    assert candidate['result'] is None and candidate['plan_revision']==2
    assert decide_plan(client,task,plan_decision(before),'modeling-stale').status_code==409
    approval=plan_decision(candidate)
    accepted=decide_plan(client,task,approval,'modeling-confirm')
    assert accepted.status_code==202,accepted.text
    assert wait_task(client,task['id'])['status']=='succeeded'
    assert decide_plan(client,task,approval,'modeling-confirm').json()==accepted.json()
    response=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1})
    assert response.status_code==200,response.text
    assert response.json()['statistics']['method']=='roc_auc'
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM confirmed_analysis_plans').fetchone()['n']==1
        assert db.execute('SELECT count(*) AS n FROM analysis_setups').fetchone()['n']==1
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']==0
    assert not (tmp_path/'data'/'.unexpected-plan-network').exists()


def test_windows_modeling_results_rebuild_in_linux(client,isolated_worker_stack,tmp_path):
    for method in ('ols','logistic','roc_auc','kaplan_meier'):
        base,_,prepared=prepared_modeling(client,method)
        task,_=make_plan(client,base,prepared,selection(method,prepared['source']['sheet_name']),key='platform-'+method)
        approve(client,task)
        response=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1})
        assert response.status_code==200,response.text
    stack=isolated_worker_stack;bootstrap(stack,tmp_path)
    code='''import json
from app.workers.config import load_secrets
load_secrets()
from app.db.database import database_connection
from app.core.config import get_data_dir
from app.adapters.storage import ProjectStore
with database_connection() as db:
    rows=db.execute('SELECT a.*,f.project_id,p.owner_id FROM analysis_runs a JOIN files f ON f.id=a.file_id JOIN projects p ON p.id=f.project_id').fetchall()
assert len(rows)==4
for row in rows:
    expected=json.loads(row['result_json'])
    store=ProjectStore(get_data_dir(),owner_id=row['owner_id'])
    actual=store.analysis_result_by_id(row['project_id'],row['file_id'],row['id'])
    assert actual==expected
    print('MODELING_PLATFORM_OK:'+actual['statistics']['method'])
print('WINDOWS_TO_LINUX_MODELING_OK:4')
'''
    output=worker_stack.compose(stack,['exec','-T','worker','python','-c',code],timeout=180)
    assert 'WINDOWS_TO_LINUX_MODELING_OK:4' in output,output
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']==0
