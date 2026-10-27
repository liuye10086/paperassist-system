"""A1 F1-F5 review counterexamples; synthetic isolated schemas and bytes only."""
import hashlib
from datetime import datetime, timezone
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from app.core.exceptions import StorageError
from app.main import app
from app.domain.storage_governance import service
from tests.api.test_admin_operations import accounts, admin, login
from tests.api.test_storage_governance import project
from tests.api.test_excel import workbook_bytes


@pytest.mark.parametrize('size,digest',[(100,'a'*64),(6,'b'*64)])
def test_f1_conflicting_pending_identity_never_expands_unique_charge(accounts,size,digest):
    store,pid=project(accounts);target=store.directory/'pending.bin'
    with store.connection(write=True) as db:
        service.set_policy(db,'project',pid,6,'enforced')
        first=service.reserve(db,store.directory,pid,'one',target,6,sha256='a'*64)
        with pytest.raises(StorageError) as err:
            service.reserve(db,store.directory,pid,'conflict',target,size,sha256=digest)
        assert err.value.code=='storage_reservation_conflict'
        assert service.usage(db,project_id=pid)['reserved_bytes']==6
        same=service.reserve(db,store.directory,pid,'same-content',target,6,sha256='a'*64)
        assert same['id']!=first['id']
        assert service.usage(db,project_id=pid)['reserved_bytes']==6


def test_f2_multiple_rollback_candidates_recover_without_releasing_other_holds(accounts):
    store,pid=project(accounts)
    with pytest.raises(RuntimeError):
        with store.connection(write=True) as db:
            for name in ('one','two'):
                path=store.directory/(name+'.bin')
                with service.publication(db,store.directory,pid,name,path,b'1234',task_id='original-'+name):path.write_bytes(b'1234')
            raise RuntimeError('synthetic rollback')
    with store.connection(write=True) as db:
        service.reconcile_intents(db,store.directory)
        rows=list(db.execute('SELECT * FROM storage_reservations ORDER BY operation_key'))
        service.set_policy(db,'project',pid,7,'enforced')
        with pytest.raises(StorageError) as err:service.recover_reservation(db,store.directory,rows[0]['id'])
        assert err.value.code=='storage_quota_exceeded'
        service.set_policy(db,'project',pid,8,'enforced')
        service.recover_reservation(db,store.directory,rows[0]['id'])
        remaining=service.usage(db,project_id=pid)
        assert remaining['usage_bytes']==4 and remaining['reserved_bytes']==4
        assert remaining['unknown_reservation_count']==1
        service.recover_reservation(db,store.directory,rows[1]['id'])
        assert service.usage(db,project_id=pid)['usage_bytes']==8
        assert service.usage(db,project_id=pid)['reserved_bytes']==0
        after=list(db.execute('SELECT * FROM storage_reservations ORDER BY operation_key'))
        assert [(r['id'],r['operation_key'],r['task_id'],r['sha256']) for r in rows]==[(r['id'],r['operation_key'],r['task_id'],r['sha256']) for r in after]


@pytest.mark.parametrize('condition',['missing','unreadable','changed'])
def test_f3_legacy_metadata_first_scan_preserves_last_known_charge(accounts,monkeypatch,condition):
    store,pid=project(accounts);fid=str(uuid4());key='files/'+fid+'.xlsx';path=store.directory/key
    data=b'legacy';digest=hashlib.sha256(data).hexdigest()
    # Equivalent to pre-0053 files: trusted business row, no governance ledger/intent.
    with store.connection(write=True) as db:
        db.execute('''INSERT INTO files(id,project_id,filename,file_type,size_bytes,sha256,uploaded_at,parse_status,uploader_id,object_key)
            VALUES(%s,%s,'legacy.xlsx','xlsx',%s,%s,%s,'parsed',%s,%s)''',
            (fid,pid,len(data),digest,datetime.now(timezone.utc).isoformat(),accounts[2]['id'],key))
    if condition!='missing':path.write_bytes(data if condition=='unreadable' else b'altered')
    original=service._digest
    if condition=='unreadable':
        def unreadable(candidate):
            if candidate==path:raise PermissionError('synthetic access failure')
            return original(candidate)
        monkeypatch.setattr(service,'_digest',unreadable)
    for _ in range(2):
        with store.connection(write=True) as db:
            scan=service.inventory(db,store.directory);value=service.usage(db,project_id=pid)
            assert scan['status']=='unknown' and scan['unknown_count']==1
            assert value['usage_bytes']==len(data) and value['unknown_object_count']==1
            row=db.execute('SELECT * FROM storage_objects WHERE object_key=%s',(key,)).fetchone()
            assert row['state']=={'missing':'missing','unreadable':'unknown','changed':'changed'}[condition]
            assert row['size_bytes']==len(data) and row['sha256']==digest
    if condition!='missing':
        with store.connection(write=True) as db:service.set_policy(db,'project',pid,7,'enforced')
        with pytest.raises(StorageError) as err:store.save_file(pid,'new.xlsx',b'n',None,None)
        assert err.value.code=='storage_accounting_unknown'


@pytest.mark.parametrize('reader',['owner','admin'])
def test_f4_get_reconciles_rollback_before_and_after_another_failed_upload(accounts,reader):
    store,pid=project(accounts);path=store.directory/'rollback.bin'
    with pytest.raises(RuntimeError):
        with store.connection(write=True) as db:
            with service.publication(db,store.directory,pid,'rollback',path,b'1234',task_id='old-task'):path.write_bytes(b'1234')
            raise RuntimeError('rollback')
    with TestClient(app) as client:
        login(client,accounts[2] if reader=='owner' else accounts[0])
        for attempt in range(2):
            result=client.get('/api/v1/me/storage',params={'project_id':pid}) if reader=='owner' else client.get('/api/v1/admin/storage')
            assert result.status_code==200,result.text
            value=result.json()
            assert value['status']=='unknown' and value['reserved_bytes']==4
            assert value['unknown_reservation_count']==1 and value['reconciled_at']
            if attempt==0:
                with pytest.raises(StorageError):store.save_file(pid,'new.xlsx',b'other',None,None)
        with store.connection() as db:
            row=db.execute('SELECT state,task_id FROM storage_reservations WHERE project_id=%s',(pid,)).fetchone()
            assert row['state']=='unknown' and row['task_id']=='old-task'


@pytest.mark.parametrize('explicit_identity',[False,True])
def test_f5_sync_upload_reuses_failed_identity_and_keeps_independent_successes(accounts,reject_database_write,explicit_identity):
    store,pid=project(accounts);content=workbook_bytes();operation=str(uuid4())
    headers={'Idempotency-Key':operation} if explicit_identity else {}
    url=f'/api/v1/projects/{pid}/files'
    with TestClient(app) as client:
        login(client,accounts[2])
        with reject_database_write('files'):
            failed=client.post(url,files={'file':('sync.xlsx',content)},headers=headers)
        assert failed.status_code==503,failed.text
        paths=list(store.files_dir.glob('*.xlsx'));assert len(paths)==1
        original=paths[0]
        response=client.post(url,files={'file':('sync.xlsx',content)},headers=headers)
        assert response.status_code==201,response.text
        assert list(store.files_dir.glob('*.xlsx'))==[original]
        assert client.get(url+'/'+response.json()['file']['id']+'/download').content==content
        if explicit_identity:
            replay=client.post(url,files={'file':('sync.xlsx',content)},headers=headers)
            assert replay.status_code==201 and replay.json()['file']['id']==response.json()['file']['id']
            conflict=client.post(url,files={'file':('changed.xlsx',content)},headers=headers)
            assert conflict.status_code==409
        else:
            independent=client.post(url,files={'file':('sync.xlsx',content)})
            assert independent.status_code==201 and independent.json()['file']['id']!=response.json()['file']['id']


def test_f5_ambiguous_unfinished_sync_intents_reject_instead_of_guessing(accounts):
    import json
    store,pid=project(accounts);content=b'abc';filename='same.xlsx'
    fingerprint=hashlib.sha256(json.dumps([filename,hashlib.sha256(content).hexdigest()],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    with pytest.raises(RuntimeError):
        with store.connection(write=True) as db:
            for index in range(2):
                operation='sync:'+str(uuid4())+':'+fingerprint
                target=store.directory/('ambiguous-'+str(index)+'.xlsx')
                with service.publication(db,store.directory,pid,operation,target,content,kind='original'):target.write_bytes(content)
            raise RuntimeError('synthetic ambiguous intents')
    with pytest.raises(StorageError) as err:store.save_file(pid,filename,content,None,None)
    assert err.value.code=='storage_reservation_conflict'


def test_f5_explicit_identity_scope_content_and_saved_response(accounts,monkeypatch):
    from fastapi import HTTPException
    from app.adapters.storage import ProjectStore
    from app.api import projects as project_api
    store,pid=project(accounts);content=workbook_bytes();operation=str(uuid4())
    headers={'Idempotency-Key':operation};url=f'/api/v1/projects/{pid}/files'
    with TestClient(app) as client:
        login(client,accounts[2])
        first=client.post(url,files={'file':('saved.xlsx',content)},headers=headers)
        assert first.status_code==201,first.text
        def changed_parser(*args,**kwargs):
            raise HTTPException(422,detail={'code':'parse_failed','message':'Synthetic parser changed','params':{}})
        monkeypatch.setattr(project_api,'parse_workbook',changed_parser)
        replay=client.post(url,files={'file':('saved.xlsx',content)},headers=headers)
        assert replay.status_code==201 and replay.json()==first.json()
    with pytest.raises(StorageError) as err:store.save_file(pid,'saved.xlsx',b'different',None,None,operation_id=operation)
    assert err.value.code=='storage_reservation_conflict'
    other_pid=store.create_project('other project','topic','sci')['id']
    other=store.save_file(other_pid,'saved.xlsx',content,None,None,operation_id=operation)
    assert other['id']!=first.json()['file']['id']
    other_owner=ProjectStore(store.directory,owner_id=accounts[0]['id'])
    third_pid=other_owner.create_project('other owner','topic','sci')['id']
    third=other_owner.save_file(third_pid,'saved.xlsx',content,None,None,operation_id=operation)
    assert third['id'] not in (other['id'],first.json()['file']['id'])
    with pytest.raises(StorageError) as err:other_owner.save_file(pid,'saved.xlsx',content,None,None,operation_id=operation)
    assert err.value.code=='project_not_found'


@pytest.mark.parametrize('scanned',[False,True])
def test_f5_successful_replay_never_recreates_missing_original_under_restricted_admission(accounts,monkeypatch,scanned):
    store,pid=project(accounts);content=workbook_bytes();operation=str(uuid4())
    headers={'Idempotency-Key':operation};url=f'/api/v1/projects/{pid}/files'
    with TestClient(app) as client:
        login(client,accounts[2])
        first=client.post(url,files={'file':('persisted.xlsx',content)},headers=headers)
        assert first.status_code==201,first.text
        record=store.file(pid,first.json()['file']['id']);target=store.directory/record['object_key']
        with store.connection(write=True) as db:service.set_policy(db,'project',pid,0,'enforced')
        monkeypatch.setattr(service.shutil,'disk_usage',lambda _:type('Disk',(),{'total':100*1024**3,'free':1})())
        # Intact already-published bytes remain readable under both restrictions.
        replay=client.post(url,files={'file':('persisted.xlsx',content)},headers=headers)
        assert replay.status_code==201 and replay.json()==first.json()
        assert target.read_bytes()==content
        assert target.is_relative_to(store.directory)
        target.unlink()  # Only this test's newly created isolated synthetic asset.
        if scanned:
            with store.connection(write=True) as db:assert service.inventory(db,store.directory)['status']=='unknown'
        missing=client.post(url,files={'file':('persisted.xlsx',content)},headers=headers)
        assert missing.status_code==410,missing.text
        assert missing.json()['detail']['code']=='file_missing'
        assert not target.exists()
        with store.connection() as db:
            assert db.execute('SELECT count(*) AS n FROM files WHERE project_id=%s',(pid,)).fetchone()['n']==1
