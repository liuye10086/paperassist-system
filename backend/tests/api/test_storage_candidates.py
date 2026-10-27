"""Durable allocation evidence in new isolated schemas; no provider/network calls."""
import hashlib
import pytest
from uuid import uuid4
from app.core.exceptions import StorageError
from app.domain.storage_governance import service as s
from tests.api.test_admin_operations import accounts
from tests.api.test_storage_governance import project


@pytest.mark.parametrize('location',['target','part'])
def test_captured_v2_key_rejects_different_v1_reservation(accounts,location):
    store,pid=project(accounts);root=store.directory;png=b'png';descriptor=b'{"candidate":true}'
    with store.connection(write=True) as db:
        hold=s.admit_candidate(db,root,pid,'v2',root/'target',40,task_id='task',source_identity='call')
        s.capture_candidate(db,root,hold['id'],png,[root/location],source_identity='call',
            descriptor=descriptor,descriptor_path=root/'descriptor.json',write_path=root/location)
        with pytest.raises(StorageError) as error:
            s.reserve(db,root,pid,'different-v1',root/location,len(png),sha256=hashlib.sha256(png).hexdigest())
        assert error.value.code=='storage_reservation_conflict'
        # Also reject an old v1 row restored independently of the new-entry guard.
        other={**hold,'id':str(uuid4()),'operation_key':'restored-v1','object_key':location,'size_bytes':len(png),'sha256':hashlib.sha256(png).hexdigest()}
        assert other['id']!=hold['id']
        s._insert_reservation(db,other)
        for action in (s.settle,s.recover_reservation):
            with pytest.raises(StorageError):action(db,root,other['id'])
        assert not db.execute('SELECT id FROM storage_objects').fetchall()
        s.publish_candidate(db,root,hold['id'])
        # After complete publication, legitimate same-object references still deduplicate.
        duplicate=s.reserve(db,root,pid,'published-reference',root/'target',len(png),sha256=hashlib.sha256(png).hexdigest())
        s.settle(db,root,duplicate['id'])
        assert s.usage(db,project_id=pid)['usage_bytes']==len(png)+len(descriptor)


def test_registered_primary_does_not_hide_unregistered_companion_charge(accounts):
    store,pid=project(accounts);root=store.directory;descriptor=b'{"candidate":true}'
    with store.connection(write=True) as db:
        hold=s.admit_candidate(db,root,pid,'v2',root/'target',40,task_id='task',source_identity='call')
        captured=s.capture_candidate(db,root,hold['id'],b'png',[root/'target'],source_identity='call',
            descriptor=descriptor,descriptor_path=root/'descriptor.json',write_path=root/'target')
        # A historical primary-only registration must not erase the remaining physical bytes.
        s._register(db,captured,3,hashlib.sha256(b'png').hexdigest())
        value=s.usage(db,project_id=pid)
        assert value['usage_bytes']==3 and value['reserved_bytes']==len(descriptor)
        s.publish_candidate(db,root,hold['id'])
        value=s.usage(db,project_id=pid)
        assert value['usage_bytes']==3+len(descriptor) and value['reserved_bytes']==0


@pytest.mark.parametrize('damage',['missing','corrupt','old-incomplete'])
def test_descriptor_evidence_never_downgrades_damage_to_original_response(accounts,monkeypatch,damage):
    from app.domain.storage_governance import candidates as c
    store,pid=project(accounts);root=store.directory
    with store.connection(write=True) as db:
        hold=s.admit_candidate(db,root,pid,'descriptor',root/'target',40,task_id='task',source_identity='call')
    write=c._write_immutable
    if damage=='old-incomplete':
        def broken(path,content):
            if path.suffix=='.json':raise OSError('old first write without rebuild format')
            return write(path,content)
        monkeypatch.setattr(c,'_write_immutable',broken)
    try:
        with store.connection(write=True) as db:
            s.capture_candidate(db,root,hold['id'],b'png',[root/'part'],source_identity='call',
                descriptor=b'{}',descriptor_path=root/'descriptor.json',write_path=root/'part',
                descriptor_format=None if damage=='old-incomplete' else c.FIGURE_DESCRIPTOR_FORMAT)
    except OSError:
        assert damage=='old-incomplete'
    monkeypatch.setattr(c,'_write_immutable',write)
    if damage=='missing':(root/'descriptor.json').unlink() # Only this new isolated synthetic file.
    if damage=='corrupt':(root/'descriptor.json').write_bytes(b'bad')
    with store.connection(write=True) as db:
        assert s.reconcile_intents(db,root)==0
        row=c._row(db,hold['id'])
        assert c.candidate_recovery_mode(root,row)=='blocked'
        if damage!='old-incomplete':
            with pytest.raises(StorageError):
                s.capture_candidate(db,root,hold['id'],b'png',[root/'part'],source_identity='call',
                    descriptor=b'{}',descriptor_path=root/'descriptor.json',write_path=root/'part',descriptor_format=c.FIGURE_DESCRIPTOR_FORMAT)


def disk(monkeypatch, free):
    monkeypatch.setattr(s, 'disk_status', lambda root: dict(status='sufficient',
        free_bytes=free, threshold_bytes=100, total_bytes=1000))


def test_all_reservations_share_durable_unwritten_disk_holds(accounts, monkeypatch):
    store, pid = project(accounts)
    disk(monkeypatch, 110)
    with store.connection(write=True) as db:
        s.reserve(db, store.directory, pid, 'first', store.directory/'one', 6)
    with store.connection(write=True) as db:
        with pytest.raises(StorageError) as error:
            s.reserve(db, store.directory, pid, 'second', store.directory/'two', 6)
        assert error.value.code == 'storage_disk_insufficient'
        # The same physical key does not allocate another six bytes.
        s.reserve(db, store.directory, pid, 'same', store.directory/'one', 6)


def test_candidate_capacity_capture_move_and_explicit_tightened_recovery(accounts, monkeypatch):
    store, pid = project(accounts); root = store.directory
    disk(monkeypatch, 120)
    with store.connection(write=True) as db:
        hold = s.admit_candidate(db, root, pid, 'candidate', root/'target', 12,
            task_id='original-task', source_identity='original-call')
    with store.connection(write=True) as db:
        s.set_policy(db, 'project', pid, 0, 'enforced')
        s.capture_candidate(db, root, hold['id'], b'1234', [root/'part'], source_identity='original-call')
    (root/'part').write_bytes(b'1234')
    with store.connection(write=True) as db:
        value=s.usage(db,project_id=pid)
        assert value['reserved_bytes']==4
        with pytest.raises(StorageError) as error:s.publish_candidate(db,root,hold['id'])
        assert error.value.code=='storage_quota_exceeded'
    assert (root/'part').read_bytes()==b'1234' and not (root/'target').exists()
    with store.connection(write=True) as db:
        s.release(db,hold['id'],unknown=True)
        s.set_policy(db,'project',pid,4,'enforced')
        with pytest.raises(StorageError):s.settle(db,root,hold['id'])
        with pytest.raises(StorageError):s.publish_candidate(db,root,hold['id'])
        s.publish_candidate(db,root,hold['id'],explicit_recovery=True)
        assert s.usage(db,project_id=pid)['usage_bytes']==4
        assert s.usage(db,project_id=pid)['reserved_bytes']==0
    assert not (root/'part').exists() and (root/'target').read_bytes()==b'1234'


def test_capture_rollback_journal_reconstructs_original_hold(accounts, monkeypatch):
    store,pid=project(accounts);root=store.directory
    with store.connection(write=True) as db:
        hold=s.admit_candidate(db,root,pid,'capture',root/'target',12,task_id='task',source_identity='call')
    with pytest.raises(RuntimeError):
        with store.connection(write=True) as db:
            s.capture_candidate(db,root,hold['id'],b'captured',[root/'part'],source_identity='call')
            raise RuntimeError('synthetic rollback')
    (root/'part').write_bytes(b'captured')
    with store.connection(write=True) as db:
        assert s.reconcile_intents(db,root)==0
        row=db.execute('SELECT * FROM storage_reservations WHERE id=%s',(hold['id'],)).fetchone()
        assert row['state']=='unknown' and row['size_bytes']==8 and row['capacity_bytes']==12
        with pytest.raises(StorageError):s.publish_candidate(db,root,hold['id'])
        s.publish_candidate(db,root,hold['id'],explicit_recovery=True)
        assert s.usage(db,project_id=pid)['usage_bytes']==8


def test_materialized_candidate_not_double_subtracted_from_disk(accounts,monkeypatch):
    store,pid=project(accounts);root=store.directory
    disk(monkeypatch,112)
    with store.connection(write=True) as db:
        hold=s.admit_candidate(db,root,pid,'one',root/'target',12,task_id='task',source_identity='call')
        s.capture_candidate(db,root,hold['id'],b'1234',[root/'part'],source_identity='call')
    (root/'part').write_bytes(b'1234')
    disk(monkeypatch,108)
    with store.connection(write=True) as db:
        s.reserve(db,root,pid,'second',root/'second',8)


def test_companion_descriptor_is_counted_and_survives_capture_transaction_rollback(accounts):
    store,pid=project(accounts);root=store.directory
    with store.connection(write=True) as db:
        hold=s.admit_candidate(db,root,pid,'descriptor',root/'target',40,task_id='task',source_identity='call')
    with pytest.raises(RuntimeError):
        with store.connection(write=True) as db:
            s.capture_candidate(db,root,hold['id'],b'png',[root/'part'],source_identity='call',
                descriptor=b'{"candidate":true}',descriptor_path=root/'descriptor.json',write_path=root/'part')
            raise RuntimeError('capture transaction rollback')
    assert (root/'part').read_bytes()==b'png'
    assert (root/'descriptor.json').read_bytes()==b'{"candidate":true}'
    with store.connection(write=True) as db:
        assert s.reconcile_intents(db,root)==0
        assert s.usage(db,project_id=pid)['reserved_bytes']==21
        s.publish_candidate(db,root,hold['id'],explicit_recovery=True)
        value=s.usage(db,project_id=pid)
        assert value['object_count']==2 and value['usage_bytes']==21 and value['reserved_bytes']==0


def test_unbound_candidate_key_cannot_be_claimed_by_ordinary_reserve(accounts):
    store,pid=project(accounts);root=store.directory
    with store.connection(write=True) as db:
        s.admit_candidate(db,root,pid,'candidate',root/'target',12,task_id='task',source_identity='call')
        with pytest.raises(StorageError) as error:s.reserve(db,root,pid,'other',root/'target',3)
        assert error.value.code=='storage_reservation_conflict'


def test_direct_settle_rechecks_tightened_policy(accounts):
    store,pid=project(accounts);root=store.directory
    with store.connection(write=True) as db:
        hold=s.reserve(db,root,pid,'ordinary',root/'target',3,sha256=hashlib.sha256(b'123').hexdigest())
        (root/'target').write_bytes(b'123')
        s.set_policy(db,'project',pid,0,'enforced')
        with pytest.raises(StorageError) as error:s.settle(db,root,hold['id'])
        assert error.value.code=='storage_quota_exceeded'


def test_v1_recovery_cannot_bypass_companion_publication(accounts):
    store,pid=project(accounts);root=store.directory
    with store.connection(write=True) as db:
        hold=s.admit_candidate(db,root,pid,'candidate',root/'target',40,task_id='task',source_identity='call')
        s.capture_candidate(db,root,hold['id'],b'png',[root/'target'],source_identity='call',
            descriptor=b'{}',descriptor_path=root/'descriptor',write_path=root/'target')
        s.release(db,hold['id'],unknown=True)
        with pytest.raises(StorageError):s.recover_reservation(db,root,hold['id'])


def test_concurrent_candidate_holds_share_disk_across_owners(accounts,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.adapters.storage import ProjectStore
    store,pid=project(accounts);other=ProjectStore(store.directory,owner_id=accounts[0]['id'])
    second=other.create_project('isolated second','synthetic','sci')['id']
    disk(monkeypatch,110);barrier=Barrier(2)
    def admit(identifier):
        barrier.wait(timeout=10)
        try:
            with store.connection(write=True) as db:
                s.admit_candidate(db,store.directory,identifier,'hold',store.directory/identifier,6,task_id=identifier,source_identity=identifier)
            return 'admitted'
        except StorageError as error:return error.code
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(admit,[pid,second]))
    assert sorted(results)==['admitted','storage_disk_insufficient']


def test_duplicate_locations_remain_charged_and_are_never_deleted(accounts):
    store,pid=project(accounts);root=store.directory
    with store.connection(write=True) as db:
        hold=s.admit_candidate(db,root,pid,'two-locations',root/'target',12,task_id='task',source_identity='call')
        s.capture_candidate(db,root,hold['id'],b'1234',[root/'part'],source_identity='call')
    (root/'part').write_bytes(b'1234');(root/'target').write_bytes(b'1234')
    with store.connection(write=True) as db:
        assert s.reconcile_intents(db,root)==0
        assert s.usage(db,project_id=pid)['reserved_bytes']==8
        with pytest.raises(StorageError):s.publish_candidate(db,root,hold['id'],explicit_recovery=True)
    assert (root/'part').read_bytes()==(root/'target').read_bytes()==b'1234'


def test_relative_intents_restore_into_new_root_with_old_origin_provenance(accounts,tmp_path):
    import json,shutil
    store,pid=project(accounts);root=store.directory;restored=tmp_path/'restored-linux-assets'
    with store.connection(write=True) as db:
        hold=s.admit_candidate(db,root,pid,'portable',root/'figures'/'target',12,task_id='task',source_identity='call')
        s.capture_candidate(db,root,hold['id'],b'1234',[root/'staging'/'candidate'],source_identity='call',
            descriptor=b'{}',descriptor_path=root/'staging'/'descriptor.json',write_path=root/'staging'/'candidate')
    assert (root/'.storage-intents'/(hold['id']+'.complete.json')).stat().st_size<=8192
    shutil.copytree(root,restored)
    for path in (restored/'.storage-intents').glob('*.json'):
        data=json.loads(path.read_text());data['schema']='retained_windows_origin';data['database']='archived_origin'
        assert '\\' not in data['object_key']
        path.write_text(json.dumps(data))
    # Only this test's new isolated reservation is removed to model a restored
    # schema whose transaction was absent; retained source files stay untouched.
    with store.connection(write=True) as db:
        db.execute('DELETE FROM storage_reservations WHERE id=%s',(hold['id'],))
        assert s.reconcile_intents(db,restored)==0
        s.publish_candidate(db,restored,hold['id'],explicit_recovery=True)
    assert (restored/'figures'/'target').read_bytes()==b'1234'
    assert (root/'staging'/'candidate').read_bytes()==b'1234'


@pytest.mark.parametrize('name',['C:\\foreign','bad\\separator'])
def test_nonportable_relative_keys_are_rejected_before_capture(accounts,name):
    store,pid=project(accounts);root=store.directory
    with store.connection(write=True) as db:
        with pytest.raises(StorageError):s.admit_candidate(db,root,pid,'bad',root/name,12,task_id='task',source_identity='call')


def test_v1_explicit_missing_retransmission_retains_sibling_unknown(accounts):
    store,pid=project(accounts);root=store.directory
    with pytest.raises(RuntimeError):
        with store.connection(write=True) as db:
            with s.publication(db,root,pid,'one',root/'one',b'1234'):
                with s.publication(db,root,pid,'two',root/'two',b'1234'):
                    raise RuntimeError('registered intents before bytes; isolated crash')
    with store.connection(write=True) as db:
        assert s.reconcile_intents(db,root)==0
        with s.publication(db,root,pid,'one',root/'one',b'1234',recover=True):
            (root/'one').write_bytes(b'1234')
        value=s.usage(db,project_id=pid)
        assert value['usage_bytes']==4 and value['reserved_bytes']==4 and value['unknown_reservation_count']==1
