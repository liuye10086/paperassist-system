"""Immutable local layout exports; real PostgreSQL, controlled renderer boundary."""
import pytest
from tests.api.test_analysis import client  # noqa:F401
from tests.api.test_pdf_exports import successful_docx, fake_renderer  # noqa:F401
from app.domain.tasks.execution import run_task


@pytest.fixture(autouse=True)
def layout_renderer(monkeypatch):
    monkeypatch.setattr('app.domain.layout_exports.service.renderer_identity', lambda: {'contract':'test-v1'})
    monkeypatch.setattr('app.domain.layout_exports.execution.renderer_identity', lambda: {'contract':'test-v1'})


def prepared(client):
    pdf_path, source = successful_docx(client)
    from app.db.database import database_connection
    with database_connection() as db:
        root = db.execute('SELECT manuscript_id FROM manuscript_versions WHERE id=%s',(source['version_id'],)).fetchone()
    source['download_url'] = pdf_path.replace('/pdf-exports','/manuscripts/')+root['manuscript_id']+'/exports/'+source['id']+'/download'
    path = pdf_path.replace('/pdf-exports', '/layout-exports')
    catalog = client.get(path + '/sources/manuscript_export/' + source['id'] + '/catalog')
    assert catalog.status_code == 200, catalog.text
    return path, source, dict(source_kind='manuscript_export', source_id=source['id'],
        request_key='layout-one', layout={'source_sha256':catalog.json()['source_sha256']})


def test_layout_catalog_create_idempotency_and_permissions(client):
    path, source, request = prepared(client)
    saved = client.post(path, json=request)
    assert saved.status_code == 201, saved.text
    saved = saved.json()
    assert client.post(path, json=request).json() == saved
    assert client.post(path, json=dict(request, layout=dict(request['layout'], pagination={'mode':'continuous'}))).status_code == 409
    assert client.post(path, json=dict(request, request_key='missing', source_id='missing')).status_code == 404
    assert client.post(path, json=dict(request, request_key='bad-sha', layout={'source_sha256':'f'*64})).status_code == 409
    assert client.post(path, json=dict(request, request_key='no-sha', layout={})).status_code == 422
    assert client.get(path).json()['items'] == [saved]
    assert client.get(path+'/config').json()['real_model_calls'] is False
    assert source['id'] in [s['source_id'] for s in client.get(path+'/sources').json()['items']]
    assert client.get('/api/v1/tasks/'+saved['task_id']+'/workspace').status_code == 200
    summary=client.get(path.replace('/layout-exports','/summary')).json()
    assert summary['layout_exports']==[saved]
    usage=client.get('/api/v1/tasks/'+saved['task_id']+'/model-usage')
    assert usage.status_code==200 and usage.json()['items']==[] and usage.json()['total']==0
    from app.adapters.storage import ProjectStore
    from app.core.config import get_data_dir
    from app.domain.project_summary import read_project_summary
    assert read_project_summary(ProjectStore(get_data_dir()),saved['project_id']).layout_exports==[saved]
    from tests.integration.test_project_ownership import account_client
    with account_client('layout-other@example.test')[0] as other:
        assert other.get(path).status_code == 404
        assert other.get(path+'/sources/manuscript_export/'+source['id']+'/catalog').status_code == 404


def test_layout_publication_shared_pdf_and_original_bytes(client, monkeypatch):
    from types import SimpleNamespace
    path, source, request = prepared(client)
    original = client.get(source['download_url']).content
    calls = []
    def prepare(raw, options, *, language):
        calls.append((raw, options, language))
        return raw
    monkeypatch.setattr('app.domain.layout_exports.execution.prepare_layout_docx', prepare)
    saved = client.post(path, json=request).json()
    assert run_task(saved['task_id'], 1)['status'] == 'succeeded'
    run_task(saved['task_id'], 1)
    assert len(calls) == 1 and calls[0][0] == original
    done = client.get(path+'/'+saved['id']).json()
    assert client.get(done['download_url']).content == original
    assert client.get(source['download_url']).content == original
    pdf_path = path.replace('/layout-exports','/pdf-exports')
    pdf = client.post(pdf_path, json=dict(source_kind='layout_export',source_id=done['id'],request_key='pdf'))
    assert pdf.status_code == 201, pdf.text
    monkeypatch.setattr('app.domain.pdf_exports.execution.render_pdf', lambda raw:SimpleNamespace(content=b'%PDF-1.7\nlayout',manifest={'contract':'test-v1'}))
    assert run_task(pdf.json()['task_id'], 1)['status'] == 'succeeded'
    assert client.get(pdf_path+'/'+pdf.json()['id']+'/download').status_code == 200
    from app.db.database import database_connection
    from app.maintenance.database_audit import audit_database
    with database_connection() as db:
        audit = audit_database(db)
    assert audit['ok'], audit['schema_issues'] or [x for x in audit['data_checks'] if x['invalid']]


def test_layout_failure_retry_and_source_change(client, monkeypatch):
    from app.core.exceptions import StorageError
    path, source, request = prepared(client)
    def fail(*args, **kwargs): raise StorageError('layout_field_update_failed','private /secret/path',503)
    monkeypatch.setattr('app.domain.layout_exports.execution.prepare_layout_docx',fail)
    saved = client.post(path,json=request).json()
    assert run_task(saved['task_id'],1)['status']=='failed'
    failed = client.get(path+'/'+saved['id']).json()
    assert failed['error_code']=='layout_field_update_failed'
    assert '/secret' not in str(failed)
    retry = client.post(path+'/'+saved['id']+'/retry',json={'request_key':'retry'})
    assert retry.status_code==201,retry.text
    assert retry.json()['id']!=saved['id']
    assert retry.json()['layout']==failed['layout']
    assert client.get(source['download_url']).status_code==200
    from pathlib import Path
    from app.core.config import get_data_dir
    (Path(get_data_dir())/'manuscript_exports'/(source['id']+'.docx')).write_bytes(b'changed')
    assert run_task(retry.json()['task_id'],1)['status']=='failed'
    assert client.get(path+'/'+retry.json()['id']).json()['download_url'] is None


@pytest.mark.parametrize('reconnect_unavailable',[False,True])
def test_layout_committed_file_survives_lost_commit_ack(client,monkeypatch,reconnect_unavailable):
    from contextlib import contextmanager
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.core.exceptions import StorageError
    from app.db.database import database_connection
    path,source,request=prepared(client)
    original=client.get(source['download_url']).content
    saved=client.post(path,json=request).json()
    monkeypatch.setattr('app.domain.layout_exports.execution.prepare_layout_docx',lambda raw,options,**kw:raw)
    connection=TaskExecutionStore.connection
    injected=[]
    @contextmanager
    def lost_ack(self,write=False):
        if injected and reconnect_unavailable: raise StorageError('storage_unavailable','controlled reconnect failure')
        success=False
        with connection(self,write=write) as db:
            yield db
            if write and not injected:
                state=db.execute('SELECT status FROM tasks WHERE id=%s',(saved['task_id'],)).fetchone()
                success=bool(state and state['status']=='succeeded')
        if success:
            injected.append(True)
            raise OSError('controlled lost acknowledgement after real commit')
    monkeypatch.setattr(TaskExecutionStore,'connection',lost_ack)
    result=run_task(saved['task_id'],1)
    assert injected==[True]
    with database_connection() as db:
        assert db.execute('SELECT status FROM tasks WHERE id=%s',(saved['task_id'],)).fetchone()['status']=='succeeded'
    assert client.get(path+'/'+saved['id']+'/download').content==original
    if not reconnect_unavailable: assert result['status']=='succeeded'


def test_layout_lease_loss_recovery_and_bounded_retry(client,monkeypatch):
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.db.database import database_connection
    from app.core.config import get_data_dir
    from pathlib import Path
    from app.core.exceptions import StorageError
    path,_,request=prepared(client)
    saved=client.post(path,json=request).json()
    execution=TaskExecutionStore()
    lease=execution.claim(saved['task_id'],1)
    assert execution.recover_expired()==0
    assert execution.claim(saved['task_id'],1) is None
    directory=Path(get_data_dir())/'layout_exports';directory.mkdir()
    output=directory/(saved['id']+'-'+lease.lease_owner+'.docx')
    output.write_bytes(b'PK orphan')
    unrelated=directory/'unrelated.docx';unrelated.write_bytes(b'keep')
    with database_connection(write=True) as db:
        db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s",(saved['task_id'],))
    assert execution.recover_expired()==1
    assert not output.exists() and unrelated.read_bytes()==b'keep'
    assert not execution.heartbeat(lease)
    def fail(*args,**kwargs): raise StorageError('pdf_renderer_busy','private details',503)
    monkeypatch.setattr('app.domain.layout_exports.execution.prepare_layout_docx',fail)
    with database_connection() as db:
        revision=db.execute('SELECT revision FROM tasks WHERE id=%s',(saved['task_id'],)).fetchone()['revision']
    for index in range(4):
        assert run_task(saved['task_id'],revision)['status']=='failed'
        failed=client.get(path+'/'+saved['id']).json()
        assert failed['can_retry']==(index<3)
        generic=client.get('/api/v1/tasks/'+saved['task_id']).json()
        assert client.post('/api/v1/tasks/'+saved['task_id']+'/retry',json={'expected_revision':generic['revision']}).status_code==409
        retry=client.post(path+'/'+saved['id']+'/retry',json={'request_key':f'retry-{index}'})
        if index<3:
            assert retry.status_code==201,retry.text
            saved=retry.json();revision=1
        else: assert retry.status_code==409
    assert len(client.get(path).json()['items'])==4


def test_historical_layout_and_pdf_download_survive_new_renderer_lock(client,monkeypatch):
    from types import SimpleNamespace
    path,_,request=prepared(client)
    monkeypatch.setattr('app.domain.layout_exports.execution.prepare_layout_docx',lambda raw,options,**kw:raw)
    saved=client.post(path,json=request).json()
    assert run_task(saved['task_id'],1)['status']=='succeeded'
    pdf_path=path.replace('/layout-exports','/pdf-exports')
    pdf=client.post(pdf_path,json=dict(source_kind='layout_export',source_id=saved['id'],request_key='pdf')).json()
    monkeypatch.setattr('app.domain.pdf_exports.execution.render_pdf',lambda raw:SimpleNamespace(content=b'%PDF-historical',manifest={'contract':'test-v1'}))
    assert run_task(pdf['task_id'],1)['status']=='succeeded'
    monkeypatch.setattr('app.domain.layout_exports.service.renderer_identity',lambda:{'contract':'new-lock'})
    monkeypatch.setattr('app.domain.pdf_exports.service.renderer_identity',lambda:{'contract':'new-lock'})
    assert client.get(path+'/'+saved['id']+'/download').status_code==200
    assert client.get(pdf_path+'/'+pdf['id']+'/download').content==b'%PDF-historical'


def test_layout_queued_input_never_follows_new_manuscript_revision(client,monkeypatch):
    from app.db.database import database_connection
    from tests.api.test_manuscripts import body
    from tests.api.test_literature_evidence import post
    path,source,request=prepared(client)
    original=client.get(source['download_url']).content
    saved=client.post(path,json=request).json()
    with database_connection() as db:
        manuscript=db.execute('SELECT manuscript_id FROM manuscript_versions WHERE id=%s',(source['version_id'],)).fetchone()['manuscript_id']
    root=path.replace('/layout-exports','/manuscripts/')+manuscript
    newer=post(client,root+'/versions',body(expected_revision=1,title='Second independent revision'),'newer')
    assert newer.status_code==201,newer.text
    task=newer.json()['versions'][0]['task_id'];assert run_task(task,1)['status']=='succeeded'
    second=post(client,root+'/versions/2/exports',{},'second-export').json()
    assert run_task(second['task_id'],1)['status']=='succeeded'
    seen=[]
    def prepare(raw,options,**kwargs): seen.append(raw);return raw
    monkeypatch.setattr('app.domain.layout_exports.execution.prepare_layout_docx',prepare)
    assert run_task(saved['task_id'],1)['status']=='succeeded'
    assert seen==[original]
    assert client.get(path+'/'+saved['id']).json()['source_id']==source['id']


def test_layout_audit_rejects_rehashed_retry_configuration_drift(client,monkeypatch):
    from app.core.exceptions import StorageError
    from app.db.database import migration_connection,database_connection
    from psycopg.types.json import Jsonb
    from app.domain.literature.service import digest
    from app.maintenance.layout_export_audit import audit_layout_exports
    path,_,request=prepared(client)
    saved=client.post(path,json=request).json()
    def fail(*args,**kw): raise StorageError('pdf_renderer_busy','controlled failure',503)
    monkeypatch.setattr('app.domain.layout_exports.execution.prepare_layout_docx',fail)
    run_task(saved['task_id'],1)
    child=client.post(path+'/'+saved['id']+'/retry',json={'request_key':'child'}).json()
    with migration_connection(write=True) as db:
        row=db.execute('SELECT * FROM layout_exports WHERE id=%s',(child['id'],)).fetchone()
        snapshot=row['input_json'];snapshot['layout']['pagination']={'mode':'continuous'}
        request_digest=digest(dict(source_kind=row['source_kind'],source_id=row['source_id'],parent_export_id=row['parent_export_id'],layout=snapshot['layout']))
        db.execute('UPDATE layout_exports SET input_json=%s,input_sha256=%s,request_digest=%s WHERE id=%s',(Jsonb(snapshot),digest(snapshot),request_digest,row['id']))
        task_snapshot=dict(export_id=row['id'],**snapshot)
        db.execute('UPDATE tasks SET input_snapshot=%s,input_digest=%s WHERE id=%s',(Jsonb(task_snapshot),digest(task_snapshot),row['task_id']))
    with database_connection() as db:
        assert any(c['invalid'] for c in audit_layout_exports(db))
    assert client.get(path+'/'+child['id']).status_code==409


@pytest.mark.parametrize('failure',['lease_lost','transaction_rollback'])
def test_layout_failed_publication_never_exposes_candidate(client,monkeypatch,failure):
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.db.database import database_connection
    from app.core.config import get_data_dir
    from pathlib import Path
    path,source,request=prepared(client)
    original=client.get(source['download_url']).content
    saved=client.post(path,json=request).json()
    def prepare(raw,options,**kwargs):
        if failure=='lease_lost':
            with database_connection(write=True) as db:
                db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s",(saved['task_id'],))
            TaskExecutionStore().recover_expired()
        return raw
    monkeypatch.setattr('app.domain.layout_exports.execution.prepare_layout_docx',prepare)
    finish=TaskExecutionStore._finish
    def fail_finish(self,db,task,status,code):
        if failure=='transaction_rollback' and status=='succeeded' and task['task_type']=='layout_docx':
            raise RuntimeError('private controlled rollback')
        return finish(self,db,task,status,code)
    monkeypatch.setattr(TaskExecutionStore,'_finish',fail_finish)
    run_task(saved['task_id'],1)
    state=client.get(path+'/'+saved['id']).json()
    assert state['status']==('queued' if failure=='lease_lost' else 'failed')
    assert state['download_url'] is None
    retained=list((Path(get_data_dir())/'layout_exports').glob('*'))
    if failure=='lease_lost':
        assert not retained
    else:
        assert len(retained)==1 and retained[0].read_bytes()==original
        assert state['error_code']=='storage_accounting_unknown' and state['recovery_mode']=='local_candidate'
        with database_connection() as db:
            assert db.execute("SELECT state FROM storage_reservations WHERE task_id=%s AND kind='layout_docx'",(saved['task_id'],)).fetchone()['state']=='unknown'
    assert client.get(source['download_url']).content==original


def failed_layout(client,monkeypatch):
    from app.core.exceptions import StorageError
    path,_,request=prepared(client)
    def fail(*args,**kwargs): raise StorageError('pdf_renderer_busy','controlled failure',503)
    monkeypatch.setattr('app.domain.layout_exports.execution.prepare_layout_docx',fail)
    saved=client.post(path,json=request).json()
    assert run_task(saved['task_id'],1)['status']=='failed'
    return path,saved,request


def test_retry_old_parent_cannot_fork_before_or_after_child_success(client,monkeypatch):
    path,root,_=failed_layout(client,monkeypatch)
    endpoint=path+'/'+root['id']+'/retry'
    child=client.post(endpoint,json={'request_key':'child'})
    assert child.status_code==201,child.text
    assert client.post(endpoint,json={'request_key':'sibling-queued'}).status_code==409
    assert client.get(path+'/'+root['id']).json()['can_retry'] is False
    monkeypatch.setattr('app.domain.layout_exports.execution.prepare_layout_docx',lambda raw,options,**kw:raw)
    assert run_task(child.json()['task_id'],1)['status']=='succeeded'
    assert client.post(endpoint,json={'request_key':'sibling-after-success'}).status_code==409
    replay=client.post(endpoint,json={'request_key':'child'})
    assert replay.status_code==200 and replay.json()['id']==child.json()['id']
    assert client.get(path+'/'+root['id']).json()['can_retry'] is False
    assert len(client.get(path).json()['items'])==2


def test_retry_limit_keeps_original_key_replay_and_all_old_parents_closed(client,monkeypatch):
    path,root,_=failed_layout(client,monkeypatch)
    current=root;replays=[]
    for index in range(3):
        endpoint=path+'/'+current['id']+'/retry';key=f'chain-{index}'
        response=client.post(endpoint,json={'request_key':key})
        assert response.status_code==201,response.text
        current=response.json();replays.append((endpoint,key,current['id']))
        assert run_task(current['task_id'],1)['status']=='failed'
    rows=client.get(path).json()['items']
    assert len(rows)==4
    assert all(row['can_retry'] is False for row in rows)
    for row in rows:
        assert client.post(path+'/'+row['id']+'/retry',json={'request_key':'overflow-'+row['id']}).status_code==409
    for endpoint,key,identity in replays:
        replay=client.post(endpoint,json={'request_key':key})
        assert replay.status_code==200 and replay.json()['id']==identity
    assert len(client.get(path).json()['items'])==4


def test_concurrent_retry_keys_use_one_remaining_slot(client,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.domain.layout_exports.service import LayoutExportService
    from app.domain.report_collections.service import scoped_store
    from app.db.database import database_connection
    from app.core.exceptions import StorageError
    path,root,_=failed_layout(client,monkeypatch)
    leaf=root
    for index in range(2):
        leaf=client.post(path+'/'+leaf['id']+'/retry',json={'request_key':f'prior-{index}'}).json()
        assert run_task(leaf['task_id'],1)['status']=='failed'
    with database_connection() as db:
        owner=db.execute('SELECT owner_id FROM projects WHERE id=%s',(root['project_id'],)).fetchone()['owner_id']
        config=db.config
    barrier=Barrier(6)
    def retry(index):
        service=LayoutExportService(scoped_store(owner,config))
        barrier.wait()
        try: return service.retry(root['project_id'],leaf['id'],f'concurrent-{index}')[1]
        except StorageError as exc: return exc.status
    with ThreadPoolExecutor(6) as pool:
        statuses=list(pool.map(retry,range(6)))
    assert statuses.count(201)==1 and statuses.count(409)==5,statuses
    assert len(client.get(path).json()['items'])==4
    assert all(not row['can_retry'] for row in client.get(path).json()['items'])


def test_retry_audit_rejects_structurally_valid_sibling_rows(client,monkeypatch):
    from app.db.database import migration_connection,database_connection
    from app.domain.literature.service import digest
    from app.maintenance.layout_export_audit import audit_layout_exports
    path,root,request=failed_layout(client,monkeypatch)
    assert client.post(path+'/'+root['id']+'/retry',json={'request_key':'first-child'}).status_code==201
    sibling=client.post(path,json=dict(request,request_key='independent-root')).json()
    # Corrupt only application lineage: all existing SQL FKs/hash shapes remain valid.
    with migration_connection(write=True) as db:
        row=db.execute('SELECT * FROM layout_exports WHERE id=%s',(sibling['id'],)).fetchone()
        request_hash=digest(dict(source_kind=row['source_kind'],source_id=row['source_id'],
            parent_export_id=root['id'],layout=row['input_json']['layout']))
        db.execute('UPDATE layout_exports SET parent_export_id=%s,request_digest=%s WHERE id=%s',
            (root['id'],request_hash,sibling['id']))
    with database_connection() as db:
        assert any(check['invalid'] for check in audit_layout_exports(db))
    assert client.get(path+'/'+root['id']).status_code==409
