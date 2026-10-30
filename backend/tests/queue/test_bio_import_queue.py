"""Opt-in CR-B01 Linux queue acceptance; synthetic data and isolated schema only."""
import os
import time
import pytest
from app.db.database import database_connection
from tests.api.test_projects import client
from tests.integration.test_bio_import_publication import create_import, confirm
from tests.queue.test_real_worker import isolated_worker_stack, worker_stack

pytestmark=pytest.mark.skipif(os.environ.get('PAPERASSIST_RUN_QUEUE_TESTS')!='1',reason='Explicit bio queue test disabled')


def wait_import(client,base,identity,status):
    deadline=time.monotonic()+100
    while time.monotonic()<deadline:
        response=client.get(base+'/bio-imports/'+identity)
        assert response.status_code==200,response.text
        view=response.json()
        assert view['task']['status']!='failed',view
        if view['task']['status']==status:
            return view
        time.sleep(.25)
    pytest.fail('Bio import queue did not reach '+status)


def test_linux_bio_wait_restart_confirm_publish(client,isolated_worker_stack):
    stack=isolated_worker_stack
    base,created,file_id,original=create_import(client)
    assert created['task']['status']=='queued'
    worker_stack.compose(stack,['up','-d','--wait','--wait-timeout','90'],timeout=180)
    waiting=wait_import(client,base,created['id'],'waiting_confirmation')
    with database_connection() as db:
        attempt=db.execute('SELECT * FROM task_attempts WHERE task_id=%s',(created['task']['id'],)).fetchone()
        assert attempt['finished_at'] and attempt['lease_owner'] is None
        assert db.execute('SELECT count(*) AS n FROM bio_dataset_versions').fetchone()['n']==0
    # A second queued slice demonstrates that the first human wait freed Worker.
    second_base,second,_,_=create_import(client)
    wait_import(client,second_base,second['id'],'waiting_confirmation')
    worker_stack.compose(stack,['stop','--timeout','45','worker'],timeout=100)
    stopped=wait_import(client,base,created['id'],'waiting_confirmation')
    assert stopped['candidate']['sha256']==waiting['candidate']['sha256']
    assert stopped['checkpoint_id']==waiting['checkpoint_id'] and stopped['wait_id']==waiting['wait_id']
    queued=confirm(client,base,created,stopped,'after-worker-restart')
    assert queued.status_code==202,queued.text
    worker_stack.compose(stack,['up','-d','--wait','--wait-timeout','90'],timeout=180)
    done=wait_import(client,base,created['id'],'succeeded')
    source=done['result_source']
    path=base+f"/bio-datasets/{source['dataset_id']}/versions/{source['dataset_version_id']}"
    preview=client.get(path+'/matrix-preview')
    assert preview.status_code==200,preview.text
    assert preview.json()['values']==[[5,2,0],[1,0,4]]
    assert client.get(base+'/files/'+file_id+'/download').content==original
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']==0
        assert db.execute('SELECT count(*) AS n FROM budget_reservations').fetchone()['n']==0
        assert db.execute('SELECT count(*) AS n FROM bio_dataset_versions WHERE import_id=%s',(created['id'],)).fetchone()['n']==1
