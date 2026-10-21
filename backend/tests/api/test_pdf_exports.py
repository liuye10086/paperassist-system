import pytest
import sys
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_manuscripts import setup,body
from tests.api.test_literature_evidence import post
from app.domain.tasks.execution import run_task


@pytest.fixture(autouse=True)
def fake_renderer(monkeypatch):
    monkeypatch.setattr('app.domain.pdf_exports.service.renderer_identity',lambda: {'contract':'test-v1'})

def successful_docx(client):
    path,_,_=setup(client)
    root=post(client,path,body(),'draft').json()
    run_task(root['versions'][0]['task_id'],1)
    exported=post(client,path+'/'+root['id']+'/versions/1/exports',{},'docx').json()
    run_task(exported['task_id'],1)
    return path.removesuffix('/manuscripts')+'/pdf-exports',exported


def test_create_pdf_freezes_exact_docx_and_request_key(client):
    path,source=successful_docx(client)
    request=dict(source_kind='manuscript_export',source_id=source['id'],request_key='pdf-one')
    response=client.post(path,json=request)
    assert response.status_code==201,response.text
    saved=response.json()
    assert saved['status']=='queued' and saved['source_sha256']
    assert client.post(path,json=request).json()==saved
    assert client.post(path,json=dict(request,source_id='missing')).status_code==409
    assert client.get(path).json()['items']==[saved]
    assert client.get(path+'/'+saved['id']+'/download').status_code==409


def test_pdf_runs_once_and_download_rechecks_docx_and_pdf(client,monkeypatch):
    from types import SimpleNamespace
    from app.core.config import get_data_dir
    path,source=successful_docx(client)
    saved=client.post(path,json=dict(source_kind='manuscript_export',source_id=source['id'],request_key='pdf')).json()
    calls=[]
    def render(raw):
        calls.append(raw)
        return SimpleNamespace(content=b'%PDF-1.7\nfake verified output',manifest={'contract':'test-v1'})
    monkeypatch.setattr('app.domain.pdf_exports.execution.render_pdf',render)
    run_task(saved['task_id'],1);run_task(saved['task_id'],1)
    complete=client.get(path+'/'+saved['id']).json()
    assert complete['status']=='succeeded',complete
    assert len(calls)==1
    assert client.get(complete['download_url']).content.startswith(b'%PDF-')
    from pathlib import Path
    docx=Path(get_data_dir())/'manuscript_exports'/(source['id']+'.docx')
    docx.write_bytes(b'changed')
    assert client.get(complete['download_url']).status_code==409
    assert client.get(path+'/'+saved['id']).json()['sha256']==complete['sha256']


def test_conversion_failure_retains_docx_and_retry_is_new_idempotent_object(client,monkeypatch):
    from app.core.exceptions import StorageError
    path,source=successful_docx(client)
    saved=client.post(path,json=dict(source_kind='manuscript_export',source_id=source['id'],request_key='pdf')).json()
    def fail(raw): raise StorageError('pdf_conversion_timeout','private path /secret',502)
    monkeypatch.setattr('app.domain.pdf_exports.execution.render_pdf',fail)
    run_task(saved['task_id'],1)
    failed=client.get(path+'/'+saved['id']).json()
    assert failed['status']=='failed' and failed['error_code']=='pdf_conversion_timeout',failed
    retry_path=path+'/'+saved['id']+'/retry'
    response=client.post(retry_path,json={'request_key':'retry'})
    assert response.status_code==201,response.text
    retried=response.json()
    assert retried['id']!=saved['id'] and retried['parent_export_id']==saved['id']
    assert client.post(retry_path,json={'request_key':'retry'}).json()==retried
    assert client.get(path+'/'+saved['id']).json()==failed
    from pathlib import Path
    from app.core.config import get_data_dir
    assert (Path(get_data_dir())/'manuscript_exports'/(source['id']+'.docx')).read_bytes().startswith(b'PK')
    assert not list((Path(get_data_dir())/'pdf_exports').glob('*'))


def test_pdf_task_workspace_and_audit_are_bound_to_exact_source(client,monkeypatch):
    path,source=successful_docx(client)
    saved=client.post(path,json=dict(source_kind='manuscript_export',source_id=source['id'],request_key='pdf')).json()
    workspace=client.get('/api/v1/tasks/'+saved['task_id']+'/workspace')
    assert workspace.status_code==200,workspace.text
    assert workspace.json()['task']['task_type']=='pdf_export'
    from app.db.database import database_connection
    from app.maintenance.pdf_export_audit import audit_pdf_exports
    with database_connection() as db:
        assert not any(item['invalid'] for item in audit_pdf_exports(db))


def test_expired_lease_recovery_does_not_steal_live_attempt_and_stale_worker_cannot_publish(client,monkeypatch):
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.db.database import database_connection
    from types import SimpleNamespace
    path,source=successful_docx(client)
    saved=client.post(path,json=dict(source_kind='manuscript_export',source_id=source['id'],request_key='pdf')).json()
    execution=TaskExecutionStore()
    old=execution.claim(saved['task_id'],1)
    assert execution.recover_expired()==0
    assert execution.claim(saved['task_id'],2) is None
    with database_connection(write=True) as db:
        db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s",(saved['task_id'],))
    assert execution.recover_expired()==1
    assert not execution.heartbeat(old)
    monkeypatch.setattr('app.domain.pdf_exports.execution.render_pdf',lambda raw:SimpleNamespace(content=b'%PDF-1.7\nnew',manifest={'contract':'test-v1'}))
    with database_connection() as db:
        task=db.execute('SELECT * FROM tasks WHERE id=%s',(saved['task_id'],)).fetchone()
    assert run_task(saved['task_id'],task['revision'])['status']=='succeeded'


from tests.api.test_boxplot import cloud  # noqa: F401
from tests.integration.test_explanations import writer  # noqa: F401
from tests.integration.test_batch05_collection_persistence import collection_case  # noqa: F401


@pytest.mark.skipif(sys.platform!='linux',reason='Existing statistical DOCX producer requires Linux sandbox.')
def test_single_report_source_uses_exact_existing_docx_without_model_calls(client,cloud,writer,monkeypatch):
    from tests.integration.test_reports import report_ready,export
    from types import SimpleNamespace
    base,_,_,figure,explanation,url=report_ready(client)
    report=export(client,url,figure,explanation).json()['report']
    calls=(len(cloud.calls),len(writer.calls))
    path=base.split('/files/')[0]+'/pdf-exports'
    saved=client.post(path,json=dict(source_kind='report',source_id=report['id'],request_key='pdf'))
    assert saved.status_code==201,saved.text
    saved=saved.json()
    monkeypatch.setattr('app.domain.pdf_exports.execution.render_pdf',lambda raw:SimpleNamespace(content=b'%PDF-1.7\nreport',manifest={'contract':'test-v1'}))
    run_task(saved['task_id'],1)
    assert client.get(path+'/'+saved['id']).json()['status']=='succeeded'
    assert calls==(len(cloud.calls),len(writer.calls))


@pytest.mark.skipif(sys.platform!='linux',reason='Existing statistical DOCX producer requires Linux sandbox.')
def test_collection_report_source_keeps_exact_version(collection_case,client,monkeypatch):
    from tests.integration.test_batch05_collection_persistence import body as collection_body
    from app.domain.report_collections.execution import run_collection_word_task
    from types import SimpleNamespace
    repository,project,sample,explanation=collection_case
    request=collection_body(sample);request.items[0].explanation_id=explanation['id']
    collection=repository.create(project,request,'collection')
    task=collection['versions'][0]['requests'][0]
    assert run_collection_word_task(task['task_id'],1)['status']=='succeeded'
    current=repository.get(project,collection['id'])
    report=current['versions'][0]['requests'][0]['report']
    path=f'/api/v1/projects/{project}/pdf-exports'
    response=client.post(path,json=dict(source_kind='collection_report',source_id=report['id'],request_key='pdf'))
    assert response.status_code==201,response.text
    saved=response.json()
    monkeypatch.setattr('app.domain.pdf_exports.execution.render_pdf',lambda raw:SimpleNamespace(content=b'%PDF-1.7\ncollection',manifest={'contract':'test-v1'}))
    run_task(saved['task_id'],1)
    assert client.get(path+'/'+saved['id']).json()['status']=='succeeded'


def test_pdf_rejects_missing_source_and_foreign_project(client):
    path,source=successful_docx(client)
    assert client.post(path,json=dict(source_kind='report',source_id='missing',request_key='missing')).status_code==404
    saved=client.post(path,json=dict(source_kind='manuscript_export',source_id=source['id'],request_key='pdf')).json()
    from tests.integration.test_project_ownership import account_client
    with account_client('pdf-other@example.test')[0] as other:
        assert other.get(path).status_code==404
        assert other.get(path+'/'+saved['id']).status_code==404
        assert other.post(path,json=dict(source_kind='manuscript_export',source_id=source['id'],request_key='foreign')).status_code==404


def test_renderer_mismatch_fails_without_publishing_and_generic_retry_cannot_mutate_old_task(client,monkeypatch):
    from types import SimpleNamespace
    path,source=successful_docx(client)
    saved=client.post(path,json=dict(source_kind='manuscript_export',source_id=source['id'],request_key='pdf')).json()
    monkeypatch.setattr('app.domain.pdf_exports.execution.render_pdf',lambda raw:SimpleNamespace(content=b'%PDF-1.7\nwrong',manifest={'contract':'other'}))
    run_task(saved['task_id'],1)
    failed=client.get(path+'/'+saved['id']).json()
    assert failed['status']=='failed' and failed['error_code']=='pdf_renderer_mismatch'
    assert client.post(path+'/'+saved['id']+'/retry',json={'request_key':'retry'}).status_code==409
    task=client.get('/api/v1/tasks/'+saved['task_id']).json()
    response=client.post('/api/v1/tasks/'+saved['task_id']+'/retry',json={'expected_revision':task['revision']})
    assert response.status_code==409,response.text
    assert client.get(path+'/'+saved['id']).json()==failed


def test_lost_lease_during_conversion_never_publishes(client,monkeypatch):
    from types import SimpleNamespace
    from app.db.database import database_connection
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.core.config import get_data_dir
    from pathlib import Path
    path,source=successful_docx(client)
    saved=client.post(path,json=dict(source_kind='manuscript_export',source_id=source['id'],request_key='pdf')).json()
    def render(raw):
        with database_connection(write=True) as db:
            db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s",(saved['task_id'],))
        TaskExecutionStore().recover_expired()
        return SimpleNamespace(content=b'%PDF-1.7\nstale',manifest={'contract':'test-v1'})
    monkeypatch.setattr('app.domain.pdf_exports.execution.render_pdf',render)
    assert run_task(saved['task_id'],1) is None
    assert client.get(path+'/'+saved['id']).json()['status']=='queued'
    assert not list((Path(get_data_dir())/'pdf_exports').glob('*'))


def test_pdf_concurrent_delivery_claims_only_one_attempt(client):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.adapters.task_execution_store import TaskExecutionStore
    path,source=successful_docx(client)
    saved=client.post(path,json=dict(source_kind='manuscript_export',source_id=source['id'],request_key='pdf')).json()
    barrier=Barrier(2)
    def claim():
        barrier.wait()
        return TaskExecutionStore().claim(saved['task_id'],1)
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(lambda _:claim(),range(2)))
    assert sum(value is not None for value in results)==1


def test_pdf_input_version_cannot_be_used_by_other_task_type(client):
    from pydantic import ValidationError
    from app.domain.tasks.contracts import TaskView
    path,source=successful_docx(client)
    saved=client.post(path,json=dict(source_kind='manuscript_export',source_id=source['id'],request_key='pdf')).json()
    task=client.get('/api/v1/tasks/'+saved['task_id']).json()
    with pytest.raises(ValidationError): TaskView.model_validate(dict(task,task_type='word_report'))


def test_publish_transaction_failure_cleans_unpublished_pdf(client,monkeypatch):
    from types import SimpleNamespace
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.core.config import get_data_dir
    from pathlib import Path
    path,source=successful_docx(client)
    saved=client.post(path,json=dict(source_kind='manuscript_export',source_id=source['id'],request_key='pdf')).json()
    monkeypatch.setattr('app.domain.pdf_exports.execution.render_pdf',lambda raw:SimpleNamespace(content=b'%PDF-1.7\ntransaction',manifest={'contract':'test-v1'}))
    original=TaskExecutionStore._finish
    def fail_publish(self,db,task,status,code):
        if status=='succeeded' and task['task_type']=='pdf_export': raise RuntimeError('private failure')
        return original(self,db,task,status,code)
    monkeypatch.setattr(TaskExecutionStore,'_finish',fail_publish)
    assert run_task(saved['task_id'],1)['status']=='failed'
    assert client.get(path+'/'+saved['id']).json()['sha256'] is None
    assert not list((Path(get_data_dir())/'pdf_exports').glob('*'))
    assert (Path(get_data_dir())/'manuscript_exports'/(source['id']+'.docx')).read_bytes().startswith(b'PK')


def test_retry_chain_is_bounded_and_old_failures_are_retained(client,monkeypatch):
    from app.core.exceptions import StorageError
    path,source=successful_docx(client)
    saved=client.post(path,json=dict(source_kind='manuscript_export',source_id=source['id'],request_key='pdf')).json()
    def fail(raw): raise StorageError('pdf_renderer_busy','private worker detail',503)
    monkeypatch.setattr('app.domain.pdf_exports.execution.render_pdf',fail)
    for i in range(4):
        assert run_task(saved['task_id'],1)['status']=='failed'
        response=client.post(path+'/'+saved['id']+'/retry',json={'request_key':f'retry-{i}'})
        if i<3:
            assert response.status_code==201,response.text
            assert response.json()['parent_export_id']==saved['id']
            saved=response.json()
        else: assert response.status_code==409,response.text
    rows=client.get(path).json()['items']
    assert len(rows)==4 and all(row['status']=='failed' for row in rows)


def test_expired_attempt_removes_only_its_unpublished_files(client):
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.db.database import database_connection
    from app.core.config import get_data_dir
    from pathlib import Path
    path,source=successful_docx(client)
    saved=client.post(path,json=dict(source_kind='manuscript_export',source_id=source['id'],request_key='pdf')).json()
    execution=TaskExecutionStore();lease=execution.claim(saved['task_id'],1)
    directory=Path(get_data_dir())/'pdf_exports';directory.mkdir()
    name=saved['id']+'-'+lease.lease_owner+'.pdf'
    output=directory/name;part=directory/(name+'.part')
    output.write_bytes(b'%PDF-orphan');part.write_bytes(b'unfinished')
    unrelated=directory/'unrelated.pdf';unrelated.write_bytes(b'keep')
    with database_connection(write=True) as db:
        db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s",(saved['task_id'],))
    assert execution.recover_expired()==1
    assert not output.exists() and not part.exists()
    assert unrelated.read_bytes()==b'keep'


def test_recovery_waits_for_publication_transaction_before_deleting_attempt_files(client):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.db.database import database_connection
    from app.core.config import get_data_dir
    from pathlib import Path
    path,source=successful_docx(client)
    saved=client.post(path,json=dict(source_kind='manuscript_export',source_id=source['id'],request_key='pdf')).json()
    execution=TaskExecutionStore();lease=execution.claim(saved['task_id'],1)
    directory=Path(get_data_dir())/'pdf_exports';directory.mkdir()
    output=directory/(saved['id']+'-'+lease.lease_owner+'.pdf');output.write_bytes(b'%PDF-publishing')
    with database_connection(write=True) as db:
        db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s",(saved['task_id'],))
    started=Event()
    def recover():
        started.set()
        return execution.recover_expired()
    with ThreadPoolExecutor(1) as pool:
        with database_connection(write=True) as db:
            task=dict(db.execute('SELECT * FROM tasks WHERE id=%s FOR UPDATE',(saved['task_id'],)).fetchone())
            future=pool.submit(recover)
            assert started.wait(2)
            # Owner publication wins the task lock; the recovery snapshot can be stale.
            execution._finish(db,task,'succeeded',None)
        future.result(timeout=10)
    assert output.exists()


@pytest.mark.parametrize('reconnect_unavailable',[False,True])
def test_committed_pdf_survives_lost_commit_ack(client,monkeypatch,reconnect_unavailable):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from hashlib import sha256
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.core.exceptions import StorageError
    from app.db.database import database_connection
    from app.core.config import get_data_dir
    from pathlib import Path
    path,source=successful_docx(client)
    saved=client.post(path,json=dict(source_kind='manuscript_export',source_id=source['id'],request_key='pdf')).json()
    output=b'%PDF-1.7\ncommitted before acknowledgement lost'
    monkeypatch.setattr('app.domain.pdf_exports.execution.render_pdf',lambda raw:SimpleNamespace(content=output,manifest={'contract':'test-v1'}))
    original=TaskExecutionStore.connection
    injected=[]
    @contextmanager
    def lost_ack(self,write=False):
        if injected and reconnect_unavailable: raise StorageError('storage_unavailable','controlled reconnect failure')
        committed_success=False
        with original(self,write=write) as db:
            yield db
            if write and not injected:
                state=db.execute('SELECT status FROM tasks WHERE id=%s',(saved['task_id'],)).fetchone()
                committed_success=bool(state and state['status']=='succeeded')
        # The real connection above has already committed to the isolated PostgreSQL schema.
        if committed_success:
            injected.append(True)
            raise OSError('controlled commit acknowledgement loss')
    monkeypatch.setattr(TaskExecutionStore,'connection',lost_ack)
    result=run_task(saved['task_id'],1)
    assert injected==[True]
    with database_connection() as db:
        state=db.execute('SELECT t.status,e.metadata_json FROM tasks t JOIN pdf_exports e ON e.task_id=t.id WHERE t.id=%s',(saved['task_id'],)).fetchone()
    assert state['status']=='succeeded'
    metadata=state['metadata_json'];target=Path(get_data_dir())/'pdf_exports'/metadata['object_name']
    assert target.exists(),'A committed successful PDF must survive a lost COMMIT acknowledgement'
    assert sha256(target.read_bytes()).hexdigest()==metadata['sha256']==sha256(output).hexdigest()
    downloaded=client.get(path+'/'+saved['id']+'/download')
    assert downloaded.status_code==200 and downloaded.content==output
    if not reconnect_unavailable: assert result['status']=='succeeded'


def test_full_database_audit_routes_pdf_sources_through_dedicated_audit(client,monkeypatch):
    from types import SimpleNamespace
    from app.db.database import database_connection
    from app.maintenance.database_audit import audit_database
    from app.maintenance.dataset_source_audit import audit_dataset_sources
    from app.core.exceptions import StorageError
    path,source=successful_docx(client)
    def audit():
        with database_connection() as db: result=audit_database(db)
        assert result['ok'],result['schema_issues'] or [c for c in result['data_checks'] if c['invalid']]
        assert any(c['table']=='pdf_exports' and c['rows']>0 for c in result['data_checks'])
    succeeded=client.post(path,json=dict(source_kind='manuscript_export',source_id=source['id'],request_key='success')).json()
    audit()  # Nonempty queued PDF must not be treated as a dataset task.
    monkeypatch.setattr('app.domain.pdf_exports.execution.render_pdf',lambda raw:SimpleNamespace(content=b'%PDF-1.7\naudited',manifest={'contract':'test-v1'}))
    assert run_task(succeeded['task_id'],1)['status']=='succeeded'
    failed=client.post(path,json=dict(source_kind='manuscript_export',source_id=source['id'],request_key='failure')).json()
    def fail(raw): raise StorageError('pdf_renderer_busy','controlled failure',503)
    monkeypatch.setattr('app.domain.pdf_exports.execution.render_pdf',fail)
    assert run_task(failed['task_id'],1)['status']=='failed'
    retry=client.post(path+'/'+failed['id']+'/retry',json={'request_key':'retry'}).json()
    audit()  # Covers succeeded + failed parent + queued child.
    monkeypatch.setattr('app.domain.pdf_exports.execution.render_pdf',lambda raw:SimpleNamespace(content=b'%PDF-1.7\nretried audit',manifest={'contract':'test-v1'}))
    assert run_task(retry['task_id'],1)['status']=='succeeded'
    audit()
    # A different task type with the same invalid dataset-shaped source must
    # still be rejected by the dataset auditor; routing is task-type specific.
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET task_type='word_report' WHERE id=%s",(failed['task_id'],))
    with database_connection() as db:
        checks=audit_dataset_sources(db)
    check=next(c for c in checks if c['table']=='tasks' and c['column']=='dataset_source')
    assert check['rows']==1 and check['invalid']==1
