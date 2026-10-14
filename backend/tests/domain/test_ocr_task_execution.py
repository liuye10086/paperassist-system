"""OCR lifecycle uses existing task attempts and original immutable snapshot."""
import pytest
from tests.api.test_projects import client  # noqa: F401
from tests.api.test_ocr_versions import uploaded_image
from tests.helpers.ocr_samples import ocr_result
from app.adapters.task_execution_store import TaskExecutionStore,LeaseLost
from app.adapters.document_parse_store import DocumentParseStore
from app.db.database import database_connection
from app.domain.tasks.file_parse_execution import run_parse_file_task
from app.core.exceptions import StorageError


def test_ocr_worker_selects_isolated_parser_and_forwards_started_callback(client,monkeypatch):
    from app.adapters import ocr_process
    started=[]
    def isolated(*args,**kwargs):
        assert args[2]=='png' and args[3]==[1]
        if kwargs.get('on_started'):kwargs['on_started'](123)
        return ocr_result(*args)
    monkeypatch.setattr(ocr_process,'parse_ocr_isolated',isolated)
    _,_,_,item,_=uploaded_image(client)
    result=run_parse_file_task(item['task']['id'],1,on_started=started.append)
    assert result['status']=='succeeded' and started==[123]


def test_ocr_expired_lease_cannot_publish_and_entire_input_is_recovered(client):
    _,_,_,item,content=uploaded_image(client)
    repo=TaskExecutionStore();lease=repo.claim(item['task']['id'],1,task_type='parse_file')
    store=DocumentParseStore(repo);snapshot,_=store.load(lease)
    result=ocr_result(content,'scan.png','png',[1],snapshot['settings'])
    with database_connection(write=True) as db:
        db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second'")
    with pytest.raises(LeaseLost):store.complete(lease,snapshot,result)
    assert repo.recover_expired()==1
    with database_connection() as db:
        row=db.execute('SELECT * FROM tasks WHERE id=%s',(item['task']['id'],)).fetchone()
        assert row['input_snapshot']==snapshot
        assert db.execute('SELECT completed_at FROM file_parse_results').fetchone()['completed_at'] is None
    assert run_parse_file_task(item['task']['id'],row['revision'],parser=ocr_result)['status']=='succeeded'


def test_ocr_retry_keeps_snapshot_and_clears_failed_completion(client):
    _,_,_,item,_=uploaded_image(client)
    def timeout(*args):raise StorageError('parse_timeout','timeout',422)
    failed=run_parse_file_task(item['task']['id'],1,parser=timeout)
    with database_connection() as db:
        snapshot=db.execute('SELECT input_snapshot FROM tasks WHERE id=%s',(failed['id'],)).fetchone()['input_snapshot']
        assert db.execute('SELECT completed_at FROM file_parse_results').fetchone()['completed_at'] is not None
    workspace=client.get('/api/v1/tasks/'+failed['id']+'/workspace').json()
    assert workspace['allowed_actions']==['retry']
    retry=client.post('/api/v1/tasks/'+failed['id']+'/retry',json={'expected_revision':failed['revision']})
    assert retry.status_code==202,retry.text
    with database_connection() as db:
        assert db.execute('SELECT input_snapshot FROM tasks WHERE id=%s',(failed['id'],)).fetchone()['input_snapshot']==snapshot
        assert db.execute('SELECT completed_at FROM file_parse_results').fetchone()['completed_at'] is None
    assert run_parse_file_task(failed['id'],retry.json()['revision'],parser=ocr_result)['status']=='succeeded'
