"""Slow local settlement must retain a fenced lease despite serialized writers."""
import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from tests.api.test_projects import client
from tests.integration.test_bio_analysis_wait import create,payload_engine
from app.adapters.task_execution_store import TaskExecutionStore,LeaseLost
from app.adapters.bio_analysis_execution import BioAnalysisExecution
from app.db.database import database_connection


def test_slow_legacy_import_manifest_renews_while_background_heartbeat_blocks(client,monkeypatch,tmp_path):
    from app.adapters.bio_dataset_execution import BioDatasetExecution
    from app.domain.storage_governance import service as ledger
    from tests.integration.test_bio_import_publication import create_import,pure_registered_parser,read,confirm
    base,created,_,_=create_import(client)
    monkeypatch.setattr('app.adapters.task_execution_store.LEASE_SECONDS',3)
    repository=TaskExecutionStore();lease=repository.claim(created['task']['id'],created['task']['revision'],task_type='bio_import')
    execution=BioDatasetExecution(repository);task,checkpoint,files=execution.load(lease)
    output=tmp_path/'parsed';output.mkdir()
    result=pure_registered_parser({'files':files},output,task['input_snapshot']['settings'])
    original=ledger._digest;verify=ledger._settle_verified;active={};expired=[]
    started=threading.Event();pool=ThreadPoolExecutor(1);heartbeats=[]
    def settling(db,*args,**kwargs):
        active['db']=db
        try:return verify(db,*args,**kwargs)
        finally:active.pop('db',None)
    def heartbeat():started.set();return repository.heartbeat(lease)
    def slow(path):
        if 'db' in active and 'bio-datasets' in Path(path).parts:
            if not heartbeats:
                heartbeats.append(pool.submit(heartbeat));assert started.wait(1)
                time.sleep(.05);assert not heartbeats[0].done()
            time.sleep(.4)
            expired.append(active['db'].execute('SELECT lease_expires_at<=clock_timestamp() AS expired FROM task_attempts WHERE task_id=%s AND attempt_no=%s',
                (lease.task_id,lease.attempt_no)).fetchone()['expired'])
        return original(path)
    monkeypatch.setattr(ledger,'_settle_verified',settling);monkeypatch.setattr(ledger,'_digest',slow)
    try:
        begin=time.monotonic();response=execution.wait(lease,checkpoint,result)
        assert response['status']=='waiting_confirmation'
        assert time.monotonic()-begin>3 and len(expired)>7
        assert not any(expired),'Legacy bio import settlement outlived its lease with heartbeat blocked'
        assert heartbeats[0].result(timeout=5) is False
        view=read(client,base,created);queued=confirm(client,base,created,view)
        assert queued.status_code==202,queued.text
        lease=repository.claim(queued.json()['id'],queued.json()['revision'],task_type='bio_import')
        task,checkpoint,_=execution.load(lease)
        from app.adapters.bio_objects import BioObjects
        from app.adapters import bio_dataset_execution as adapter
        reader=BioObjects.read;renew=adapter.renew_bio_lease
        heartbeats.clear();expired.clear();started.clear()
        def observe_renew(db,current):
            active['db']=db
            return renew(db,current)
        def slow_read(self,record):
            if not heartbeats:
                heartbeats.append(pool.submit(heartbeat));assert started.wait(1)
                time.sleep(.05);assert not heartbeats[0].done()
            time.sleep(.3)
            expired.append(active['db'].execute('SELECT lease_expires_at<=clock_timestamp() AS expired FROM task_attempts WHERE task_id=%s AND attempt_no=%s',
                (lease.task_id,lease.attempt_no)).fetchone()['expired'])
            return reader(self,record)
        monkeypatch.setattr(adapter,'renew_bio_lease',observe_renew)
        monkeypatch.setattr(BioObjects,'read',slow_read)
        begin=time.monotonic();done=execution.publish(lease,checkpoint)
        assert done['status']=='succeeded' and time.monotonic()-begin>3
        assert len(expired)>7 and not any(expired)
        assert heartbeats[0].result(timeout=5) is False
    finally:pool.shutdown(wait=True)


def test_slow_candidate_history_renews_before_each_journal_while_heartbeat_blocks(client,monkeypatch,tmp_path):
    from app.domain.storage_governance import service as ledger
    _,created,_,_=create(client,monkeypatch,tmp_path)
    repository=TaskExecutionStore();root=repository.assets.directory
    with repository.connection(write=True) as db:
        for index in range(3):
            target=root/f'history-{index}.png'
            hold=ledger.admit_candidate(db,root,created['task']['project_id'],f'history-{index}',target,100,
                task_id=created['task']['id'],source_identity='synthetic-history')
            ledger.capture_candidate(db,root,hold['id'],b'png',[target],source_identity='synthetic-history',
                descriptor=b'{}',descriptor_path=root/f'history-{index}.json',write_path=target)
    monkeypatch.setattr('app.adapters.task_execution_store.LEASE_SECONDS',3)
    lease=repository.claim(created['task']['id'],created['task']['revision'],task_type='bio_analysis')
    original=Path.open;pool=ThreadPoolExecutor(1);started=threading.Event();heartbeats=[];expired=[];stages=[];renewals=[]
    def heartbeat():started.set();return repository.heartbeat(lease)
    try:
        with repository.connection(write=True) as db:
            def progress():
                BioAnalysisExecution.renew_lease(db,lease);renewals.append(time.monotonic())
            def slow(path,*args,**kwargs):
                if path.parent==root/'.storage-intents' and path.name.endswith(('.allocation.json','.capture.json','.complete.json')):
                    if not heartbeats:
                        heartbeats.append(pool.submit(heartbeat));assert started.wait(1)
                        time.sleep(.05);assert not heartbeats[0].done()
                    time.sleep(.4);stages.append(path.name.split('.')[-2])
                    expired.append(db.execute('SELECT lease_expires_at<=clock_timestamp() AS expired FROM task_attempts WHERE task_id=%s AND attempt_no=%s',
                        (lease.task_id,lease.attempt_no)).fetchone()['expired'])
                    assert len(renewals)>len(stages)-1, 'Candidate journal scan did not delegate per-entry progress'
                return original(path,*args,**kwargs)
            monkeypatch.setattr(Path,'open',slow)
            begin=time.monotonic()
            assert ledger.reconcile_intents(db,root,progress=progress)==0
            assert time.monotonic()-begin>3
            assert stages==['allocation']*3+['capture']*3+['complete']*3
            assert not any(expired)
        assert heartbeats[0].result(timeout=5) is True
    finally:pool.shutdown(wait=True)


def test_slow_manifest_renews_on_held_connection_while_background_heartbeat_blocks(client,monkeypatch,tmp_path):
    from app.domain.storage_governance import service as ledger
    base,created,staging,_=create(client,monkeypatch,tmp_path)
    # Shrink the fixture lease only; production remains the unchanged 60 seconds.
    monkeypatch.setattr('app.adapters.task_execution_store.LEASE_SECONDS',3)
    repository=TaskExecutionStore();lease=repository.claim(created['task']['id'],created['task']['revision'],task_type='bio_analysis')
    execution=BioAnalysisExecution(repository);task,checkpoint,payload=execution.load(lease)
    output=staging/task['id']/'fixture';output.mkdir(parents=True)
    result=payload_engine(payload,output,'qc')
    for index in range(12):
        content=('slow member '+str(index)).encode();path=output/f'extra_{index}.txt';path.write_bytes(content)
        result['outputs'].append(dict(key=f'extra_{index}',path=str(path),role='methods',format='txt',size_bytes=len(content),sha256=hashlib.sha256(content).hexdigest()))
    original=ledger._digest;started=threading.Event();pool=ThreadPoolExecutor(1);heartbeats=[];blocked=[];expired=[];active={}
    verify=ledger._settle_verified
    def settling(db,*args,**kwargs):
        active['db']=db
        try:return verify(db,*args,**kwargs)
        finally:active.pop('db',None)
    monkeypatch.setattr(ledger,'_settle_verified',settling)
    def heartbeat():started.set();return repository.heartbeat(lease)
    def slow(path):
        if 'bio-analysis' in Path(path).parts and Path(path).is_file():
            if not heartbeats:
                heartbeats.append(pool.submit(heartbeat));assert started.wait(1)
                time.sleep(.05);blocked.append(not heartbeats[0].done())
            time.sleep(.3)
            if 'db' in active:
                expired.append(active['db'].execute('SELECT lease_expires_at<=clock_timestamp() AS expired FROM task_attempts WHERE task_id=%s AND attempt_no=%s',
                    (lease.task_id,lease.attempt_no)).fetchone()['expired'])
        return original(path)
    monkeypatch.setattr(ledger,'_digest',slow)
    try:
        response=execution.wait(lease,checkpoint,result)
        with database_connection() as db:
            attempt=db.execute('SELECT * FROM task_attempts WHERE task_id=%s',(task['id'],)).fetchone()
        assert response['status']=='waiting_confirmation'
        assert blocked==[True] and attempt['finished_at'] is not None
        assert not any(expired),'Manifest hashing outlived the lease while its independent heartbeat was blocked'
        assert attempt['finished_at']-attempt['started_at']>__import__('datetime').timedelta(seconds=3)
        assert heartbeats[0].result(timeout=5) is False, 'Waiting completion must fence the blocked heartbeat'
    finally:pool.shutdown(wait=True)


def test_bio_batch_guards_are_once_per_manifest_not_once_per_leaf(client,monkeypatch,tmp_path):
    from app.domain.storage_governance import service as ledger
    from app.domain.storage_governance.bio_manifest import admit_bio_manifest,settle_bio_manifest
    _,created,_,_=create(client,monkeypatch,tmp_path)
    repository=TaskExecutionStore();lease=repository.claim(created['task']['id'],created['task']['revision'],task_type='bio_analysis')
    counts={key:0 for key in ('reconcile_intents','_scope_check','_disk_guard')}
    for key in counts:
        original=getattr(ledger,key)
        def counted(*args,_key=key,_original=original,**kwargs):counts[_key]+=1;return _original(*args,**kwargs)
        monkeypatch.setattr(ledger,key,counted)
    entries=[]
    for index in range(8):
        content=('batch '+str(index)).encode();sha=hashlib.sha256(content).hexdigest()
        key=f"bio-analysis/{created['id']}/{sha}.bin"
        entries.append(('bio_analysis',f"bio_analysis:{created['id']}:compute:leaf:{sha}",dict(object_key=key,size_bytes=len(content),sha256=sha)))
    with repository.connection(write=True) as db:
        task=repository.require_lease(db,lease)
        rows=admit_bio_manifest(db,repository.assets.directory,task,entries,progress=lambda:None)
    assert counts==dict(reconcile_intents=1,_scope_check=1,_disk_guard=1)
    from app.adapters.bio_objects import BioAnalysisObjects
    objects=BioAnalysisObjects(repository.assets.directory)
    for index,(_,_,record) in enumerate(entries):objects.write(record,('batch '+str(index)).encode())
    for key in counts:counts[key]=0
    with repository.connection(write=True) as db:settle_bio_manifest(db,repository.assets.directory,task,rows,progress=lambda:None)
    assert counts==dict(reconcile_intents=0,_scope_check=1,_disk_guard=0)
    with repository.connection(write=True) as db:
        replay=admit_bio_manifest(db,repository.assets.directory,task,entries,progress=lambda:None)
    assert [r['id'] for r in replay]==[r['id'] for r in rows]
    objects.path(entries[0][2]['object_key']).write_bytes(b'changed')
    from app.core.exceptions import StorageError
    with pytest.raises(StorageError):
        with repository.connection(write=True) as db:
            admit_bio_manifest(db,repository.assets.directory,task,entries,progress=lambda:None)


def test_manifest_quota_rejection_rolls_back_all_provisional_rows_before_journals(client,monkeypatch,tmp_path):
    from app.core.exceptions import StorageError
    from app.domain.storage_governance import service as ledger
    from app.domain.storage_governance.bio_manifest import admit_bio_manifest
    _,created,_,_=create(client,monkeypatch,tmp_path)
    repository=TaskExecutionStore();lease=repository.claim(created['task']['id'],created['task']['revision'],task_type='bio_analysis')
    with repository.connection(write=True) as db:
        task=repository.require_lease(db,lease);usage=ledger.usage(db,project_id=task['project_id'])
        ledger.set_policy(db,'project',task['project_id'],usage['usage_bytes']+10,'enforced',reason='Synthetic batch quota boundary')
    entries=[]
    for index in range(3):
        content=('quota-'+str(index)).encode();sha=hashlib.sha256(content).hexdigest()
        entries.append(('bio_analysis','quota-fixture:'+str(index),dict(object_key=f"bio-analysis/{created['id']}/{sha}.bin",size_bytes=len(content),sha256=sha)))
    journals=set((repository.assets.directory/'.storage-intents').iterdir())
    with pytest.raises(StorageError) as failure:
        with repository.connection(write=True) as db:
            admit_bio_manifest(db,repository.assets.directory,task,entries,progress=lambda:BioAnalysisExecution.renew_lease(db,lease))
    assert failure.value.code=='storage_quota_exceeded'
    with database_connection() as db:
        assert db.execute("SELECT count(*) AS n FROM storage_reservations WHERE operation_key LIKE 'quota-fixture:%%'").fetchone()['n']==0
    assert set((repository.assets.directory/'.storage-intents').iterdir())==journals
    # A second logical operation sharing physical bytes must not double-charge.
    aliases=entries+[('bio_analysis','quota-fixture:alias',entries[0][2])]
    with repository.connection(write=True) as db:
        ledger.set_policy(db,'project',task['project_id'],usage['usage_bytes']+21,'enforced',reason='Synthetic exact deduplicated quota')
        admitted=admit_bio_manifest(db,repository.assets.directory,task,aliases,progress=lambda:BioAnalysisExecution.renew_lease(db,lease))
        assert ledger.usage(db,project_id=task['project_id'])['reserved_bytes']==21
    assert len(admitted)==4


def test_same_connection_renewal_never_revives_expired_or_wrong_token_lease(client,monkeypatch,tmp_path):
    from app.adapters.task_execution_store import TaskLease
    _,created,_,_=create(client,monkeypatch,tmp_path)
    repository=TaskExecutionStore();lease=repository.claim(created['task']['id'],created['task']['revision'],task_type='bio_analysis')
    with repository.connection(write=True) as db:
        before=db.execute('SELECT lease_expires_at FROM task_attempts WHERE task_id=%s',(lease.task_id,)).fetchone()['lease_expires_at']
        with pytest.raises(LeaseLost):BioAnalysisExecution.renew_lease(db,TaskLease(lease.task_id,lease.attempt_no,'wrong-token'))
        assert db.execute('SELECT lease_expires_at FROM task_attempts WHERE task_id=%s',(lease.task_id,)).fetchone()['lease_expires_at']==before
        db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s",(lease.task_id,))
        expired=db.execute('SELECT lease_expires_at FROM task_attempts WHERE task_id=%s',(lease.task_id,)).fetchone()['lease_expires_at']
        with pytest.raises(LeaseLost):BioAnalysisExecution.renew_lease(db,lease)
        assert db.execute('SELECT lease_expires_at FROM task_attempts WHERE task_id=%s',(lease.task_id,)).fetchone()['lease_expires_at']==expired


def test_lost_lease_mid_settlement_rolls_back_objects_and_never_publishes_wait(client,monkeypatch,tmp_path):
    from app.domain.storage_governance import service as ledger
    _,created,staging,_=create(client,monkeypatch,tmp_path)
    repository=TaskExecutionStore();lease=repository.claim(created['task']['id'],created['task']['revision'],task_type='bio_analysis')
    execution=BioAnalysisExecution(repository);task,checkpoint,payload=execution.load(lease)
    output=staging/task['id']/'fenced';output.mkdir(parents=True)
    result=payload_engine(payload,output,'qc');verify=ledger._settle_verified
    def expire_after_first_settle(db,*args,**kwargs):
        value=verify(db,*args,**kwargs)
        db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s",(lease.task_id,))
        return value
    monkeypatch.setattr(ledger,'_settle_verified',expire_after_first_settle)
    with pytest.raises(LeaseLost):execution.wait(lease,checkpoint,result)
    with database_connection() as db:
        assert db.execute('SELECT status FROM tasks WHERE id=%s',(lease.task_id,)).fetchone()['status']=='running'
        assert db.execute('SELECT count(*) AS n FROM task_waits WHERE task_id=%s',(lease.task_id,)).fetchone()['n']==0
        rows=list(db.execute('SELECT state FROM storage_reservations WHERE task_id=%s',(lease.task_id,)))
        assert rows and all(r['state']=='reserved' for r in rows)
