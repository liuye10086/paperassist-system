"""Source verification renews only live leases during a writer transaction."""
import time
import pytest
from tests.api.test_research_findings import client,selected_cell


@pytest.mark.parametrize('expire_one_read',[False,True])
def test_report_freeze_renews_between_sources_without_reviving_expiry(client,tmp_path,monkeypatch,expire_one_read):
    from app.adapters.task_execution_store import TaskExecutionStore,LeaseLost
    from app.adapters import task_execution_store
    from app.domain.research_results.execution import ResearchExecution
    from app.domain.research_results.sources import ResearchSourceReader
    base,source=selected_cell(client)
    sources=[{**source,'locator':{**source['locator'],'cell':'B'+str(i)}} for i in range(2,6)]
    finding=client.post(base+'/research-findings',json=dict(title='Bounded source checks',sources=sources),headers={'Idempotency-Key':'progress-finding'}).json()
    created=client.post(base+'/research-reports',json=dict(title='Lease progress',finding_version_id=finding['id']),headers={'Idempotency-Key':'progress-report'})
    assert created.status_code==201,created.text
    report=created.json();repository=TaskExecutionStore()
    monkeypatch.setattr(task_execution_store,'LEASE_SECONDS',1)
    lease=repository.claim(report['task_id'],report['task']['revision'],task_type='research_report')
    original=ResearchSourceReader._original;calls=[]
    def slow(self,db,project,selection):
        calls.append(selection.source_id)
        time.sleep(1.2 if expire_one_read and len(calls)==1 else .3)
        return original(self,db,project,selection)
    monkeypatch.setattr(ResearchSourceReader,'_original',slow)
    execution=ResearchExecution(repository,tmp_path/'stage')
    started=time.monotonic()
    if expire_one_read:
        with pytest.raises(LeaseLost):
            with repository.connection(write=True) as db:execution.checked(db,lease)
        with repository.connection() as db:
            with pytest.raises(LeaseLost):repository.require_lease(db,lease)
    else:
        with repository.connection(write=True) as db:
            execution.checked(db,lease)
            assert time.monotonic()-started>1
            assert len(calls)>=4
            assert repository.require_lease(db,lease)['status']=='running'




@pytest.mark.parametrize('code,status',[('research_source_conflict',409),('file_missing',410)])
def test_slow_source_rejection_is_committed_without_reaper_requeue(client,tmp_path,monkeypatch,code,status):
    from app.adapters import task_execution_store
    from app.adapters.research_report_render import render_report
    from app.adapters.research_results_store import invalid
    from app.domain.research_results.execution import run_research_report_task
    from app.domain.research_results.sources import ResearchSourceReader
    from app.db.database import database_connection
    base,source=selected_cell(client)
    sources=[{**source,'locator':{**source['locator'],'cell':'B'+str(i)}} for i in range(2,6)]
    finding=client.post(base+'/research-findings',json=dict(title='Source rejection',sources=sources),headers={'Idempotency-Key':'reject-finding'}).json()
    report=client.post(base+'/research-reports',json=dict(title='Rejected report',finding_version_id=finding['id']),headers={'Idempotency-Key':'reject-report'}).json()
    original=ResearchSourceReader._original;rendered=[];reads=[]
    def engine(payload,output):
        result=render_report(payload,output);rendered.append(True);return result
    def slow(self,db,project,selection):
        if rendered:
            reads.append(selection.source_id);time.sleep(.3)
            if len(reads)==4:raise invalid(code,status)
        return original(self,db,project,selection)
    monkeypatch.setattr(ResearchSourceReader,'_original',slow)
    monkeypatch.setattr(task_execution_store,'LEASE_SECONDS',1)
    result=run_research_report_task(report['task_id'],1,engine=engine,staging_directory=tmp_path/'stage')
    assert result is not None and result['status']=='failed'
    assert result['error_code']==code
    task_execution_store.TaskExecutionStore().recover_expired()
    with database_connection() as db:
        task=db.execute('SELECT status,current_attempt,error_code FROM tasks WHERE id=%s',(report['task_id'],)).fetchone()
        assert dict(task)==dict(status='failed',current_attempt=1,error_code=code)
        assert not db.execute('SELECT 1 FROM research_report_members WHERE report_version_id=%s',(report['id'],)).fetchone()
        assert not db.execute("SELECT 1 FROM task_events WHERE task_id=%s AND event_type='requeued'",(report['task_id'],)).fetchone()
