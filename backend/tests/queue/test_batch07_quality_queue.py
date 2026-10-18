"""Opt-in isolated Linux quality wait/restart/crash recovery; retain stack volumes."""
import copy
import json
import os
from pathlib import Path
import time
import pytest

from app.core.config import local_config
from app.core.paths import PROJECT_ROOT
from app.db.database import database_connection
from tests.api.test_analysis import add_file,client
from tests.queue.test_real_worker import worker_stack
from tests.queue.test_dataset_queue import create_version,get_version,wait_task
from tests.queue.test_dataset_preparation_queue import bootstrap,preparation,wait_review,decide,assert_local_only

pytestmark=pytest.mark.skipif(os.environ.get('PAPERASSIST_RUN_QUEUE_TESTS')!='1',reason='Explicit isolated Linux quality queue test disabled.')

@pytest.fixture
def quality_worker_stack(postgres_schema,tmp_path):
    test_id=postgres_schema.schema.removeprefix('pa_test_')
    # Use the existing private-directory protection only for this new test
    # configuration directory; system and Docker permissions remain unchanged.
    stack=worker_stack.prepare(PROJECT_ROOT,local_config(),test_id=test_id,assets=tmp_path/'data')
    assert stack.project=='pa-test-'+test_id
    assert worker_stack.docker(['info','--format','{{.OSType}}'],timeout=15).strip()=='linux'
    evidence=PROJECT_ROOT/'script'/'.runtime'/'stage04-batch07'/('queue-'+test_id+'.json')
    try:
        worker_stack.compose(stack,['build','worker'],timeout=1200)
        yield stack
    finally:
        worker_stack.stop(stack)
        import shutil
        retained=evidence.parent/('queue-assets-'+test_id)
        if (tmp_path/'data').exists():
            shutil.copytree(tmp_path/'data',retained,dirs_exist_ok=False)
        evidence.write_text(json.dumps(dict(project=stack.project,schema=postgres_schema.schema,assets=str(retained),mounted_assets=str(tmp_path/'data'),
            containers=worker_stack.owned_containers(stack),volumes_retained=True,private_directory_protected=True,
            system_or_docker_acl_modified=False),indent=2),encoding='utf-8')

def quality_task(client,base,parent,key):
    defaults=client.get(base+'/prepared-dataset-versions/'+parent['id']+'/quality-defaults')
    assert defaults.status_code==200,defaults.text
    request=dict(base_dataset_id=parent['id'],recipe=defaults.json()['recipe'])
    response=client.post(base+'/dataset-quality-preparations',json=request,headers={'Idempotency-Key':key})
    assert response.status_code==202,response.text
    return response.json()

def test_linux_quality_wait_restart_revision_and_both_crash_windows(client,quality_worker_stack,tmp_path):
    stack=quality_worker_stack; override=bootstrap(stack,tmp_path)
    base,_=add_file(client,[['Value','Group'],[1,' A '],[2,'NA'],[2,'NA']])
    raw=create_version(client,base,0)
    assert wait_task(client,raw['task']['id'])['status']=='succeeded'
    first=get_version(client,base,raw['id'])['datasets'][0]
    baseline=preparation(client,base,first,'quality-baseline')
    decide(client,wait_review(client,baseline['id']),'baseline-approve')
    assert wait_task(client,baseline['id'])['status']=='succeeded'
    parent=client.get('/api/v1/tasks/'+baseline['id']+'/dataset-preparation').json()['result']

    task=quality_task(client,base,parent,'quality-restart')
    view=wait_review(client,task['id']); original_receipt=client.get(view['impact_download_url']).content
    with database_connection() as db:
        attempt=db.execute('SELECT * FROM task_attempts WHERE task_id=%s',(task['id'],)).fetchone()
        assert attempt['finished_at'] and attempt['lease_owner'] is None and attempt['lease_expires_at'] is None
    # The actual worker has concurrency one: another completed task proves the wait released it.
    later=create_version(client,base,1)
    assert wait_task(client,later['task']['id'])['status']=='succeeded'
    worker_stack.compose(stack,['stop','--timeout','45','worker'],timeout=100)
    same=wait_review(client,task['id']); assert same['wait']==view['wait']
    assert client.get(same['impact_download_url']).content==original_receipt
    recipe=copy.deepcopy(view['recipe']); recipe['fields'][1].update(trim_text=True,missing_markers=['NA']); recipe['duplicate_policy']='exact'
    _,stale=decide(client,view,'revise-quality','revise',recipe)
    worker_stack.compose(stack,['--file',str(override),'up','-d','--wait','--wait-timeout','90'],timeout=180)
    changed=wait_review(client,task['id']); assert changed['recipe_revision']==2
    assert changed['preview']['changed_cell_count']==3 and changed['preview']['duplicate_excluded_row_count']==1
    assert client.get(view['impact_download_url']).status_code==409
    stale['operation']='approve'; stale['recipe']=None
    assert client.post('/api/v1/tasks/'+task['id']+'/dataset-preparation/decision',json=stale,headers={'Idempotency-Key':'late-quality'}).status_code==409
    receipt=client.get(changed['impact_download_url']).content
    worker_stack.compose(stack,['stop','--timeout','45','worker'],timeout=100)
    approved,body=decide(client,changed,'approve-quality')
    worker_stack.compose(stack,['--file',str(override),'up','-d','--wait','--wait-timeout','90'],timeout=180)
    assert wait_task(client,task['id'])['status']=='succeeded'
    result=client.get('/api/v1/tasks/'+task['id']+'/dataset-preparation').json()['result']
    assert client.get(result['impact_download_url']).content==receipt
    assert client.post('/api/v1/tasks/'+task['id']+'/dataset-preparation/decision',json=body,headers={'Idempotency-Key':'approve-quality'}).json()==approved

    for mode in ('preview','publish'):
        task=quality_task(client,base,parent,'preparation-crash-'+mode)
        if mode=='publish': decide(client,wait_review(client,task['id']),'approve-crash-publish')
        marker=tmp_path/'data'/('.preparation-crash-'+task['id'])
        deadline=time.monotonic()+45
        while not marker.exists() and time.monotonic()<deadline: time.sleep(.2)
        assert marker.exists()
        with database_connection() as db:
            assert db.execute('SELECT status FROM tasks WHERE id=%s',(task['id'],)).fetchone()['status']=='running'
            assert db.execute('SELECT count(*) AS n FROM prepared_dataset_versions WHERE task_id=%s',(task['id'],)).fetchone()['n']==0
            assert db.execute('SELECT next_node FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',(task['id'],)).fetchone()['next_node']==('prepare_preview' if mode=='preview' else 'publish')
        if mode=='preview':
            recovered=wait_review(client,task['id'],timeout=110)
            assert recovered['task']['current_attempt']==2
            decide(client,recovered,'approve-crash-preview')
        done=wait_task(client,task['id'],timeout=110)
        assert done['status']=='succeeded' and done['current_attempt']==3
        with database_connection(write=True) as db:
            assert db.execute('SELECT count(*) AS n FROM prepared_dataset_versions WHERE task_id=%s',(task['id'],)).fetchone()['n']==1
            assert db.execute('SELECT count(*) AS n FROM prepared_dataset_derivations d JOIN prepared_dataset_versions p ON p.id=d.prepared_dataset_id WHERE p.task_id=%s',(task['id'],)).fetchone()['n']==1
            db.execute('UPDATE task_outbox SET published_at=NULL,available_at=clock_timestamp() WHERE task_id=%s',(task['id'],))
        time.sleep(3)
        assert client.get('/api/v1/tasks/'+task['id']).json()['current_attempt']==3
    assert_local_only(tmp_path)
