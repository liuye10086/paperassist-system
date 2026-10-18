"""Opt-in real single-worker waits, restart and two durable crash windows."""
import copy
import json
import os
from pathlib import Path
import time

import pytest

from app.db.database import database_connection
from app.domain.dataset_preparation.service import candidate_id
from tests.api.test_analysis import add_file,client  # noqa: F401
from tests.queue.test_dataset_queue import create_version,get_version,wait_task
from tests.queue.test_real_worker import isolated_worker_stack,worker_stack  # noqa: F401

pytestmark = pytest.mark.skipif(os.environ.get('PAPERASSIST_RUN_QUEUE_TESTS') != '1',
    reason='Explicit isolated preparation queue test is disabled.')


def bootstrap(stack,tmp_path,*,cpu=None):
    if cpu is not None and cpu not in {str(value) for value in range(16)}:
        raise ValueError('Explicit TEST Worker CPU must be 0 through 15')
    override = tmp_path/'preparation-worker.json'
    override.write_text(json.dumps({'services':{'worker':{
        **({'cpuset':cpu} if cpu is not None else {}),
        'command':['python','/app/preparation_bootstrap.py','worker'],
        'volumes':[{'type':'bind','source':str(Path(__file__).with_name('preparation_bootstrap.py').resolve()),
            'target':'/app/preparation_bootstrap.py','read_only':True}]}}}),encoding='utf-8')
    worker_stack.compose(stack,['--file',str(override),'up','-d','--wait','--wait-timeout','90'],timeout=180)
    return override


def preparation(client,base,raw,key):
    defaults = client.get(base+'/dataset-versions/'+raw['id']+'/preparation-defaults')
    assert defaults.status_code == 200,defaults.text
    response = client.post(base+'/dataset-preparations',json=dict(dataset_id=raw['id'],recipe=defaults.json()['recipe']),
        headers={'Idempotency-Key':key})
    assert response.status_code == 202,response.text
    return response.json()


def wait_review(client,task_id,timeout=105):
    deadline = time.monotonic()+timeout
    while time.monotonic()<deadline:
        response = client.get('/api/v1/tasks/'+task_id+'/dataset-preparation')
        assert response.status_code == 200,response.text
        view = response.json()
        if view['task']['status'] == 'waiting_confirmation':
            return view
        assert view['task']['status'] != 'failed',view
        time.sleep(.2)
    pytest.fail('The isolated preparation worker did not reach confirmation in time.')


def decide(client,view,key,operation='approve',recipe=None):
    body = dict(operation=operation,recipe=recipe,wait_id=view['wait']['id'],checkpoint_id=view['checkpoint_id'],
        expected_task_revision=view['task']['revision'],input_version=view['task']['input_version'])
    response = client.post('/api/v1/tasks/'+view['task']['id']+'/dataset-preparation/decision',json=body,
        headers={'Idempotency-Key':key})
    assert response.status_code == 202,response.text
    return response.json(),body


def assert_local_only(tmp_path):
    assert not (tmp_path/'data'/'.unexpected-preparation-network').exists()
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0
        assert db.execute('SELECT count(*) AS n FROM budget_reservations').fetchone()['n'] == 0


def test_wait_frees_worker_and_restart_can_revise_then_approve(client,isolated_worker_stack,tmp_path):
    stack = isolated_worker_stack
    override = bootstrap(stack,tmp_path)
    base,_ = add_file(client,[['Value','Group'],[1,' A '],[2,'NA']])
    raw = create_version(client,base,0)
    assert wait_task(client,raw['task']['id'])['status'] == 'succeeded'
    first = get_version(client,base,raw['id'])['datasets'][0]
    task = preparation(client,base,first,'preparation-restart')
    view = wait_review(client,task['id'])
    preview_bytes = client.get(view['preview_download_url']).content
    with database_connection() as db:
        attempt = db.execute('SELECT * FROM task_attempts WHERE task_id=%s',(task['id'],)).fetchone()
        assert attempt['finished_at'] and attempt['lease_owner'] is None and attempt['lease_expires_at'] is None
    # Worker concurrency is one: successful V2 proves V1's human wait returned.
    later = create_version(client,base,1)
    assert wait_task(client,later['task']['id'])['status'] == 'succeeded'
    assert wait_review(client,task['id'])['source']['dataset_id'] == first['id']
    worker_stack.compose(stack,['stop','--timeout','45','worker'],timeout=100)
    stopped = client.get('/api/v1/tasks/'+task['id']+'/dataset-preparation').json()
    assert stopped['wait'] == view['wait'] and stopped['checkpoint_id'] == view['checkpoint_id']
    assert client.get(stopped['preview_download_url']).content == preview_bytes
    recipe = copy.deepcopy(stopped['recipe'])
    recipe['fields'][1].update(trim_text=True,missing_markers=['NA'])
    revised,_ = decide(client,stopped,'revise-after-restart','revise',recipe)
    worker_stack.compose(stack,['--file',str(override),'up','-d','--wait','--wait-timeout','90'],timeout=180)
    changed = wait_review(client,task['id'])
    assert changed['recipe_revision'] == 2 and changed['preview']['changed_cell_count'] == 2
    assert changed['wait']['id'] != stopped['wait']['id']
    worker_stack.compose(stack,['stop','--timeout','45','worker'],timeout=100)
    approved,body = decide(client,changed,'approve-after-restart')
    accepted_bytes = client.get(changed['preview_download_url']).content
    worker_stack.compose(stack,['--file',str(override),'up','-d','--wait','--wait-timeout','90'],timeout=180)
    done = wait_task(client,task['id'])
    assert done['status'] == 'succeeded',done
    result = client.get('/api/v1/tasks/'+task['id']+'/dataset-preparation').json()['result']
    assert client.get(result['download_url']).content == accepted_bytes
    assert result['parent_dataset_id'] == first['id'] and result['parent_dataset_version'] == 1
    replay = client.post('/api/v1/tasks/'+task['id']+'/dataset-preparation/decision',json=body,headers={'Idempotency-Key':'approve-after-restart'})
    assert replay.json() == approved
    assert_local_only(tmp_path)


def test_preview_and_publication_process_death_recover_with_unique_publish(client,isolated_worker_stack,tmp_path):
    stack = isolated_worker_stack
    bootstrap(stack,tmp_path)
    base,_ = add_file(client)
    raw = create_version(client,base,0)
    assert wait_task(client,raw['task']['id'])['status'] == 'succeeded'
    first = get_version(client,base,raw['id'])['datasets'][0]
    for mode in ('preview','publish'):
        task = preparation(client,base,first,'preparation-crash-'+mode)
        if mode == 'publish':
            view = wait_review(client,task['id'])
            decide(client,view,'approve-'+mode)
        marker = tmp_path/'data'/('.preparation-crash-'+task['id'])
        deadline = time.monotonic()+45
        while not marker.exists() and time.monotonic()<deadline:
            time.sleep(.2)
        assert marker.exists(),client.get('/api/v1/tasks/'+task['id']).json()
        assert marker.read_text(encoding='ascii') == ('waiting' if mode == 'preview' else 'succeeded')
        with database_connection() as db:
            persisted = db.execute('SELECT * FROM tasks WHERE id=%s',(task['id'],)).fetchone()
            assert persisted['status'] == 'running'
            assert db.execute('SELECT count(*) AS n FROM prepared_dataset_versions WHERE task_id=%s',(task['id'],)).fetchone()['n'] == 0
            assert db.execute("SELECT count(*) AS n FROM task_waits WHERE task_id=%s AND status='open'",(task['id'],)).fetchone()['n'] == 0
            checkpoint = db.execute('SELECT next_node FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',(task['id'],)).fetchone()
            assert checkpoint['next_node'] == ('prepare_preview' if mode == 'preview' else 'publish')
        candidates = list((tmp_path/'data'/'prepared-datasets'/candidate_id(task['id'])).glob('*.json'))
        assert len(candidates) == 1
        candidate_bytes = candidates[0].read_bytes()
        if mode == 'preview':
            recovered = wait_review(client,task['id'],timeout=110)
            assert recovered['task']['current_attempt'] == 2
            decide(client,recovered,'approve-preview')
        done = wait_task(client,task['id'],timeout=110)
        assert done['status'] == 'succeeded' and done['current_attempt'] == 3,done
        result = client.get('/api/v1/tasks/'+task['id']+'/dataset-preparation').json()['result']
        assert client.get(result['download_url']).content == candidate_bytes
        with database_connection(write=True) as db:
            assert db.execute('SELECT count(*) AS n FROM prepared_dataset_versions WHERE task_id=%s',(task['id'],)).fetchone()['n'] == 1
            db.execute('UPDATE task_outbox SET published_at=NULL,available_at=clock_timestamp() WHERE task_id=%s',(task['id'],))
        time.sleep(3)
        assert client.get('/api/v1/tasks/'+task['id']).json()['current_attempt'] == 3
    assert [item['version'] for item in client.get(base+'/prepared-dataset-versions').json()['items']] == [2,1]
    assert_local_only(tmp_path)
