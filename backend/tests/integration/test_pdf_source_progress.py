"""Research-report PDF progress coalescing preserves original publication fences."""
import time
from types import SimpleNamespace

import pytest
from tests.api.test_research_findings import client, selected_cell


def verifier():
    from app.domain.pdf_exports import execution
    assert hasattr(execution, '_verify_source'), 'PDF still forwards every source callback to SQL'
    return execution, execution._verify_source


@pytest.mark.parametrize('lease_seconds', [60, 1])
def test_full_traversal_with_bounded_renewal_interval_and_forced_boundaries(monkeypatch, lease_seconds):
    execution, verify = verifier()
    from app.adapters import task_execution_store
    monkeypatch.setattr(task_execution_store, 'LEASE_SECONDS', lease_seconds)
    clock=[0.0];calls=[];visited=[]
    monkeypatch.setattr(execution, 'monotonic', lambda:clock[0])
    interval=min(1.0,lease_seconds/4)
    def original():calls.append(clock[0])
    original.renewed={'original':'retained'}
    def source(db,row,*,progress):
        assert progress is not original
        for _ in range(29971):visited.append(True);progress()
        clock[0]=interval-.001;progress()
        clock[0]=interval;progress()
        clock[0]=2*interval-.001;progress()
        clock[0]=2*interval;progress()
        return b'exact DOCX'
    assert verify(SimpleNamespace(verify_source=source),None,{'source_kind':'research_report'},original)==b'exact DOCX'
    assert len(visited)==29971
    assert calls==[0.0,interval,2*interval,2*interval]
    assert original.renewed=={'original':'retained'}


def test_each_source_phase_forces_entry_exit_even_in_same_clock_tick(monkeypatch):
    execution,verify=verifier();monkeypatch.setattr(execution,'monotonic',lambda:10.0)
    calls=[];callbacks=[]
    def original():calls.append(True)
    def source(db,row,*,progress):
        callbacks.append(progress)
        for _ in range(100):progress()
        return b'unchanged'
    service=SimpleNamespace(verify_source=source)
    for _ in range(2):assert verify(service,None,{'source_kind':'research_report'},original)==b'unchanged'
    assert len(calls)==4 and callbacks[0] is not callbacks[1]


def test_other_pdf_sources_keep_original_callback_identity_and_single_post():
    _,verify=verifier()
    for kind in ('report','collection_report','manuscript_export','layout_export','review_document_export'):
        order=[]
        def original():order.append('progress')
        def source(db,row,*,progress):
            assert progress is original
            order.append('source');progress();progress();return b'same'
        assert verify(SimpleNamespace(verify_source=source),None,{'source_kind':kind},original)==b'same'
        assert order==['source','progress','progress','progress']


@pytest.mark.parametrize('failure_at',['entry','chunk','source','exit'])
def test_errors_are_propagated_without_finally_overriding_them(monkeypatch,failure_at):
    execution,verify=verifier()
    from app.adapters.task_execution_store import LeaseLost
    from app.core.exceptions import StorageError
    clock=[0.0];calls=[];visited=[]
    monkeypatch.setattr(execution,'monotonic',lambda:clock[0])
    error=StorageError('source_conflict','fixture',409) if failure_at=='source' else LeaseLost()
    def original():
        calls.append(clock[0])
        if (failure_at=='entry' and len(calls)==1 or
                failure_at=='chunk' and clock[0]==1 or failure_at=='exit' and len(calls)==2):raise error
    def source(db,row,*,progress):
        visited.append(True)
        if failure_at=='source':raise error
        if failure_at=='chunk':clock[0]=1
        progress();return b'same'
    with pytest.raises(type(error)) as caught:
        verify(SimpleNamespace(verify_source=source),None,{'source_kind':'research_report'},original)
    assert caught.value is error
    assert len(calls)==(1 if failure_at in ('entry','source') else 2)
    assert bool(visited)==(failure_at!='entry')


def claimed_report(client, key):
    from app.adapters.task_execution_store import TaskExecutionStore
    base,source=selected_cell(client)
    finding=client.post(base+'/research-findings',json=dict(title='PDF progress fixture',sources=[source]),headers={'Idempotency-Key':key+'-finding'}).json()
    response=client.post(base+'/research-reports',json=dict(title='PDF progress fixture',finding_version_id=finding['id']),headers={'Idempotency-Key':key+'-report'})
    assert response.status_code==201,response.text
    report=response.json();repository=TaskExecutionStore()
    lease=repository.claim(report['task_id'],report['task']['revision'],task_type='research_report')
    return repository,lease


@pytest.mark.parametrize('mutation',['expired','owner_changed'])
def test_real_original_progress_rejects_expired_or_replaced_lease_at_exit(client,monkeypatch,mutation):
    execution,verify=verifier()
    from app.adapters.task_execution_store import LeaseLost
    repository,lease=claimed_report(client,'pdf-progress-'+mutation)
    monkeypatch.setattr(execution,'monotonic',lambda:0)
    with repository.connection(write=True) as db:
        original=repository.transaction_progress(db,lease)
        def source(db,row,*,progress):
            for _ in range(1000):progress()
            if mutation=='expired':db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s",(lease.task_id,))
            else:db.execute("UPDATE task_attempts SET lease_owner='different-worker' WHERE task_id=%s",(lease.task_id,))
            return b'bytes'
        with pytest.raises(LeaseLost):verify(SimpleNamespace(verify_source=source),db,{'source_kind':'research_report'},original)


@pytest.mark.parametrize('expire_before_quota',[False,True])
def test_original_publication_renewed_and_quota_rollback_are_preserved(client,monkeypatch,expire_before_quota):
    execution,verify=verifier()
    from app.adapters import task_execution_store
    from app.adapters.task_execution_store import LeaseLost
    from app.core.exceptions import StorageError
    from app.domain.tasks.publication_transaction import publication_transaction,PublicationFailed
    repository,lease=claimed_report(client,'pdf-progress-quota')
    if expire_before_quota:monkeypatch.setattr(task_execution_store,'LEASE_SECONDS',1)
    monkeypatch.setattr(execution,'monotonic',lambda:0)
    granted=[];restores=[]
    with pytest.raises(LeaseLost if expire_before_quota else PublicationFailed):
        with publication_transaction(repository,lease) as (db,original):
            execute=db.execute
            def observed(sql,parameters=()):
                if sql.startswith('UPDATE task_attempts a SET heartbeat_at=%s'):restores.append(parameters[:2])
                return execute(sql,parameters)
            monkeypatch.setattr(db,'execute',observed)
            def source(db,row,*,progress):
                for _ in range(1000):progress()
                return b'bytes'
            assert verify(SimpleNamespace(verify_source=source),db,{'source_kind':'research_report'},original)==b'bytes'
            row=db.execute('SELECT heartbeat_at,lease_expires_at FROM task_attempts WHERE task_id=%s AND attempt_no=%s',(lease.task_id,lease.attempt_no)).fetchone()
            assert original.renewed==dict(row)
            granted.append((row['heartbeat_at'],row['lease_expires_at']))
            if expire_before_quota:time.sleep(1.1)
            raise StorageError('storage_quota_exceeded','fixture quota',409)
    assert restores==granted
