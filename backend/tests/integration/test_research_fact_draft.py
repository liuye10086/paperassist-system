"""Published research facts reuse the existing synthetic science/language workflow."""
from tests.api.test_research_writing_handoff import client,prepared,publish_candidate
import pytest


@pytest.mark.parametrize('quota_denied',[False,True])
def test_research_docx_renews_lease_during_candidate_reconciliation(client,tmp_path,monkeypatch,quota_denied):
    import time
    from app.domain.manuscripts.execution import run_manuscript_task
    from app.adapters import task_execution_store
    from app.domain.storage_governance import service as storage
    base,deliveries,finding=prepared(client)
    result=publish_candidate(client,base,dict(delivery_id=deliveries['sci_draft'],finding_version_ids=[finding['id']]),tmp_path)
    root=base+'/manuscripts/'+result['manuscript_id']
    response=client.post(root+'/versions/1/exports',json={},headers={'Idempotency-Key':'slow-docx'})
    assert response.status_code==201,response.text
    exported=response.json();task=client.get('/api/v1/tasks/'+exported['task_id']).json()
    original=storage.reconcile_intents;calls=[]
    def delayed(db,directory,*,progress=None):
        calls.append(True)
        if len(calls)==2:
            for _ in range(8):
                time.sleep(.3)
                if progress is not None:progress()
            if quota_denied:
                from app.core.exceptions import StorageError
                raise StorageError('storage_quota_exceeded','Synthetic quota rejection after a long scan',409)
        return original(db,directory,progress=progress)
    monkeypatch.setattr(storage,'reconcile_intents',delayed)
    monkeypatch.setattr(task_execution_store,'LEASE_SECONDS',2)
    completed=run_manuscript_task(task['id'],task['revision'])
    if quota_denied:
        assert completed is not None and completed['status']=='failed'
        assert completed['error_code']=='storage_quota_exceeded'
        return
    assert completed is not None and completed['status']=='succeeded'
    metadata=client.get(root+'/exports/'+exported['id']).json()
    assert client.get(metadata['download_url']).status_code==200


def test_published_research_uses_controlled_synthetic_provider_and_review_publish(client,tmp_path):
    from tests.api.test_manuscript_writing_live import authorize,request_v2,LiveFixture,budgets
    from tests.api.test_manuscript_writing_live_review import decision
    from tests.api.test_manuscript_writing_language import approve
    from app.domain.manuscript_writing.execution import run_manuscript_writing_task
    from app.domain.tasks.execution import run_task
    base,deliveries,finding=prepared(client,title='External result facts')
    result=publish_candidate(client,base,dict(delivery_id=deliveries['sci_draft'],finding_version_ids=[finding['id']],output_language='en'),tmp_path)
    root=base+'/manuscripts/'+result['manuscript_id']
    response=client.post(root+'/writing-previews',json=dict(schema_version=2,base_revision=1,mode='full_draft',output_language='en',selected_source_ids=[finding['id']],selected_evidence_ids=[]),headers={'Idempotency-Key':'live-preview'})
    assert response.status_code==201,response.text
    bundle=response.json();_,authorization=authorize(client,root,bundle)
    response=client.post(root+'/writing-requests',json=request_v2(bundle,authorization),headers={'Idempotency-Key':'live-request'})
    assert response.status_code==202,response.text
    task=response.json()['task'];budgets(client,task);provider=LiveFixture()
    completed=run_manuscript_writing_task(task['id'],task['revision'],provider=provider)
    assert completed['status']=='succeeded',completed
    path=root+'/writing-requests/'+task['id'];context=client.get(path+'/review-context')
    assert context.status_code==200,context.text
    science=client.post(path+'/reviews',json=decision(context.json()),headers={'Idempotency-Key':'science'})
    assert science.status_code==201,science.text
    science=science.json();language_context=client.get(path+'/reviews/'+science['id']+'/language-context')
    assert language_context.status_code==200,language_context.text
    language=client.post(path+'/language-reviews',json=approve(language_context.json()),headers={'Idempotency-Key':'language'})
    assert language.status_code==201,language.text
    language=language.json()
    published=client.post(path+'/publish',json=dict(schema_version=2,expected_revision=1,review_id=science['id'],review_sha256=science['review_sha256'],language_review_id=language['id'],language_review_sha256=language['artifact_sha256']),headers={'Idempotency-Key':'publish-reviewed'})
    assert published.status_code==201,published.text
    version=published.json()['versions'][0]
    assert run_task(version['task_id'],1)['status']=='succeeded'
    assert client.get(root+'/versions/1').status_code==200
    from app.db.database import database_connection
    from app.maintenance.manuscript_audit import audit_manuscripts
    from app.maintenance.research_results_audit import audit_research_task_sources
    with database_connection() as db:
        checks=audit_manuscripts(db)+audit_research_task_sources(db)
        assert all(c['invalid']==0 for c in checks),checks
        assert db.execute('SELECT count(*) AS n FROM manuscript_research_sources').fetchone()['n']==2
    assert len(provider.posts)==1
    refreshed=publish_candidate(client,base,dict(delivery_id=deliveries['sci_draft'],finding_version_ids=[finding['id']],manuscript_id=result['manuscript_id'],base_version_id=version['id'],expected_revision=2,sections=['results']),tmp_path,'after-model')
    latest=client.get(root+'/versions/3').json()['snapshot']
    assert latest['sections'][2]==version['snapshot']['sections'][2]
    assert 'writing_provenance' not in latest
    assert client.get(root+'/reviews/context').status_code==200


def test_research_candidate_rejects_stale_worker_and_has_no_formal_manuscript(client,tmp_path):
    from app.domain.research_results.execution import run_research_task
    from app.domain.research_results.fact_draft import render_fact_draft
    from app.db.database import database_connection
    base,deliveries,finding=prepared(client)
    created=client.post(base+'/research-manuscript-candidates',json=dict(delivery_id=deliveries['sci_draft'],finding_version_ids=[finding['id']]),headers={'Idempotency-Key':'expired'}).json()
    def expired(payload,output):
        rendered=render_fact_draft(payload,output)
        with database_connection(write=True) as db:db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s",(created['task_id'],))
        return rendered
    assert run_research_task(created['task_id'],1,task_type='research_fact_draft',engine=expired,staging_directory=tmp_path/'stage') is None
    assert client.get(base+'/research-manuscript-candidates/'+created['id']).json()['candidate'] is None
    with database_connection() as db:assert db.execute('SELECT count(*) AS n FROM manuscripts').fetchone()['n']==0


@pytest.mark.parametrize('through_report,fmt',[(False,'png'),(True,'png'),(True,'tiff'),(True,'pdf'),(True,'svg')])
def test_research_figure_is_in_common_docx_with_exact_bytes(client,tmp_path,through_report,fmt):
    from tests.api.test_research_figure_publication import selected_image
    from tests.api.test_projects import upload
    from app.domain.research_results.execution import run_research_figure_task
    from app.adapters.research_figure_render import render_figure
    from app.domain.manuscripts.execution import run_manuscript_task
    from app.db.database import database_connection
    project,file=selected_image(client);base='/api/v1/projects/'+project
    figure=client.post(base+'/research-figures',json=dict(mode='reuse',panels=[dict(source=dict(source_kind='original_file',source_id=file))],formats=[fmt],caption='Fixed original figure'),headers={'Idempotency-Key':'figure'}).json()
    assert run_research_figure_task(figure['task_id'],1,engine=render_figure,staging_directory=tmp_path/'stage')['status']=='succeeded'
    source_file=upload(client,project).json()['file']
    finding=client.post(base+'/research-findings',json=dict(title='With figure',sources=[dict(source_kind='original_file',source_id=source_file['id'],locator=dict(kind='cell',sheet='研究数据',cell='B2'))]),headers={'Idempotency-Key':'finding'}).json()
    with database_connection() as db:delivery=db.execute("SELECT id FROM research_deliveries WHERE project_id=%s AND kind='sci_draft'",(project,)).fetchone()['id']
    selection=dict(delivery_id=delivery,finding_version_ids=[finding['id']],figure_version_ids=[figure['id']])
    if through_report:
        from app.domain.research_results.execution import run_research_report_task
        from app.adapters.research_report_render import render_report
        report=client.post(base+'/research-reports',json=dict(title='Report source',finding_version_id=finding['id'],figure_version_ids=[figure['id']]),headers={'Idempotency-Key':'report'}).json()
        assert run_research_report_task(report['task_id'],1,engine=render_report,staging_directory=tmp_path/'stage')['status']=='succeeded'
        selection=dict(delivery_id=delivery,report_version_ids=[report['id']])
    result=publish_candidate(client,base,selection,tmp_path)
    root=base+'/manuscripts/'+result['manuscript_id'];version=client.get(root+'/versions/1').json()
    assert len(version['snapshot']['results_groups'][0]['figures'])==1
    export=client.post(root+'/versions/1/exports',json={},headers={'Idempotency-Key':'docx'}).json()
    done=run_manuscript_task(export['task_id'],1)
    assert done['status']=='succeeded',done
    ready=client.get(root+'/exports/'+export['id']).json()
    raw=client.get(ready['download_url']).content
    from zipfile import ZipFile
    from io import BytesIO
    with ZipFile(BytesIO(raw)) as archive:assert any(n.startswith('word/media/') for n in archive.namelist())
    pdf=client.post(base+'/pdf-exports',json=dict(source_kind='manuscript_export',source_id=export['id'],request_key='research-manuscript-pdf'))
    assert pdf.status_code==201,pdf.text
