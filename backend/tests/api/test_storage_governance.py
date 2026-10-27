"""Storage foundation: isolated schemas and synthetic byte objects only."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from app.adapters.storage import ProjectStore
from app.core.config import get_data_dir
from app.core.exceptions import StorageError
from app.db.database import database_connection
from app.main import app
from tests.api.test_admin_operations import accounts, admin, login


def project(accounts):
    store=ProjectStore(get_data_dir(),owner_id=accounts[2]['id'])
    return store,store.create_project('private filename project','private topic','sci')['id']


def test_storage_routes_and_default_limits(admin,accounts):
    store,pid=project(accounts)
    own=admin.get('/api/v1/me/storage')
    assert own.status_code==200,own.text
    assert own.json()['quota']['limit_bytes']==5*1024**3
    with TestClient(app) as client:
        login(client,accounts[2])
        value=client.get('/api/v1/me/storage',params={'project_id':pid})
        assert value.status_code==200,value.text
        assert value.json()['quota']['limit_bytes']==1024**3
        assert client.get('/api/v1/admin/storage').status_code==403
        assert admin.get('/api/v1/me/storage',params={'project_id':pid}).status_code==404


def test_upload_atomic_limit_failure_and_download_retention(admin,accounts):
    store,pid=project(accounts)
    response=admin.put('/api/v1/admin/storage/policies/project/'+pid,json={'limit_bytes':10,'mode':'enforced','expected_revision':0,'reason':'Synthetic quota validation'})
    assert response.status_code==200,response.text
    def upload():
        try:return store.save_file(pid,'secret.xlsx',b'123456',None,None)
        except StorageError as exc:return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:upload(),range(2)))
    assert sum(isinstance(r,dict) for r in results)==1,results
    assert 'storage_quota_exceeded' in results
    record=next(r for r in results if isinstance(r,dict))
    assert store.original(store.file(pid,record['id']))==b'123456'
    assert admin.put('/api/v1/admin/storage/policies/project/'+pid,json={'limit_bytes':1,'mode':'enforced','expected_revision':1,'reason':'Synthetic lower quota validation'}).status_code==200
    assert store.original(store.file(pid,record['id']))==b'123456'
    safe=admin.get('/api/v1/admin/storage').json()
    assert safe['usage_bytes']==6
    assert all(secret not in str(safe) for secret in ('secret.xlsx','private topic',str(store.directory)))


def test_reservation_unknown_idempotence_and_physical_object_dedup(accounts):
    from app.domain.storage_governance.service import reserve,settle,release,usage,set_policy
    store,pid=project(accounts);root=store.directory
    target=root/'figures'/'one.png';target.parent.mkdir(exist_ok=True);content=b'123456'
    with store.connection(write=True) as db:
        set_policy(db,'project',pid,10,'enforced')
        first=reserve(db,root,pid,'first',target,len(content),kind='figure')
        assert reserve(db,root,pid,'first',target,len(content),kind='figure')['id']==first['id']
        release(db,first['id'],unknown=True)
    with store.connection(write=True) as db:
        assert usage(db,project_id=pid)['reserved_bytes']==6
        with pytest.raises(StorageError,match='未知'):reserve(db,root,pid,'second',root/'other',6)
        release(db,first['id'])
    with store.connection(write=True) as db:
        first=reserve(db,root,pid,'write',target,len(content));target.write_bytes(content);settle(db,root,first['id'])
        other=target
        second=reserve(db,root,pid,'link',other,len(content));settle(db,root,second['id'])
        value=usage(db,project_id=pid)
        assert value['usage_bytes']==6 and value['object_count']==1 and value['reserved_bytes']==0


def test_inventory_unknown_and_disk_protection(admin,accounts,monkeypatch):
    from app.domain.storage_governance import service
    store,pid=project(accounts)
    (store.directory/'orphan.secret').write_bytes(b'orphan')
    scan=admin.post('/api/v1/admin/storage/scan')
    assert scan.status_code==200,scan.text
    assert scan.json()['inventory']['unknown_count']>=1
    assert 'orphan.secret' not in scan.text
    monkeypatch.setattr(service.shutil,'disk_usage',lambda _:type('Disk',(),{'total':100*1024**3,'free':1})())
    with pytest.raises(StorageError) as err:store.save_file(pid,'disk.xlsx',b'data',None,None)
    assert err.value.code=='storage_disk_insufficient'


def test_rollback_retains_intent_and_unknown_charge(accounts):
    from app.domain.storage_governance.service import publication,reconcile_intents,usage
    store,pid=project(accounts);target=store.directory/'figures'/'safe.png'
    with pytest.raises(RuntimeError):
        with store.connection(write=True) as db:
            with publication(db,store.directory,pid,'paid-call-original',target,b'safe',kind='figure',task_id='original-task'):
                target.parent.mkdir(exist_ok=True);target.write_bytes(b'safe')
            raise RuntimeError('commit acknowledgement unknown')
    assert target.read_bytes()==b'safe'
    with store.connection(write=True) as db:
        reconcile_intents(db,store.directory)
        value=usage(db,project_id=pid)
        assert value['reserved_bytes']==4 and value['unknown_reservation_count']==1
        row=db.execute('SELECT * FROM storage_reservations WHERE project_id=%s',(pid,)).fetchone()
        assert row['operation_key']=='paid-call-original' and row['task_id']=='original-task'



def test_scan_snapshot_survives_next_read(admin,accounts):
    store,pid=project(accounts)
    (store.directory/'unmapped-cache').write_bytes(b'cache')
    first=admin.post('/api/v1/admin/storage/scan').json()['inventory']
    after=admin.get('/api/v1/admin/storage').json()
    assert after['inventory']==first


def test_user_quota_counts_multiple_projects_and_warning(accounts):
    from app.domain.storage_governance.service import set_policy,usage
    store,one=project(accounts);two=store.create_project('two','topic','sci')['id']
    with store.connection(write=True) as db:set_policy(db,'user',accounts[2]['id'],10,'enforced')
    store.save_file(one,'one.xlsx',b'12345678',None,None)
    with store.connection() as db:assert usage(db,user_id=accounts[2]['id'])['status']=='warning'
    with pytest.raises(StorageError) as err:store.save_file(two,'two.xlsx',b'123',None,None)
    assert err.value.code=='storage_quota_exceeded'


def test_explicit_recovery_keeps_original_identity_and_rechecks_limit(accounts):
    from app.domain.storage_governance.service import publication,reconcile_intents,recover_reservation,set_policy,usage
    store,pid=project(accounts);target=store.directory/'figures'/'recover.png'
    with pytest.raises(RuntimeError):
        with store.connection(write=True) as db:
            with publication(db,store.directory,pid,'same-call',target,b'1234',kind='figure',task_id='same-task'):
                target.parent.mkdir(exist_ok=True);target.write_bytes(b'1234')
            raise RuntimeError()
    with store.connection(write=True) as db:
        reconcile_intents(db,store.directory)
        row=db.execute('SELECT * FROM storage_reservations WHERE project_id=%s',(pid,)).fetchone()
        set_policy(db,'project',pid,3,'enforced')
        with pytest.raises(StorageError) as err:recover_reservation(db,store.directory,row['id'])
        assert err.value.code=='storage_quota_exceeded'
        set_policy(db,'project',pid,4,'enforced')
        obj=recover_reservation(db,store.directory,row['id'])
        assert recover_reservation(db,store.directory,row['id'])==obj
        assert usage(db,project_id=pid)['usage_bytes']==4
        assert usage(db,project_id=pid)['reserved_bytes']==0


def test_quota_policy_revision_conflict_and_audit(admin,accounts):
    store,pid=project(accounts);url='/api/v1/admin/storage/policies/project/'+pid
    first=admin.put(url,json={'limit_bytes':10,'mode':'enforced','expected_revision':0,'reason':'Synthetic storage quota change'})
    assert first.status_code==200,first.text
    assert first.json()['revision']==1
    stale=admin.put(url,json={'limit_bytes':20,'mode':'enforced','expected_revision':0,'reason':'Synthetic stale quota change'})
    assert stale.status_code==409,stale.text
    events=admin.get('/api/v1/admin/storage/policy-events').json()['items']
    assert len(events)==1 and events[0]['actor_user_id']==accounts[0]['id']
    assert events[0]['before_limit_bytes']==1024**3 and events[0]['after_limit_bytes']==10


def test_same_physical_key_multiple_scopes_and_pending_refs_count_once(accounts):
    from app.domain.storage_governance.service import reserve,settle,usage,set_policy
    store,one=project(accounts);two=store.create_project('two','topic','sci')['id']
    target=store.directory/'shared.bin'
    with store.connection(write=True) as db:
        set_policy(db,'user',accounts[2]['id'],6,'enforced')
        a=reserve(db,store.directory,one,'one',target,6)
        b=reserve(db,store.directory,one,'same-key',target,6)
        assert usage(db,user_id=accounts[2]['id'])['reserved_bytes']==6
        target.write_bytes(b'123456');settle(db,store.directory,a['id']);settle(db,store.directory,b['id'])
        c=reserve(db,store.directory,two,'shared-reference',target,6);settle(db,store.directory,c['id'])
        assert usage(db,user_id=accounts[2]['id'])['usage_bytes']==6
        assert usage(db,project_id=two)['usage_bytes']==6


def test_missing_known_object_is_unknown_not_complete_scan(admin,accounts):
    store,pid=project(accounts)
    record=store.save_file(pid,'synthetic.xlsx',b'synthetic',None,None)
    path=store.directory/store.file(pid,record['id'])['object_key']
    assert path.is_relative_to(store.directory)
    path.unlink()  # This test's new isolated synthetic file, never historical data.
    scan=admin.post('/api/v1/admin/storage/scan').json()
    assert scan['inventory']['status']=='unknown'
    assert scan['inventory']['unknown_count']==1
    assert scan['unknown_object_count']==1
    assert scan['usage_scope']=='registered_asset_objects'
