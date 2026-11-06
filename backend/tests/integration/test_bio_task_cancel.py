"""Real SQL cancellation fences; synthetic outputs never assert scientific validity."""
from app.db.database import database_connection
from tests.api.test_projects import client
from tests.integration.test_bio_analysis_wait import create, run, confirm, payload_engine
from tests.integration.test_project_ownership import account_client
import pytest


def cancel(client, task, revision=None):
    return client.post('/api/v1/tasks/'+task['id']+'/cancel',json={'expected_revision':revision or task['revision']})


def test_queued_cancel_idempotent_and_owner_revision_bound(client,monkeypatch,tmp_path):
    _,created,staging,_=create(client,monkeypatch,tmp_path)
    task=created['task']
    workspace=client.get('/api/v1/tasks/'+task['id']+'/workspace')
    assert workspace.status_code==200,workspace.text
    assert workspace.json()['allowed_actions']==['cancel']
    other,_=account_client('cancel-other@example.test')
    try: assert cancel(other,task).status_code==404
    finally: other.close()
    assert cancel(client,task,99).status_code==409
    response=cancel(client,task)
    assert response.status_code==200,response.text
    assert response.json()['status']=='cancelled'
    assert client.get('/api/v1/tasks/'+task['id']+'/workspace').json()['allowed_actions']==[]
    assert cancel(client,task).json()==response.json()
    assert cancel(client,task,response.json()['revision']).json()==response.json()
    assert run(task,staging,lambda *a,**k:pytest.fail('cancelled queue computed')) is None
    assert client.post('/api/v1/tasks/'+task['id']+'/retry',json={'expected_revision':response.json()['revision']}).status_code==409
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM task_attempts WHERE task_id=%s',(task['id'],)).fetchone()['n']==0
        assert db.execute("SELECT count(*) AS n FROM task_events WHERE task_id=%s AND event_type='cancelled'",(task['id'],)).fetchone()['n']==1


def test_cancel_wins_before_publication_and_retains_staging(client,monkeypatch,tmp_path):
    base,created,staging,_=create(client,monkeypatch,tmp_path)
    def engine(payload,output,mode):
        result=payload_engine(payload,output,mode)
        current=client.get('/api/v1/tasks/'+created['task']['id']).json()
        response=cancel(client,current)
        assert response.status_code==200,response.text
        return result
    assert run(created['task'],staging,engine) is None
    assert list(staging.rglob('receipt.json'))
    with database_connection() as db:
        task=db.execute('SELECT * FROM tasks WHERE id=%s',(created['task']['id'],)).fetchone()
        assert task['status']=='cancelled'
        assert db.execute('SELECT status,lease_owner FROM task_attempts WHERE task_id=%s',(task['id'],)).fetchone()=={'status':'cancelled','lease_owner':None}
        assert db.execute('SELECT count(*) AS n FROM bio_processed_dataset_versions').fetchone()['n']==0


def test_completed_publication_wins_cancel_conflict(client,monkeypatch,tmp_path):
    base,created,staging,_=create(client,monkeypatch,tmp_path)
    run(created['task'],staging)
    queued=confirm(client,base,created,client.get(base+'/bio-analysis-runs/'+created['id']).json()).json()
    done=run(queued,staging)
    assert done['status']=='succeeded'
    assert cancel(client,done).status_code==409
    assert client.get('/api/v1/tasks/'+done['id']).json()['result_bio_processed_dataset_version_id']==done['result_bio_processed_dataset_version_id']
