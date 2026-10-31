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


def test_report_freeze_keeps_lease_through_included_pdf_source_closure(client,tmp_path,monkeypatch):
    from types import SimpleNamespace
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.adapters import task_execution_store
    from app.adapters.research_objects import ResearchObjects
    from app.adapters.research_report_render import render_report
    from app.domain.research_results.execution import ResearchExecution,run_research_report_task
    from app.domain.pdf_exports.service import PdfExportService
    from app.domain.pdf_exports.execution import run_pdf_task
    base,source=selected_cell(client)
    finding=client.post(base+'/research-findings',json=dict(title='PDF facts',sources=[source]),headers={'Idempotency-Key':'pdf-progress-finding'}).json()
    body=dict(title='PDF package',finding_version_id=finding['id'])
    report=client.post(base+'/research-reports',json=body,headers={'Idempotency-Key':'pdf-progress-report'}).json()
    assert run_research_report_task(report['task_id'],1,engine=render_report,staging_directory=tmp_path/'stage')['status']=='succeeded'
    saved=client.get(base+'/research-reports/'+report['id']).json()
    docx=next(m for m in saved['members'] if m['role']=='docx')
    identity={'contract':'test-source-progress-v1'}
    monkeypatch.setattr('app.domain.pdf_exports.service.renderer_identity',lambda:identity)
    monkeypatch.setattr('app.domain.pdf_exports.execution.renderer_identity',lambda:identity)
    monkeypatch.setattr('app.domain.pdf_exports.execution.render_pdf',lambda raw:SimpleNamespace(content=b'%PDF-1.7\nsynthetic',manifest=identity))
    pdf=client.post(base+'/pdf-exports',json=dict(source_kind='research_report',source_id=docx['id'],request_key='progress-pdf')).json()
    assert run_pdf_task(pdf['task_id'],1)['status']=='succeeded'
    packaged=client.post(base+'/research-reports',json={**body,'root_id':report['root_id'],'expected_revision':1,'include_pdf_id':pdf['id']},headers={'Idempotency-Key':'progress-package'})
    assert packaged.status_code==201,packaged.text
    packaged=packaged.json();repository=TaskExecutionStore()
    monkeypatch.setattr(task_execution_store,'LEASE_SECONDS',1)
    lease=repository.claim(packaged['task_id'],1,task_type='research_report')
    original_download=PdfExportService.download;original_read=ResearchObjects.read;inside=[];reads=[]
    def download(self,*args,**kwargs):
        inside.append(True)
        try:return original_download(self,*args,**kwargs)
        finally:inside.pop()
    def slow_read(self,record):
        if inside:
            reads.append(record['sha256']);time.sleep(.3)
        return original_read(self,record)
    monkeypatch.setattr(PdfExportService,'download',download)
    monkeypatch.setattr(ResearchObjects,'read',slow_read)
    with repository.connection(write=True) as db:
        ResearchExecution(repository,tmp_path/'stage').checked(db,lease)
        assert len(reads)>4
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
