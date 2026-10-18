"""Opt-in real Linux filter wait, restart, revision and single publication."""
from tests.helpers.legacy_plans import seed_legacy_plan
import copy
import json
import os
import shutil
from pathlib import Path
import pytest
from app.core.config import local_config
from app.core.paths import PROJECT_ROOT
from app.db.database import database_connection
from tests.api.test_analysis import add_file,client
from tests.queue.test_real_worker import worker_stack
from tests.queue.test_dataset_queue import create_version,get_version,wait_task
from tests.queue.test_dataset_preparation_queue import bootstrap,preparation,wait_review,decide,assert_local_only
from tests.integration.test_batch09_filter_pipeline import ROWS,RECIPE

pytestmark=pytest.mark.skipif(os.environ.get('PAPERASSIST_RUN_QUEUE_TESTS')!='1',reason='Explicit isolated Linux filter queue disabled.')

@pytest.fixture
def filter_worker_stack(postgres_schema,tmp_path):
    test_id=postgres_schema.schema.removeprefix('pa_test_')
    stack=worker_stack.prepare(PROJECT_ROOT,local_config(),test_id=test_id,assets=tmp_path/'data')
    assert stack.project=='pa-test-'+test_id
    assert worker_stack.docker(['info','--format','{{.OSType}}'],timeout=15).strip()=='linux'
    destination=PROJECT_ROOT/'script/.runtime/stage04-batch09'
    destination.mkdir(parents=True,exist_ok=True)
    try:
        worker_stack.compose(stack,['build','worker'],timeout=1200)
        yield stack
    finally:
        worker_stack.stop(stack)
        retained=destination/('filter-queue-assets-'+test_id)
        if (tmp_path/'data').exists():shutil.copytree(tmp_path/'data',retained,dirs_exist_ok=False)
        (destination/('filter-queue-'+test_id+'.json')).write_text(json.dumps(dict(project=stack.project,schema=postgres_schema.schema,
            assets=str(retained),containers=worker_stack.owned_containers(stack),volumes_retained=True,system_or_docker_acl_modified=False),indent=2),encoding='utf-8')

def test_linux_filter_restart_revision_confirmation_and_duplicate_delivery(client,filter_worker_stack,tmp_path):
    stack=filter_worker_stack;override=bootstrap(stack,tmp_path,cpu='1')
    base,_=add_file(client,ROWS)
    raw=create_version(client,base,0)
    assert wait_task(client,raw['task']['id'])['status']=='succeeded'
    raw=get_version(client,base,raw['id'])['datasets'][0]
    initial=preparation(client,base,raw,'filter-baseline')
    decide(client,wait_review(client,initial['id']),'baseline-approve')
    assert wait_task(client,initial['id'])['status']=='succeeded'
    parent=client.get('/api/v1/tasks/'+initial['id']+'/dataset-preparation').json()['result']
    response=client.post(base+'/dataset-population-filters',json=dict(base_dataset_id=parent['id'],recipe=RECIPE),headers={'Idempotency-Key':'linux-filter'})
    assert response.status_code==202,response.text
    task=response.json();view=wait_review(client,task['id'])
    assert view['preview']['retained_record_count']==3
    with database_connection() as db:
        attempt=db.execute('SELECT * FROM task_attempts WHERE task_id=%s',(task['id'],)).fetchone()
        assert attempt['finished_at'] and attempt['lease_owner'] is None
    later=create_version(client,base,1)
    assert wait_task(client,later['task']['id'])['status']=='succeeded'
    worker_stack.compose(stack,['stop','--timeout','45','worker'],timeout=100)
    recipe=copy.deepcopy(RECIPE);recipe['reason']='明确修改的成人A组'
    _,old=decide(client,view,'filter-revise','revise',recipe)
    assert client.get(view['impact_download_url']).status_code==409
    worker_stack.compose(stack,['--file',str(override),'up','-d','--wait','--wait-timeout','90'],timeout=180)
    changed=wait_review(client,task['id'])
    assert changed['recipe_revision']==2 and changed['preview']['retained_record_count']==3
    old['operation']='approve';old['recipe']=None
    assert client.post('/api/v1/tasks/'+task['id']+'/dataset-preparation/decision',json=old,headers={'Idempotency-Key':'late'}).status_code==409
    frozen=client.get(changed['impact_download_url']).content
    worker_stack.compose(stack,['stop','--timeout','45','worker'],timeout=100)
    accepted,body=decide(client,changed,'filter-approve')
    assert client.get(base+'/analysis-setup').json() is None
    worker_stack.compose(stack,['--file',str(override),'up','-d','--wait','--wait-timeout','90'],timeout=180)
    assert wait_task(client,task['id'])['status']=='succeeded'
    result=client.get('/api/v1/tasks/'+task['id']+'/dataset-preparation').json()['result']
    assert result['source']['schema_version']==3
    assert client.get(result['impact_download_url']).content==frozen
    assert client.post('/api/v1/tasks/'+task['id']+'/dataset-preparation/decision',json=body,headers={'Idempotency-Key':'filter-approve'}).json()==accepted
    # The real dispatcher republishes already completed task messages.
    with database_connection(write=True) as db:
        db.execute('UPDATE task_outbox SET published_at=NULL,available_at=clock_timestamp() WHERE task_id=%s',(task['id'],))
    _v4_restart_flow(client,stack,override,base,parent,result)
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM prepared_dataset_versions WHERE task_id=%s',(task['id'],)).fetchone()['n']==1
        assert db.execute('SELECT count(*) AS n FROM prepared_dataset_derivations_v3').fetchone()['n']==1
        assert db.execute('SELECT count(*) AS n FROM confirmed_analysis_plans').fetchone()['n']==2
    assert_local_only(tmp_path)


def _wait_plan(client,task,status):
    import time
    from tests.helpers.analysis_plan import review_plan
    deadline=time.monotonic()+110
    while time.monotonic()<deadline:
        view=review_plan(client,task)
        if view['task']['status']==status:return view
        assert view['task']['status']!='failed',view
        time.sleep(.2)
    pytest.fail('V4 requirement worker did not reach durable wait')


def _v4_restart_flow(client,stack,override,base,parent,filtered):
    from tests.integration.test_research_plan import research
    from tests.test_batch09_research_flow import decision
    from tests.helpers.analysis_plan import review_plan,decide_plan
    from tests.api.test_analysis import selection
    project=base.split('/')[4];file=base.split('/')[6]
    body=dict(schema_version=4,input_kind='data',file_id=file,dataset_id=filtered['id'],expected_setup_revision=0,
        selection=None,research_request=research(),evidence_version_ids=[])
    response=seed_legacy_plan(client, base+'/analysis-plans',json=body,headers={'Idempotency-Key':'linux-v4-data'})
    assert response.status_code==202,response.text
    data=response.json();data_wait=_wait_plan(client,data,'waiting_input')
    assert data_wait['check']['data_check'] is None and data_wait['check']['research_missing']==['selection']
    evidence=client.post('/api/v1/projects/'+project+'/external-evidence',json=dict(file_id=file,source_kind='original',title='External result',
        intended_use='request_reanalysis',original_data='unavailable'),headers={'Idempotency-Key':'linux-evidence'})
    assert evidence.status_code==201,evidence.text
    response=seed_legacy_plan(client, '/api/v1/projects/'+project+'/analysis-plans',json={**body,'input_kind':'materials','file_id':None,'dataset_id':None,
        'evidence_version_ids':[evidence.json()['id']]},headers={'Idempotency-Key':'linux-v4-materials'})
    assert response.status_code==202,response.text
    materials=response.json();material_wait=_wait_plan(client,materials,'waiting_input')
    assert material_wait['source'] is None and material_wait['check']['data_check'] is None
    assert material_wait['check']['research_missing']==['source','selection']
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM confirmed_analysis_plans').fetchone()['n']==0
        attempts=db.execute('SELECT * FROM task_attempts WHERE task_id IN (%s,%s)',(data['id'],materials['id'])).fetchall()
        assert all(a['finished_at'] and a['lease_owner'] is None for a in attempts)
    worker_stack.compose(stack,['stop','--timeout','45','worker'],timeout=100)
    assert review_plan(client,data)==data_wait and review_plan(client,materials)==material_wait
    chosen=selection(numeric_column='C',group_column=None)
    response=decide_plan(client,data,decision(data_wait,'revise',selection=chosen),'linux-data-supply')
    assert response.status_code==202,response.text
    assert decide_plan(client,data,decision(data_wait),'linux-stale-data').status_code==409
    worker_stack.compose(stack,['--file',str(override),'up','-d','--wait','--wait-timeout','90'],timeout=180)
    checked=_wait_plan(client,data,'waiting_confirmation')
    assert checked['result'] is None and checked['source']==filtered['source']
    approved=decide_plan(client,data,decision(checked),'linux-data-approve')
    assert approved.status_code==202,approved.text
    assert wait_task(client,data['id'])['status']=='succeeded'
    request={k:material_wait[k] for k in ('input_version','checkpoint_id','wait_id','plan_revision')}
    request.update(expected_task_revision=material_wait['task']['revision'],file_id=file,dataset_id=filtered['id'],expected_setup_revision=1,
        selection=chosen,research_request=research())
    path='/api/v1/tasks/'+materials['id']+'/analysis-plan/continuations'
    response=client.post(path,json=request,headers={'Idempotency-Key':'linux-material-supply'})
    assert response.status_code==202,response.text
    receipt=response.json();assert receipt['completion_type']=='continued_as_plan'
    replay=client.post(path,json=request,headers={'Idempotency-Key':'linux-material-supply'})
    assert replay.status_code==200 and replay.json()==receipt
    child=receipt['task'];checked=_wait_plan(client,child,'waiting_input')
    assert checked['input_version']['workflow_version']=='analysis_plan_v5'
    assert checked['check']['research_missing']==['source_confirmation']
    clarification={k:checked[k] for k in ('input_version','checkpoint_id','wait_id','plan_revision')}
    clarification.update(expected_task_revision=checked['task']['revision'],source_resolution=dict(confirmed=True,note='Use this frozen filtered version for the child plan.'))
    clarified=client.post('/api/v1/tasks/'+child['id']+'/analysis-plan/source-decisions',json=clarification,headers={'Idempotency-Key':'linux-child-source'})
    assert clarified.status_code==202,clarified.text
    checked=_wait_plan(client,child,'waiting_confirmation')
    assert checked['result'] is None
    assert review_plan(client,materials)['result'] is None
    approved=decide_plan(client,child,decision(checked),'linux-child-approve')
    assert approved.status_code==202,approved.text
    assert wait_task(client,child['id'])['status']=='succeeded'
    submitted=client.post(base+'/analysis-runs',json={'expected_revision':2})
    assert submitted.status_code==202,submitted.text
    completed=wait_task(client,submitted.json()['id'])
    assert completed['status']=='succeeded',completed
    computed=client.get(base+'/analysis-runs/'+completed['result_analysis_run_id'])
    assert computed.status_code==200,computed.text
    assert computed.json()['overall']['n']==3 and computed.json()['overall']['mean']==40
