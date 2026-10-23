"""Finite display adoption and append-only human submission history."""
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_journal_format import candidate, guide, target, post


def test_display_rule_explicit_unit_and_submission_corrections(client):
    base,p,r=candidate(client)
    rule=dict(id='body',key='body_font_size_pt',value=12,status='known',quote='Body font size: 12 pt',location='line:1')
    response=post(client,base+'/guides',guide(p,source_text=rule['quote'],requirements=[rule],extract=False),'g')
    assert response.status_code==201,response.text
    g=response.json();t=post(client,base+'/targets',target(p,r,g),'t').json()
    body=dict(target_id=t['id'],status='accepted',event_date='2026-10-22',note='synthetic user record')
    response=post(client,base+'/submission-events',body,'event')
    assert response.status_code==201,response.text
    event=response.json()
    correction=post(client,base+'/submission-events',body|dict(status='revision',event_date='2026-10-21',corrects_event_id=event['id']),'correction')
    assert correction.status_code==201,correction.text
    listing=client.get(base+'/submission-events').json()
    assert len(listing['items'])==2
    assert listing['current_by_target'][t['id']]['status']=='revision'
    assert post(client,base+'/submission-events',body,'event').json()==event
    rule['quote']='Body font size: 12'
    assert post(client,base+'/guides',guide(p,source_text=rule['quote'],requirements=[rule],extract=False),'bad-unit').status_code==422


def test_adaptation_requires_matching_successful_check(client):
    base,p,r=candidate(client)
    response=client.post(base+'/adaptations/preview',json=dict(target_id='absent',check_id='absent',manuscript=dict(id='absent',revision=1,version_id='absent')))
    assert response.status_code==404,response.text
    assert client.get(base+'/adaptations').status_code==200

def adaptation_ready(client,*,permission='allowed',fixture=None,real_guide=False):
    from tests.api.test_manuscript_review_v2_bridge import published
    from tests.api.test_journals import profile,request
    from app.domain.tasks.execution import run_task
    if fixture:root,version=fixture(client);science=language=None
    else:root,version,science,language=published(client)
    base=root.rsplit('/manuscripts/',1)[0]+'/journals'
    p=post(client,base+'/profiles',profile(**({'source_type':'user_provided'} if real_guide else {})),'p').json()
    r=post(client,base+'/recommendations',request(),'r').json();assert run_task(r['task']['id'],1)['status']=='succeeded'
    from app.domain.journals.display import defaults
    display=defaults(version['snapshot']);display['names']['abstract']='Summary'
    mapping=[dict(section_id=k,display_name=v) for k,v in display['names'].items()]
    quote='Display sections: '+' | '.join(i['section_id']+'='+i['display_name'] for i in mapping)
    order=[display['names'][k] for k in ('title','abstract','introduction','materials_and_methods','results','discussion','references')]
    order_quote='Section order: '+' | '.join(order)
    rules=[dict(id='names',key='section_display_names',value=mapping,status='known',quote=quote,location='line:1'),dict(id='order',key='section_order',value=order,status='known',quote=order_quote,location='line:2'),dict(id='body',key='body_font_size_pt',value=12,status='known',quote='Body font size: 12 pt',location='line:3'),dict(id='spacing',key='body_line_spacing',value=1.5,status='known',quote='Body line spacing: 1.5 multiple',location='line:4')]
    response=post(client,base+'/guides',guide(p,source_text='\n'.join(r['quote'] for r in rules),requirements=rules,extract=False,permission_status=permission,**({'source_type':'user_provided'} if real_guide else {})),'g');assert response.status_code==201,response.text
    g=response.json();t=post(client,base+'/targets',target(p,r,g),'t').json()
    fixed=dict(target_id=t['id'],manuscript=dict(id=root.rsplit('/',1)[1],revision=version['revision']))
    c=post(client,base+'/checks',fixed,'c').json();assert run_task(c['task']['id'],1)['status']=='succeeded'
    request=fixed|dict(check_id=c['id'],manuscript=fixed['manuscript']|dict(version_id=version['id']))
    return root,base,version,request,science,language

def test_v2_display_adaptation_old_parent_public_docx_and_idempotency(client):
    from app.domain.tasks.execution import run_task
    from app.db.database import database_connection
    from tests.api.test_manuscripts import body
    from io import BytesIO
    from docx import Document
    root,base,version,request,science,language=adaptation_ready(client)
    # Create a newer root version; adoption must still derive from the reviewed v2.
    newer=post(client,root+'/versions',body(expected_revision=2),'newer')
    assert newer.status_code==201,newer.text
    preview=client.post(base+'/adaptations/preview',json=request)
    assert preview.status_code==200,preview.text
    p=preview.json();assert len(p['sections'])==7 and len(p['actions'])==4
    adopt=request|dict(expected_current_revision=3,preview_sha256=p['preview_sha256'],selected_action_ids=[a['id'] for a in p['actions']])
    response=post(client,base+'/adaptations',adopt,'adopt');assert response.status_code==202,response.text
    a=response.json()
    assert client.get('/api/v1/tasks/'+a['task']['id']+'/workspace').status_code==200
    with database_connection() as db:before=db.execute('SELECT count(*) n FROM model_calls').fetchone()['n']
    task=run_task(a['task']['id'],1);assert task['status']=='succeeded',task
    result=client.get(base+'/adaptations/'+a['id']).json()['result'];output=result['output']
    assert output['revision']==4 and output['parent_version_id']==version['id']
    assert run_task(output['task_id'],1)['status']=='succeeded'
    saved=client.get(root+'/versions/4');assert saved.status_code==200,saved.text
    snapshot=saved.json()['snapshot']
    for key in ('sections','results_groups','sources','references','writing_provenance'):assert snapshot[key]==version['snapshot'][key]
    assert snapshot['results_groups'][0]['tables'] and science['review_sha256'] and language['artifact_sha256']
    export=post(client,root+'/versions/4/exports',{},'docx');assert export.status_code==201,export.text
    e=export.json();assert run_task(e['task_id'],1)['status']=='succeeded'
    exported=client.get(root+'/exports/'+e['id']).json()
    raw=client.get(exported['download_url']).content;doc=Document(BytesIO(raw))
    headings=[p.text for p in doc.paragraphs if p.style.name=='Heading 1']
    assert 'Summary' in headings and headings.index('Materials and methods')<headings.index('Results')
    assert doc.styles['Normal'].font.size.pt==12 and doc.styles['Normal'].paragraph_format.line_spacing==1.5
    checked=post(client,base+'/checks',dict(target_id=request['target_id'],manuscript=dict(id=output['manuscript_id'],revision=4)),'new-check').json()
    assert run_task(checked['task']['id'],1)['status']=='succeeded'
    report=client.get(base+'/checks/'+checked['id']).json()['result']
    assert report['display_version']=='journal_display_v1'
    assert all(i['status']=='pass' for i in report['items'] if i['key'] in ('section_order','section_display_names','body_font_size_pt','body_line_spacing'))
    assert post(client,base+'/adaptations',adopt,'adopt').status_code==200
    assert run_task(a['task']['id'],1) is None
    assert client.get(base+'/submission-events').json()['items']==[]
    with database_connection() as db:
        assert db.execute('SELECT count(*) n FROM model_calls').fetchone()['n']==before
        assert db.execute('SELECT count(*) n FROM manuscript_versions').fetchone()['n']==4

def test_unknown_permission_has_no_executable_actions(client):
    root,base,version,request,_,_=adaptation_ready(client,permission='unknown')
    response=client.post(base+'/adaptations/preview',json=request);assert response.status_code==200,response.text
    assert response.json()['actions']==[] and not response.json()['can_adopt']

def test_user_material_guide_does_not_upgrade_synthetic_manuscript(client):
    root,base,version,request,_,_=adaptation_ready(client,real_guide=True)
    assert client.get(base+'/targets/'+request['target_id']).json()['synthetic'] is False
    check=client.get(base+'/checks/'+request['check_id']).json()
    assert check['input_snapshot']['synthetic'] is True and check['result']['synthetic'] is True
    preview=client.post(base+'/adaptations/preview',json=request).json()
    assert preview['synthetic'] is True

def test_nonempty_figures_numeric_tables_and_citation_bindings_preserved(client):
    from tests.helpers.journal_adaptation import nonempty_published
    from app.domain.tasks.execution import run_task
    from app.db.database import database_connection
    from app.maintenance.database_audit import audit_database
    from zipfile import ZipFile
    from io import BytesIO
    root,base,version,request,_,_=adaptation_ready(client,fixture=nonempty_published)
    response=client.post(base+'/adaptations/preview',json=request);assert response.status_code==200,response.text
    p=response.json();adopt=request|dict(expected_current_revision=version['revision'],preview_sha256=p['preview_sha256'],selected_action_ids=[a['id'] for a in p['actions']])
    response=post(client,base+'/adaptations',adopt,'nonempty');assert response.status_code==202,response.text
    a=response.json();task=run_task(a['task']['id'],1);assert task['status']=='succeeded',task
    result=client.get(base+'/adaptations/'+a['id']).json()['result'];o=result['output'];assert run_task(o['task_id'],1)['status']=='succeeded'
    output=client.get(root+'/versions/'+str(o['revision'])).json()['snapshot']
    for key in ('sources','sections','results_groups','references','citation_snapshot'):assert output[key]==version['snapshot'][key]
    assert not [i for i in result['public_issues'] if i['severity']=='error']
    e=post(client,root+'/versions/'+str(o['revision'])+'/exports',{},'nonempty-docx').json();assert run_task(e['task_id'],1)['status']=='succeeded'
    raw=client.get(client.get(root+'/exports/'+e['id']).json()['download_url']).content
    with ZipFile(BytesIO(raw)) as z:assert any(n.startswith('word/media/') for n in z.namelist())
    with database_connection() as db:report=audit_database(db)
    assert report['ok'],report['schema_issues'] or [c for c in report['data_checks'] if c['invalid']]

def test_failure_retry_keeps_input_and_concurrent_revision_blocks_publication(client):
    from app.domain.journals.adaptation_execution import run_adaptation_task
    from app.domain.tasks.execution import run_task
    from tests.api.test_manuscripts import body
    root,base,version,request,_,_=adaptation_ready(client)
    p=client.post(base+'/adaptations/preview',json=request).json()
    body_adopt=request|dict(expected_current_revision=2,preview_sha256=p['preview_sha256'],selected_action_ids=[a['id'] for a in p['actions']])
    a=post(client,base+'/adaptations',body_adopt,'fail').json()
    def fail():raise RuntimeError('synthetic interruption before publication')
    result=run_adaptation_task(a['task']['id'],1,before_publish=fail);assert result['status']=='failed'
    assert client.get(root).json()['current_revision']==2
    retry=post(client,'/api/v1/tasks/'+a['task']['id']+'/resume',dict(operation='retry',wait_id=None,expected_task_revision=result['revision'],input_version=result['input_version']),'resume');assert retry.status_code==202,retry.text
    assert client.get(base+'/adaptations/'+a['id']).json()['input_snapshot']==a['input_snapshot']
    def concurrent():
        response=post(client,root+'/versions',body(expected_revision=2),'concurrent');assert response.status_code==201,response.text
    retried=client.get('/api/v1/tasks/'+a['task']['id']).json()
    result=run_adaptation_task(a['task']['id'],retried['revision'],before_publish=concurrent)
    assert result['status']=='failed' and result['error_code']=='manuscript_revision_conflict',result
    assert client.get(root).json()['current_revision']==3
    assert client.get(base+'/submission-events').json()['items']==[]

def test_tasks_do_not_write_progress_and_summary_uses_same_latest_target(client):
    from app.domain.tasks.execution import run_task
    root,base,version,request,_,_=adaptation_ready(client)
    event=post(client,base+'/submission-events',dict(target_id=request['target_id'],status='submitted',event_date='2026-10-23',note='Explicit user record'),'submit').json()
    p=client.post(base+'/adaptations/preview',json=request).json()
    a=post(client,base+'/adaptations',request|dict(expected_current_revision=2,preview_sha256=p['preview_sha256'],selected_action_ids=[i['id'] for i in p['actions']]),'adopt').json()
    assert run_task(a['task']['id'],1)['status']=='succeeded'
    assert client.get(base+'/submission-events').json()['current_by_target'][request['target_id']]==event
    summary=client.get(base.removesuffix('/journals')+'/summary');assert summary.status_code==200,summary.text
    assert summary.json()['journal']['progress']==event
    old=client.get(base+'/targets/'+request['target_id']).json()
    next_target=post(client,base+'/targets',{k:old[k] for k in ('recommendation_id','profile_id','guide_id','requirements_version','article_type')},'target2').json()
    summary=client.get(base.removesuffix('/journals')+'/summary').json()['journal']
    assert summary['target_id']==next_target['id'] and summary['progress'] is None

def test_hard_numeric_source_citation_errors_never_publish(client,monkeypatch):
    from app.domain.tasks.execution import run_task
    import app.domain.journals.adaptation_service as service
    root,base,version,request,_,_=adaptation_ready(client)
    p=client.post(base+'/adaptations/preview',json=request).json()
    body=request|dict(expected_current_revision=2,preview_sha256=p['preview_sha256'],selected_action_ids=[a['id'] for a in p['actions']])
    original=service.apply
    for fault in ('numeric','source','citation'):
        def broken(snapshot,actions):
            candidate=original(snapshot,actions);paragraph=next(s for s in candidate['sections'] if s['id']=='results')['paragraphs'][0]
            if fault=='numeric':paragraph['text']='n = 999; mean = 999'
            if fault=='source':paragraph['source_ids']=['missing-source']
            if fault=='citation':paragraph['citations']=[dict(project_reference_id='fabricated',review_id='fabricated',metadata_version_id='fabricated')]
            return candidate
        with monkeypatch.context() as patch:
            patch.setattr(service,'apply',broken)
            a=post(client,base+'/adaptations',body,'fault-'+fault).json()
            failed=run_task(a['task']['id'],1)
            assert failed['status']=='failed' and failed['error_code']=='manuscript_review_blocked',failed
            saved=client.get(base+'/adaptations/'+a['id']).json()
            assert saved['validation']['can_publish'] is False and saved['result'] is None
        assert client.get(root).json()['current_revision']==2
    assert client.get(base+'/submission-events').json()['items']==[]

def test_adaptation_lease_fence_dispatcher_and_owner_isolation(client):
    from app.db.database import database_connection
    from app.domain.journals.adaptation_execution import run_adaptation_task
    from app.domain.tasks.execution import run_task
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.workers.dispatcher import dispatch_once
    from tests.integration.test_project_ownership import account_client
    root,base,version,request,_,_=adaptation_ready(client)
    p=client.post(base+'/adaptations/preview',json=request).json()
    a=post(client,base+'/adaptations',request|dict(expected_current_revision=2,preview_sha256=p['preview_sha256'],selected_action_ids=[i['id'] for i in p['actions']]),'lease').json()
    messages=[];assert dispatch_once(publish=messages.append)>0
    assert any(m['task_id']==a['task']['id'] for m in messages)
    def expire():
        with database_connection(write=True) as db:db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s",(a['task']['id'],))
    assert run_adaptation_task(a['task']['id'],1,before_publish=expire) is None
    assert client.get(root).json()['current_revision']==2
    TaskExecutionStore().recover_expired()
    task=client.get('/api/v1/tasks/'+a['task']['id']).json();assert run_task(task['id'],task['revision'])['status']=='succeeded'
    assert client.get(root).json()['current_revision']==3
    with account_client('adaptation-other@example.test')[0] as other:
        assert other.get(base+'/adaptations/'+a['id']).status_code==404
        assert other.get(base+'/submission-events').status_code==404
        assert other.post(base+'/adaptations/preview',json=request).status_code==404
    assert client.get('/api/v1/tasks/'+a['task']['id']+'/events').status_code==200

def test_lease_expiry_inside_publication_rolls_back_version_result_and_success(client,monkeypatch):
    from app.db.database import database_connection
    from app.domain.manuscripts.service import ManuscriptService
    from app.domain.journals.adaptation_execution import run_adaptation_task
    root,base,version,request,_,_=adaptation_ready(client)
    p=client.post(base+'/adaptations/preview',json=request).json()
    a=post(client,base+'/adaptations',request|dict(expected_current_revision=2,preview_sha256=p['preview_sha256'],selected_action_ids=[i['id'] for i in p['actions']]),'late-lease').json()
    publish=ManuscriptService.publish_journal_adaptation
    def expire_after_publication(self,db,*args,**kwargs):
        result=publish(self,db,*args,**kwargs)
        db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s",(a['task']['id'],))
        return result
    monkeypatch.setattr(ManuscriptService,'publish_journal_adaptation',expire_after_publication)
    with database_connection() as db:
        before_versions=db.execute('SELECT count(*) AS n FROM manuscript_versions').fetchone()['n']
        before_tasks=db.execute('SELECT count(*) AS n FROM tasks').fetchone()['n']
    assert run_adaptation_task(a['task']['id'],1) is None
    assert client.get(root).json()['current_revision']==2
    assert client.get(base+'/adaptations/'+a['id']).json()['result'] is None
    assert client.get('/api/v1/tasks/'+a['task']['id']).json()['status']=='running'
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM manuscript_versions').fetchone()['n']==before_versions
        assert db.execute('SELECT count(*) AS n FROM tasks').fetchone()['n']==before_tasks


def test_public_docx_pdf_failures_retry_fixed_output_without_new_manuscript(client,monkeypatch):
    from app.domain.tasks.execution import run_task
    from app.core.exceptions import StorageError
    from types import SimpleNamespace
    root,base,version,request,_,_=adaptation_ready(client)
    p=client.post(base+'/adaptations/preview',json=request).json()
    a=post(client,base+'/adaptations',request|dict(expected_current_revision=2,preview_sha256=p['preview_sha256'],selected_action_ids=[i['id'] for i in p['actions']]),'adopt').json()
    assert run_task(a['task']['id'],1)['status']=='succeeded'
    output=client.get(base+'/adaptations/'+a['id']).json()['result']['output'];assert run_task(output['task_id'],1)['status']=='succeeded'
    e=post(client,root+'/versions/3/exports',{},'docx').json()
    def bad_docx(*args,**kwargs):raise StorageError('report_render_failed','Synthetic local render failure',422)
    with monkeypatch.context() as patch:
        patch.setattr('app.adapters.manuscript_docx.build_manuscript_docx',bad_docx)
        failed=run_task(e['task_id'],1);assert failed['status']=='failed'
    retry=client.post('/api/v1/tasks/'+e['task_id']+'/retry',json=dict(expected_revision=failed['revision']));assert retry.status_code==202,retry.text
    assert run_task(e['task_id'],retry.json()['revision'])['status']=='succeeded'
    pdfpath=base.removesuffix('/journals')+'/pdf-exports'
    monkeypatch.setattr('app.domain.pdf_exports.service.renderer_identity',lambda:dict(contract='synthetic-pdf-v1'))
    monkeypatch.setattr('app.domain.pdf_exports.execution.renderer_identity',lambda:dict(contract='synthetic-pdf-v1'))
    response=client.post(pdfpath,json=dict(source_kind='manuscript_export',source_id=e['id'],request_key='pdf'));assert response.status_code==201,response.text
    pdf=response.json()
    def timeout(raw):raise StorageError('pdf_conversion_timeout','Synthetic timeout',422)
    monkeypatch.setattr('app.domain.pdf_exports.execution.render_pdf',timeout)
    failed=run_task(pdf['task_id'],1);assert failed['status']=='failed' and failed['error_code']=='pdf_conversion_timeout',failed
    response=client.post(pdfpath+'/'+pdf['id']+'/retry',json=dict(request_key='pdf-retry'));assert response.status_code==201,response.text
    retried=response.json();assert retried['source_id']==e['id'] and retried['source_sha256']==pdf['source_sha256']
    monkeypatch.setattr('app.domain.pdf_exports.execution.render_pdf',lambda raw:SimpleNamespace(content=b'%PDF-1.7\nsynthetic contract only',manifest=dict(contract='synthetic-pdf-v1')))
    assert run_task(retried['task_id'],1)['status']=='succeeded'
    assert client.get(root).json()['current_revision']==3
    assert client.get(base+'/submission-events').json()['items']==[]
