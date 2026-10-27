"""Only creation-time registered synthetic fixtures may lose primary bytes."""
from importlib.util import find_spec
from pathlib import Path
import os
import json
from datetime import datetime,timedelta,timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from app.adapters.storage import ProjectStore
from app.core.config import get_data_dir
from app.core.exceptions import StorageError
from app.main import app
from tests.api.test_admin_operations import accounts, login


@pytest.fixture(autouse=True)
def explicit_synthetic_retention_clock(monkeypatch):
    from app.domain.storage_governance import deletion
    # New files really are new. Only this offline test's policy clock advances;
    # operator APIs/builders never accept a backdated timestamp.
    monkeypatch.setattr(deletion,'current_utc',lambda:datetime.now(timezone.utc)+timedelta(hours=25))


def components():
    assert find_spec('app.domain.storage_governance.deletion') is not None, 'Controlled deletion is not implemented'
    from app.domain.storage_governance.deletion import DeletionService, create_disposable_fixture
    return DeletionService, create_disposable_fixture


def fixture(accounts, tmp_path, *, originals=True):
    service, build = components()
    store = ProjectStore(get_data_dir(), owner_id=accounts[2]['id'])
    evidence=Path(os.environ.get('PAPERASSIST_DELETION_TEST_EVIDENCE_DIR',str(tmp_path/'preserved-evidence')))
    created = build(store, evidence_directory=evidence,
                    originals=[('original.xlsx', b'new synthetic source')] if originals else [],
                    temporary=[b'new disposable one', b'new disposable two'])
    from app.domain.storage_governance.deletion import current_utc
    Path(created['receipt_path']).with_name('synthetic-retention-clock.json').write_text(json.dumps({
        'simulation_only':True,'elapsed_real_hours':0,'assessment_clock':current_utc().isoformat(),
        'explanation':'New disposable synthetic input; only test policy clock advances 25h, no actual 24h elapsed.'}),encoding='utf-8')
    return store, created, service(store)


def preview(service, created, **kwargs):
    return service.preview(created['project_id'], scope_kind=kwargs.pop('scope_kind', 'project'),
                           reason='Explicit disposable synthetic acceptance', **kwargs)


def execute(service, plan, key='fixture-delete'):
    return service.execute(plan['project_id'], plan['id'],
                           confirmed_manifest_sha256=plan['manifest_sha256'],
                           confirmation='delete_registered_synthetic_objects', key=key)


def test_registered_partial_failure_retries_only_failed_and_preserves_shared_download(accounts, tmp_path, monkeypatch):
    from app.domain.storage_governance.service import reserve, settle, inventory
    store, created, service = fixture(accounts, tmp_path)
    shared = created['files'][0]
    other = store.create_project('retained sibling', 'synthetic', 'sci')['id']
    with store.connection(write=True) as db:
        row = reserve(db, store.directory, other, 'shared', store.directory/shared['object_key'], shared['size_bytes'])
        settle(db, store.directory, row['id'])
    plan = preview(service, created)
    assert any(i['action']=='retain' and 'shared_reference' in i['reason_codes'] for i in plan['items'])
    failing_key = created['temporary'][1]['object_key']
    calls = []
    original_unlink = Path.unlink
    def fail_once(path, *args, **kwargs):
        calls.append(path.as_posix())
        if path == store.directory/failing_key:
            raise OSError('isolated injected IO failure')
        return original_unlink(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'unlink', fail_once)
        result = execute(service, plan)
    assert result['state']=='partial_failed'
    assert sorted(i['state'] for i in result['items'])==['deleted','failed','retained']
    assert store.original(store.file(created['project_id'], shared['id']))==b'new synthetic source'
    before_calls = len(calls)
    def observe(path, *args, **kwargs):
        calls.append(path.as_posix())
        return original_unlink(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'unlink', observe)
        done = service.retry(created['project_id'], plan['id'], confirmed_manifest_sha256=plan['manifest_sha256'],
                             confirmation='delete_registered_synthetic_objects', key='fixture-delete')
        assert execute(service, plan)==done
    assert calls[before_calls:]==[(store.directory/failing_key).as_posix()]
    assert done['state']=='partial_retained' and done['deleted_object_count']==2
    assert done['backup_status']=='retained_indefinitely' and done['provider_status']=='not_executed'
    assert Path(created['receipt_path']).is_file()
    assert len(list(Path(created['receipt_path']).parent.glob('*.source')))==3
    with store.connection(write=True) as db:
        inventory(db, store.directory)
        assert db.execute("SELECT count(*) AS n FROM storage_objects WHERE state='deleted'").fetchone()['n']==2
        assert db.execute('SELECT count(*) AS n FROM storage_reservations WHERE project_id=%s',(created['project_id'],)).fetchone()['n']==3


def test_preview_changes_and_unsettled_work_block_execution(accounts, tmp_path):
    from app.domain.storage_governance.service import reserve, settle
    store, created, service = fixture(accounts, tmp_path, originals=False)
    plan = preview(service, created)
    other = store.create_project('second retained', 'synthetic', 'sci')['id']
    obj = created['temporary'][0]
    with store.connection(write=True) as db:
        row = reserve(db,store.directory,other,'new-ref',store.directory/obj['object_key'],obj['size_bytes'])
        settle(db,store.directory,row['id'])
    with pytest.raises(StorageError) as error: execute(service, plan)
    assert error.value.code=='storage_deletion_plan_changed'
    with store.connection(write=True) as db:
        reserve(db,store.directory,created['project_id'],'unknown-result',store.directory/'never-written',2)
    blocked = preview(service, created)
    assert 'storage_work_unresolved' in blocked['blockers']
    with pytest.raises(StorageError) as error: execute(service, blocked)
    assert error.value.code=='storage_deletion_blocked'
    assert all((store.directory/o['object_key']).exists() for o in created['temporary'])


def test_atomic_barrier_rejects_tasks_sql_references_and_late_publication(accounts, tmp_path):
    from app.domain.storage_governance.service import reserve
    from app.adapters.task_store import TaskStore
    from datetime import datetime, timezone
    store, created, service = fixture(accounts, tmp_path, originals=False)
    plan = preview(service, created)
    execute(service, plan)
    pid=created['project_id']; now=datetime.now(timezone.utc)
    task=dict(id=str(uuid4()),project_id=pid,user_id=accounts[2]['id'],task_type='boxplot',idempotency_key='late',
              input_digest='a'*64,input_snapshot={},workflow_version='test',status='queued',phase='compute',
              revision=1,current_attempt=0,reason_code=None,created_at=now,updated_at=now)
    with pytest.raises(StorageError) as error:
        with store.connection(write=True) as db: TaskStore.insert_task(db,task)
    assert error.value.code=='storage_deletion_pending'
    with pytest.raises(StorageError) as error:
        with store.connection(write=True) as db:
            db.execute("INSERT INTO manuscripts(id,project_id,user_id,title,created_at,updated_at) VALUES(%s,%s,%s,'late',%s,%s)",
                       (str(uuid4()),pid,accounts[2]['id'],now,now))
    assert error.value.code=='storage_deletion_pending'
    with pytest.raises(StorageError) as error:
        with store.connection(write=True) as db: reserve(db,store.directory,pid,'late',store.directory/'late.bin',1)
    assert error.value.code=='storage_deletion_pending'
    assert not (store.directory/'late.bin').exists()


def test_unregistered_environment_retains_and_registered_identity_change_blocks(accounts, tmp_path):
    service_type, _ = components()
    store=ProjectStore(get_data_dir(),owner_id=accounts[2]['id'])
    pid=store.create_project('retained by default','synthetic','sci')['id']
    record=store.save_file(pid,'retained.xlsx',b'retained content',None,None)
    service=service_type(store)
    plan=service.preview(pid,scope_kind='project',reason='Preview only unregistered scope')
    assert plan['retention_policy']=='retain_all'
    with pytest.raises(StorageError) as error: execute(service,plan)
    assert error.value.code=='storage_deletion_not_authorized'
    assert store.original(store.file(pid,record['id']))==b'retained content'
    store,created,service=fixture(accounts,tmp_path,originals=False)
    plan=preview(service,created)
    target=store.directory/created['temporary'][0]['object_key']
    target.write_bytes(b'changed fixture bytes')
    with pytest.raises(StorageError): execute(service,plan)
    assert target.read_bytes()==b'changed fixture bytes'


def test_http_owner_preview_execute_and_file_scope_preserves_sibling(accounts,tmp_path):
    store,created,service=fixture(accounts,tmp_path)
    shared=created['files'][0]
    with TestClient(app) as client:
        login(client,accounts[2])
        base=f"/api/v1/projects/{created['project_id']}/storage-deletions"
        response=client.post(base+'/preview',json={'scope_kind':'file','file_id':shared['id'],'reason':'Synthetic file deletion'})
        assert response.status_code==200,response.text
        plan=response.json()
        assert len(plan['items'])==1
        response=client.post(base+'/'+plan['id']+'/execute',headers={'Idempotency-Key':'http-file'},
                             json={'confirmed_manifest_sha256':plan['manifest_sha256'],'confirmation':'delete_registered_synthetic_objects'})
        assert response.status_code==200,response.text
        assert response.json()['deleted_object_count']==1
        assert all((store.directory/o['object_key']).exists() for o in created['temporary'])
        assert 'object_key' not in response.text and str(store.directory) not in response.text
        new=store.save_file(created['project_id'],'unrelated.xlsx',b'unrelated new source',None,None)
        assert store.original(store.file(created['project_id'],new['id']))==b'unrelated new source'
        login(client,accounts[0])
        assert client.get(base+'/'+plan['id']).status_code==404


def insert_task(store,pid,owner,status='failed'):
    from datetime import datetime,timezone
    from app.adapters.task_store import TaskStore
    now=datetime.now(timezone.utc)
    task=dict(id=str(uuid4()),project_id=pid,user_id=owner,task_type='literature_search',idempotency_key=str(uuid4()),
              input_digest='a'*64,input_snapshot={},workflow_version='test',status=status,phase='compute',
              revision=1,current_attempt=1,reason_code=None,created_at=now,updated_at=now)
    with store.connection(write=True) as db:TaskStore.insert_task(db,task)
    return task


def test_active_unknown_budget_block_then_preserve_fee_and_idempotency_evidence(accounts,tmp_path):
    from tests.api.test_admin_operations import seed_call
    store,created,service=fixture(accounts,tmp_path,originals=False)
    pid=created['project_id'];task=insert_task(store,pid,accounts[2]['id'],'queued')
    call=seed_call(accounts[2]['id'],pid,task['id'],usage={'input_tokens':1,'output_tokens':1},cost=100)
    budget=str(uuid4());now=task['created_at']
    with store.connection(write=True) as db:
        db.execute("UPDATE model_calls SET status='submission_unknown',usage_status='pending' WHERE id=%s",(call,))
        db.execute("""INSERT INTO model_budgets(id,user_id,scope_type,scope_key,project_id,limit_micro_usd,revision,created_at,updated_at)
            VALUES(%s,%s,'project',%s,%s,10000,1,%s,%s)""",(budget,accounts[2]['id'],pid,pid,now,now))
        db.execute("INSERT INTO budget_reservations(call_id,budget_id,status,reserved_micro_usd,accounted_micro_usd,updated_at) VALUES(%s,%s,'held',100,0,%s)",(call,budget,now))
    blocked=preview(service,created)
    assert {'active_tasks','external_work_unresolved','budget_reservations_held'}<=set(blocked['blockers'])
    with pytest.raises(StorageError) as error:execute(service,blocked)
    assert error.value.code=='storage_deletion_blocked'
    with store.connection(write=True) as db:
        db.execute("UPDATE tasks SET status='failed' WHERE id=%s",(task['id'],))
        db.execute("UPDATE model_calls SET status='completed',usage_status='estimated' WHERE id=%s",(call,))
        db.execute("UPDATE budget_reservations SET status='settled',reserved_micro_usd=0,accounted_micro_usd=100 WHERE call_id=%s",(call,))
        before=[dict(db.execute('SELECT * FROM model_calls WHERE id=%s',(call,)).fetchone()),
                list(db.execute('SELECT * FROM usage_events WHERE call_id=%s ORDER BY id',(call,))),
                dict(db.execute('SELECT * FROM budget_reservations WHERE call_id=%s',(call,)).fetchone())]
    done=execute(service,preview(service,created))
    assert done['deleted_object_count']==2
    with store.connection(write=True) as db:
        assert before==[dict(db.execute('SELECT * FROM model_calls WHERE id=%s',(call,)).fetchone()),
                        list(db.execute('SELECT * FROM usage_events WHERE call_id=%s ORDER BY id',(call,))),
                        dict(db.execute('SELECT * FROM budget_reservations WHERE call_id=%s',(call,)).fetchone())]
        assert db.execute('SELECT idempotency_key FROM tasks WHERE id=%s',(task['id'],)).fetchone()['idempotency_key']==task['idempotency_key']
        # A late accounting-only observation remains writable after disposal.
        db.execute('UPDATE model_calls SET reconciliation_revision=reconciliation_revision+1 WHERE id=%s',(call,))


def test_concurrent_reference_and_requeue_cannot_cross_armed_barrier(accounts,tmp_path,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from app.adapters.task_store import TaskStore
    from app.domain.storage_governance.service import reserve,settle
    store,created,service=fixture(accounts,tmp_path,originals=False)
    pid=created['project_id'];task=insert_task(store,pid,accounts[2]['id'])
    other=store.create_project('other retained','synthetic','sci')['id']
    plan=preview(service,created);armed=Event();started=Event();event=service._event
    def pause(db,operation,state,reason,*args):
        event(db,operation,state,reason,*args)
        if state=='running':
            armed.set();assert started.wait(5)
    monkeypatch.setattr(service,'_event',pause)
    def racing_reference():
        assert armed.wait(5);started.set()
        try:
            with store.connection(write=True) as db:
                obj=created['temporary'][0]
                db.execute('INSERT INTO storage_references(object_id,project_id,owner_id,kind) VALUES(%s,%s,%s,%s)',
                           (obj['object_id'],other,accounts[2]['id'],'late_shared'))
        except StorageError as exc:return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        writer=pool.submit(racing_reference)
        done=execute(service,plan)
        assert writer.result(timeout=5)=='storage_deletion_pending'
    assert done['deleted_object_count']==2
    with pytest.raises(StorageError) as error:
        with store.connection(write=True) as db:TaskStore.enqueue(db,task)
    assert error.value.code=='storage_deletion_pending'
    with store.connection() as db:
        assert db.execute('SELECT count(*) AS n FROM task_outbox WHERE task_id=%s',(task['id'],)).fetchone()['n']==0


def test_lost_database_ack_after_unlink_resumes_durable_intent_without_second_unlink(accounts,tmp_path,monkeypatch):
    store,created,service=fixture(accounts,tmp_path,originals=False)
    plan=preview(service,created);event=service._event;broken=False
    def fail(db,operation,state,reason,*args):
        nonlocal broken
        if state=='deleted' and not broken:
            broken=True
            raise StorageError('storage_unavailable','Synthetic commit rollback after unlink',503)
        return event(db,operation,state,reason,*args)
    with monkeypatch.context() as patch:
        patch.setattr(service,'_event',fail)
        failed=execute(service,plan)
    assert failed['state']=='partial_failed'
    def no_more_unlink(path,*args,**kwargs):raise AssertionError('Absent primary must not be unlinked twice')
    with monkeypatch.context() as patch:
        patch.setattr(Path,'unlink',no_more_unlink)
        done=service.retry(created['project_id'],plan['id'],confirmed_manifest_sha256=plan['manifest_sha256'],
                           confirmation='delete_registered_synthetic_objects',key='fixture-delete')
    assert done['state']=='partial_retained' and done['deleted_object_count']==2


def test_registered_temporary_scope_requires_full_retention_period(accounts,tmp_path,monkeypatch):
    from app.domain.storage_governance import deletion
    monkeypatch.setattr(deletion,'current_utc',lambda:datetime.now(timezone.utc))
    store,created,service=fixture(accounts,tmp_path,originals=False)
    plan=preview(service,created,scope_kind='temporary')
    assert 'temporary_retention_period' in plan['blockers']
    with pytest.raises(StorageError) as error:execute(service,plan)
    assert error.value.code=='storage_deletion_blocked'
    project_plan=preview(service,created)
    assert all(i['action']=='retain' and 'temporary_retention_period' in i['reason_codes'] for i in project_plan['items'])
    assert execute(service,project_plan)['deleted_object_count']==0
    assert all((store.directory/o['object_key']).exists() for o in created['temporary'])


def test_file_plan_includes_retained_document_graph_and_download_dependencies(accounts,tmp_path):
    from tests.helpers.document_samples import document_bytes
    from app.adapters.docx_parser import parse_docx
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    service_type,build=components()
    store=ProjectStore(get_data_dir(),owner_id=accounts[2]['id'])
    source=document_bytes()
    created=build(store,evidence_directory=Path(os.environ['PAPERASSIST_DELETION_TEST_EVIDENCE_DIR']),
                  originals=[('retained.docx',source)])
    from app.domain.documents.service import document_snapshot
    from app.adapters.task_store import TaskStore
    pid=created['project_id'];fid=created['files'][0]['id'];parse_id=str(uuid4());now=datetime.now(timezone.utc)
    with store.connection(write=True) as db:
        file=dict(db.execute('SELECT * FROM files WHERE id=%s',(fid,)).fetchone())
        snapshot=document_snapshot(pid,{k:file[k] for k in ('id','filename','file_type','size_bytes','sha256','storage_backend','object_key')},parse_id,1)
        task=dict(id=str(uuid4()),project_id=pid,user_id=accounts[2]['id'],task_type='parse_file',idempotency_key='fixture-first-parse',
                  input_digest=file['sha256'],input_snapshot=snapshot,workflow_version='docx_document_v1',status='queued',phase='parse',
                  revision=1,current_attempt=0,reason_code=None,created_at=now,updated_at=now)
        TaskStore.insert_task(db,task)
        db.execute('''INSERT INTO file_parse_results(id,file_id,task_id,version,source_sha256,parser_version,settings_json,created_at)
            VALUES(%s,%s,%s,1,%s,%s,%s,%s)''',(parse_id,fid,task['id'],file['sha256'],snapshot['parser_version'],Jsonb(snapshot['settings']),now))
        TaskStore.append_event(db,task,'created');TaskStore.enqueue(db,task)
    with TestClient(app) as client:
        login(client,accounts[2]);base=f"/api/v1/projects/{created['project_id']}/files/{created['files'][0]['id']}"
        task=run_parse_file_task(task['id'],1,parser=parse_docx)
        assert task['status']=='succeeded',task
        version=client.get(base+'/document-versions').json()['items'][0]
        before=client.get(version['download_url']).content
        service=service_type(store);plan=preview(service,created,scope_kind='file',file_id=created['files'][0]['id'])
        assert len(plan['items'])==4 # original + parsed JSON + two embedded image bytes
        assert all(i['action']=='retain' for i in plan['items'])
        done=execute(service,plan)
        assert done['deleted_object_count']==0
        assert client.get(version['download_url']).content==before
        assert client.get(base+'/download').content==source


def test_deleted_file_does_not_block_unrelated_factual_manuscript_admission_and_execution(accounts,tmp_path,monkeypatch):
    from io import BytesIO
    from openpyxl import Workbook
    from tests.api.test_manuscripts import body
    from app.domain.manuscripts.execution import run_manuscript_task
    from app.domain.storage_governance.guards import require_task_open
    from app.domain.storage_governance.service import require_publication_allowed
    store,created,service=fixture(accounts,tmp_path)
    removed=created['files'][0]
    plan=preview(service,created,scope_kind='file',file_id=removed['id'])
    assert execute(service,plan)['deleted_object_count']==1
    book=Workbook();book.active.append(['Synthetic retained B',1]);stream=BytesIO();book.save(stream)
    retained=store.save_file(created['project_id'],'retained-b.xlsx',stream.getvalue(),None,None)
    with TestClient(app) as client:
        login(client,accounts[2]);path=f"/api/v1/projects/{created['project_id']}/manuscripts"
        selected=dict(kind='original',id=retained['id'],file_id=retained['id'],role='methods')
        response=client.post(path,headers={'Idempotency-Key':'retained-b-draft'},json=body(sources=[selected]))
        assert response.status_code==201,response.text
        manuscript=response.json();version=manuscript['versions'][0]
        task_id=version['task_id']
        with store.connection(write=True) as db:
            task=dict(db.execute('SELECT * FROM tasks WHERE id=%s',(task_id,)).fetchone())
            assert 'file_id' not in task['input_snapshot']
            require_task_open(db,task)
            require_publication_allowed(db,created['project_id'],'r1-publication-check',task_id=task_id)
        result=run_manuscript_task(task_id,1)
        assert result['status']=='succeeded',result
        assert client.get(path+'/'+manuscript['id']).json()['versions'][0]['status']=='published'
        rejected=client.post(path,headers={'Idempotency-Key':'disposed-a-draft'},json=body(sources=[{
            'kind':'original','id':removed['id'],'file_id':removed['id'],'role':'methods'}]))
        assert rejected.status_code==410,rejected.text
        assert rejected.json()['detail']['code']=='file_missing'
        assert store.original(store.file(created['project_id'],retained['id']))==stream.getvalue()
        with store.connection() as db:
            assert db.execute('SELECT count(*) AS n FROM manuscripts WHERE project_id=%s',(created['project_id'],)).fetchone()['n']==1
            unknown={**task,'input_snapshot':{**task['input_snapshot'],'manuscript_version_id':str(uuid4())}}
            with pytest.raises(StorageError) as error:require_task_open(db,unknown)
            assert error.value.code=='storage_deletion_scope_unknown'
            # The existing resolver deliberately returns the original snapshot
            # for PDF families it does not expand. That fallback is not proof.
            from app.domain.file_lifecycle import manuscript_task_sources
            with monkeypatch.context() as patch:
                patch.setattr(manuscript_task_sources,'task_material',lambda db,task,user,project:task['input_snapshot'])
                with pytest.raises(StorageError) as error:require_task_open(db,{**task,'task_type':'pdf_export'})
                assert error.value.code=='storage_deletion_scope_unknown'
