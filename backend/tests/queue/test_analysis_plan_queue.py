"""Opt-in real Linux worker restart, durable wait and crash-window recovery."""
import json
import os
from pathlib import Path
import time
import pytest
from app.db.database import database_connection
from tests.api.test_analysis import client
from tests.helpers.analysis_plan import prepared_sample,create_plan,review_plan,plan_decision,decide_plan
from tests.queue.test_real_worker import isolated_worker_stack,worker_stack
from tests.queue.test_dataset_queue import wait_task

pytestmark=pytest.mark.skipif(os.environ.get('PAPERASSIST_RUN_QUEUE_TESTS')!='1',reason='Explicit isolated queue drill is disabled.')


def bootstrap(stack,tmp_path):
    override=tmp_path/'plan-worker.json'
    override.write_text(json.dumps({'services':{'worker':{
        'command':['python','/app/analysis_plan_bootstrap.py','worker'],
        'volumes':[{'type':'bind','source':str(Path(__file__).with_name('analysis_plan_bootstrap.py').resolve()),
            'target':'/app/analysis_plan_bootstrap.py','read_only':True}]}}}),encoding='utf-8')
    worker_stack.compose(stack,['--file',str(override),'up','-d','--wait','--wait-timeout','90'],timeout=180)
    return override


def wait_review(client,task,timeout=115):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        view=review_plan(client,task)
        if view['task']['status']=='waiting_confirmation': return view
        assert view['task']['status']!='failed',view
        time.sleep(.2)
    pytest.fail('Plan worker did not reach its durable confirmation wait.')


def test_plan_wait_releases_single_worker_and_survives_restart(client,isolated_worker_stack,tmp_path):
    stack=isolated_worker_stack
    base,_,prepared=prepared_sample(client)
    first,_=create_plan(client,base,prepared,key='plan-restart')
    override=bootstrap(stack,tmp_path)
    view=wait_review(client,first)
    # Both reach waiting with concurrency one: the human wait holds no worker.
    second,_=create_plan(client,base,prepared,key='plan-second')
    assert wait_review(client,second)['task']['current_attempt']==1
    with database_connection() as db:
        attempt=db.execute('SELECT * FROM task_attempts WHERE task_id=%s',(first['id'],)).fetchone()
        assert attempt['finished_at'] and attempt['lease_owner'] is None
    worker_stack.compose(stack,['stop','--timeout','45','worker'],timeout=100)
    assert review_plan(client,first)==view
    changed={**view['selection'],'group_column':None}
    revised=decide_plan(client,first,plan_decision(view,'revise',changed),'revise-after-restart')
    assert revised.status_code==202,revised.text
    worker_stack.compose(stack,['--file',str(override),'up','-d','--wait','--wait-timeout','90'],timeout=180)
    next_view=wait_review(client,first)
    assert next_view['plan_revision']==2 and next_view['wait_id']!=view['wait_id']
    approved=decide_plan(client,first,plan_decision(next_view),'approve-after-restart')
    assert approved.status_code==202,approved.text
    assert wait_task(client,first['id'])['status']=='succeeded'
    result=client.post(base+'/analysis-runs',json={'expected_revision':1})
    assert result.status_code==200,result.text
    assert result.json()['overall']['n']==5 and result.json()['analysis_plan']['plan_id']==review_plan(client,first)['result']['id']
    assert not (tmp_path/'data'/'.unexpected-plan-network').exists()
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']==0
        assert db.execute('SELECT count(*) AS n FROM budget_reservations').fetchone()['n']==0


def test_plan_crash_before_wait_and_publish_commit_recovers_once(client,isolated_worker_stack,tmp_path):
    stack=isolated_worker_stack
    base,_,prepared=prepared_sample(client)
    bootstrap(stack,tmp_path)
    for index,mode in enumerate(('wait','publish')):
        task,_=create_plan(client,base,prepared,expected=index,key='plan-crash-'+mode)
        if mode=='publish':
            view=wait_review(client,task)
            assert decide_plan(client,task,plan_decision(view)).status_code==202
        marker=tmp_path/'data'/('.plan-crash-'+task['id'])
        deadline=time.monotonic()+45
        while not marker.exists() and time.monotonic()<deadline: time.sleep(.2)
        assert marker.exists()
        with database_connection() as db:
            assert db.execute('SELECT status FROM tasks WHERE id=%s',(task['id'],)).fetchone()['status']=='running'
            assert db.execute('SELECT count(*) AS n FROM confirmed_analysis_plans WHERE task_id=%s',(task['id'],)).fetchone()['n']==0
            assert db.execute("SELECT count(*) AS n FROM task_waits WHERE task_id=%s AND status='open'",(task['id'],)).fetchone()['n']==0
            setup=db.execute('SELECT revision FROM analysis_setups').fetchone()
            assert (setup['revision'] if setup else 0)==index
        if mode=='wait':
            recovered=wait_review(client,task)
            assert recovered['task']['current_attempt']==2
            assert decide_plan(client,task,plan_decision(recovered)).status_code==202
        done=wait_task(client,task['id'],timeout=115)
        assert done['status']=='succeeded' and done['current_attempt']==3,done
        with database_connection(write=True) as db:
            assert db.execute('SELECT count(*) AS n FROM confirmed_analysis_plans WHERE task_id=%s',(task['id'],)).fetchone()['n']==1
            assert db.execute('SELECT revision FROM analysis_setups').fetchone()['revision']==index+1
            db.execute('UPDATE task_outbox SET published_at=NULL,available_at=clock_timestamp() WHERE task_id=%s',(task['id'],))
        # A later task/read follows the duplicate delivery; no extra revision.
        time.sleep(3)
        assert client.get('/api/v1/tasks/'+task['id']).json()['current_attempt']==3
    assert not (tmp_path/'data'/'.unexpected-plan-network').exists()
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']==0
        assert db.execute('SELECT count(*) AS n FROM budget_reservations').fetchone()['n']==0
