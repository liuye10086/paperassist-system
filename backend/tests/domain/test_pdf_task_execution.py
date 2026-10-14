"""Real PDF task state transitions with isolated database and local parser."""
from tests.api.test_projects import client, create_project  # noqa: F401
from tests.api.test_file_batches import register
from tests.helpers.pdf_samples import pdf_bytes, TEXT
from app.adapters.pdf_parser import parse_pdf
from app.adapters.task_execution_store import TaskExecutionStore
from app.core.exceptions import StorageError
from app.db.database import database_connection
from app.domain.tasks.file_parse_execution import run_parse_file_task


def queued_pdf(client):
    project = create_project(client)
    base, batch, item, content = register(client, project, pdf_bytes([TEXT]), 'source.pdf')
    response = client.post(base+'/'+batch['id']+'/items/'+item['client_id'],
                           files={'file': (item['filename'], content)})
    assert response.status_code == 202, response.text
    return response.json()


def completed_at(task_id):
    with database_connection() as db:
        return db.execute('SELECT completed_at FROM file_parse_results WHERE task_id=%s',
                          (task_id,)).fetchone()['completed_at']


def test_pdf_worker_selects_pdf_parser_and_document_publication(client, monkeypatch):
    from app.adapters import pdf_process
    monkeypatch.setattr(pdf_process, 'parse_pdf_isolated', parse_pdf)
    item = queued_pdf(client)
    result = run_parse_file_task(item['task']['id'], 1)
    assert result['status'] == 'succeeded', result
    with database_connection() as db:
        manifest = db.execute('SELECT result_json FROM file_parse_results WHERE task_id=%s',
                              (item['task']['id'],)).fetchone()['result_json']
        assert manifest['kind'] == 'pdf_document'
        assert manifest['summary']['counts']['pages'] == 1
    assert run_parse_file_task(item['task']['id'], 1) is None


def test_pdf_failed_time_clears_during_manual_retry(client):
    item = queued_pdf(client)
    def timeout(*args):
        raise StorageError('parse_timeout', 'synthetic timeout', 422)
    failed = run_parse_file_task(item['task']['id'], 1, parser=timeout)
    assert failed['status'] == 'failed'
    assert completed_at(failed['id']) is not None
    retried = client.post('/api/v1/tasks/'+failed['id']+'/retry',
                          json={'expected_revision': failed['revision']})
    assert retried.status_code == 202, retried.text
    assert retried.json()['status'] == 'queued'
    assert completed_at(failed['id']) is None
    assert run_parse_file_task(failed['id'], retried.json()['revision'], parser=parse_pdf)['status'] == 'succeeded'


def test_pdf_recovery_clears_intermediate_completion_then_finishes_exhaustion(client):
    item = queued_pdf(client)
    task_id = item['task']['id']
    repository = TaskExecutionStore()
    revision = 1
    for attempt in range(1, 4):
        assert repository.claim(task_id, revision, task_type='parse_file') is not None
        with database_connection(write=True) as db:
            db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s", (task_id,))
        assert repository.recover_expired() == 1
        with database_connection() as db:
            task = db.execute('SELECT status,revision FROM tasks WHERE id=%s', (task_id,)).fetchone()
        if attempt < 3:
            assert task['status'] == 'queued'
            assert completed_at(task_id) is None
            revision = task['revision']
        else:
            assert task['status'] == 'failed'
            assert completed_at(task_id) is not None

def test_encrypted_pdf_rejection_survives_task_and_batch_publication(client):
    project=create_project(client)
    base,batch,item,content=register(client,project,pdf_bytes([TEXT],encrypted=True),'locked.pdf')
    uploaded=client.post(base+'/'+batch['id']+'/items/'+item['client_id'],files={'file':('locked.pdf',content)})
    assert uploaded.status_code==202,uploaded.text
    result=run_parse_file_task(uploaded.json()['task']['id'],1,parser=parse_pdf)
    assert result['status']=='failed'
    assert result['error_code']=='encrypted_document'
    from app.domain.tasks.errors import error_category
    assert error_category(result['error_code'])=='source'
    public=client.get('/api/v1/tasks/'+result['id']).json()
    assert public['error_code']=='encrypted_document'
    batch_item=client.get(base+'/'+batch['id']).json()['items'][0]
    assert batch_item['error']['code']=='encrypted_document'
    assert batch_item['task']['error_code']=='encrypted_document'
    file_url=f"/api/v1/projects/{project['id']}/files/{uploaded.json()['file_id']}"
    assert client.get(file_url+'/details').json()['error']['code']=='encrypted_document'
    assert client.get(file_url+'/document-versions').json()['items'][0]['error']['code']=='encrypted_document'
    with database_connection() as db:
        assert db.execute('SELECT error_code FROM tasks WHERE id=%s',(result['id'],)).fetchone()['error_code']=='encrypted_document'
