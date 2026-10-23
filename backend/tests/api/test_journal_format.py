"""Offline guide/target/check boundaries and fixed public task execution."""
import pytest
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_journals import setup, profile, request, post
from app.db.database import database_connection


def candidate(client):
    base=setup(client)
    p=post(client,base+'/profiles',profile(),'profile').json()
    response=post(client,base+'/recommendations',request(),'recommendation')
    assert response.status_code==202,response.text
    r=response.json()
    from app.domain.tasks.execution import run_task
    assert run_task(r['task']['id'],1)['status']=='succeeded'
    return base,p,r


def guide(p,**changes):
    return dict(profile_id=p['id'],name='synthetic guide',source_type='synthetic',source_text='Maximum body words: 3000; count: en_whitespace_body\nRequired sections: Introduction | Methods | Results | Discussion\nAbstract required: yes\nMaximum abstract words: 250; count: en_whitespace_abstract\nMaximum figures: 5\nMaximum tables: 5\nFigure captions: required\nTable captions: required\nFigure numbering: required\nTable numbering: required\nFigure references: required\nTable references: required\nReference style: NLM\nMinimum DPI: 300',source_url='https://journal.example.test/guide',source_version='2026-v1',acquired_on='2026-10-23',verified_on='2026-10-23',article_types=['research'],conditions='synthetic engineering only',permission='user supplied synthetic',permission_status='allowed')|changes


def target(p,r,g,**changes):
    return dict(recommendation_id=r['id'],profile_id=p['id'],guide_id=g['id'],requirements_version=g['requirements_version'],article_type='research')|changes


def test_guide_extract_reject_forgery_synthetic_upgrade_and_idempotency(client):
    base,p,r=candidate(client)
    response=post(client,base+'/guides',guide(p),'guide')
    assert response.status_code==201,response.text
    g=response.json()
    assert g['synthetic'] is True and g['requirements_version']
    assert next(i for i in g['requirements'] if i['key']=='word_limit')['value']==3000
    assert all(i['quote'] and i['location'] for i in g['requirements'])
    assert post(client,base+'/guides',guide(p),'guide').json()==g
    assert post(client,base+'/guides',guide(p,source_version='changed'),'guide').status_code==409
    forged=guide(p,requirements=[dict(id='fake',key='word_limit',value=2,status='known',quote='fabricated',location='line:1')])
    assert post(client,base+'/guides',forged,'forged').status_code==422
    assert post(client,base+'/guides',guide(p,source_type='official_local'),'upgrade').status_code==422
    assert client.get(base+'/guides/'+g['id']).json()==g


def test_target_pins_candidate_guide_and_keeps_unknown_permission(client):
    base,p,r=candidate(client)
    response=post(client,base+'/guides',guide(p,permission_status='unknown'),'guide')
    assert response.status_code==201,response.text
    g=response.json()
    response=post(client,base+'/targets',target(p,r,g),'target')
    assert response.status_code==201,response.text
    t=response.json()
    assert t['warnings'] and t['guide']['id']==g['id']
    assert t['confirmed_by'] and t['confirmed_at']
    newer=post(client,base+'/guides',guide(p,previous_version_id=g['id'],source_version='v2'),'v2')
    assert newer.status_code==201,newer.text
    assert client.get(base+'/targets/'+t['id']).json()==t
    assert post(client,base+'/targets',target(p,r,g,article_type='review'),'article').status_code==422
    other=setup(client)
    assert client.get(other+'/guides/'+g['id']).status_code==404
    assert post(client,other+'/targets',target(p,r,g),'foreign').status_code==404


def manuscript(client):
    from tests.api.test_manuscripts import body,setup as ms_setup
    path,_,_=ms_setup(client)
    m=post(client,path,body(),'manuscript').json()
    from app.domain.tasks.execution import run_task
    assert run_task(m['versions'][0]['task_id'],1)['status']=='succeeded'
    return path,m


def test_check_requires_explicit_published_version_runs_public_task_and_no_writes(client):
    path,m=manuscript(client)
    base=path.removesuffix('/manuscripts')+'/journals'
    p=post(client,base+'/profiles',profile(),'profile').json()
    r=post(client,base+'/recommendations',request(),'recommendation').json()
    from app.domain.tasks.execution import run_task
    run_task(r['task']['id'],1)
    resp=post(client,base+'/guides',guide(p),'guide')
    assert resp.status_code==201,resp.text
    g=resp.json();t=post(client,base+'/targets',target(p,r,g),'target').json()
    assert post(client,base+'/checks',dict(target_id=t['id']),'missing').status_code==422
    body=dict(target_id=t['id'],manuscript=dict(id=m['id'],revision=1),check_version=1)
    response=post(client,base+'/checks',body,'check')
    assert response.status_code==202,response.text
    c=response.json()
    assert c['task']['task_type']=='journal_format_check'
    assert c['input_snapshot']['manuscript']['revision']==1
    with database_connection() as db:
        before=db.execute('SELECT count(*) n FROM manuscript_versions').fetchone()['n']
        ledger=db.execute('SELECT count(*) n FROM model_calls').fetchone()['n']
    assert run_task(c['task']['id'],1)['status']=='succeeded'
    saved=client.get(base+'/checks/'+c['id']).json()
    assert {i['category'] for i in saved['result']['items']}=={'length','sections','abstract','illustrations','references'}
    assert any(i['status']=='mismatch' for i in saved['result']['items'] if i['key']=='abstract_required')
    assert any(i['status'] in ('manual','unsupported') for i in saved['result']['items'] if i['key']=='dpi')
    for item in saved['result']['items']:
        assert {'actual','expected','location','evidence','suggested_action','future_automation'}<=item.keys()
    assert post(client,base+'/checks',body,'check').json()==saved
    assert client.get('/api/v1/tasks/'+c['task']['id']).json()['input_version']['kind']=='journal_format_check'
    assert client.get('/api/v1/tasks/'+c['task']['id']+'/workspace').status_code==200
    assert client.get('/api/v1/tasks/'+c['task']['id']+'/events').status_code==200
    project=base.split('/projects/')[1].split('/')[0]
    listing=client.get('/api/v1/projects/'+project+'/tasks',params={'task_type':'journal_format_check'})
    assert listing.status_code==200,listing.text
    assert listing.json()['items'][0]['task']['id']==c['task']['id']
    assert client.get(base+'/checks').json()['items'][0]['id']==c['id']
    with database_connection() as db:
        assert db.execute('SELECT count(*) n FROM manuscript_versions').fetchone()['n']==before
        assert db.execute('SELECT count(*) n FROM model_calls').fetchone()['n']==ledger


def test_guide_manual_correction_needs_matching_location_and_preserves_extraction(client):
    base,p,r=candidate(client)
    rule=dict(id='corrected',key='word_limit',value=3000,status='known',quote='Maximum body words: 3000; count: en_whitespace_body',location='line:999',count_method='en_whitespace_body',note='manual confirmation')
    assert post(client,base+'/guides',guide(p,requirements=[rule]),'wrong-line').status_code==422
    rule['location']='line:1'
    response=post(client,base+'/guides',guide(p,requirements=[rule]),'corrected')
    assert response.status_code==201,response.text
    g=response.json()
    assert g['extracted_requirements'][0]['key']=='word_limit'
    assert next(i for i in g['requirements'] if i['key']=='word_limit')['id']=='corrected'
    rule.update(key='abstract_required',value=False,quote='Abstract required: yes',location='line:3')
    assert post(client,base+'/guides',guide(p,requirements=[rule]),'inverted').status_code==422
    rule.update(value=True,location='line:1')
    assert post(client,base+'/guides',guide(p,requirements=[rule]),'wrong-leading-line').status_code==422


def test_target_cross_guide_conflicts_specific_precedence_and_defer(client):
    base,p,r=candidate(client)
    g1=post(client,base+'/guides',guide(p,source_text='Maximum body words: 3000; count: en_whitespace_body\n[research] Maximum body words: 2000; count: en_whitespace_body'),'g1').json()
    g2=post(client,base+'/guides',guide(p,previous_version_id=g1['id'],source_version='v2',source_text='Maximum body words: 1500; count: en_whitespace_body'),'g2').json()
    response=post(client,base+'/targets',target(p,r,g1,additional_guide_ids=[g2['id']]),'conflict')
    assert response.status_code==201,response.text
    t=response.json()
    assert t['conflicts'][0]['key']=='word_limit'
    assert not any(i['key']=='word_limit' for i in t['selected_requirements'])
    assert t['decisions'][0]['evidence'][0]['quote']
    chosen=next(i for i in t['conflicts'][0]['requirements'] if i['source_id']==g2['id'])
    selected=post(client,base+'/targets',target(p,r,g1,additional_guide_ids=[g2['id']],resolutions=[dict(key='word_limit',requirement_id=chosen['id'],reason='采用更严格版本')]),'selected').json()
    assert selected['selected_requirements'][0]['id']==chosen['id']
    deferred=post(client,base+'/targets',target(p,r,g1,resolutions=[dict(key='word_limit',requirement_id=None,reason='待核定计数')]),'defer').json()
    assert deferred['conflicts'][0]['deferred'] is True


def test_format_failure_retry_resume_fixed_old_manuscript_and_new_guide(client):
    path,m=manuscript(client);base=path.removesuffix('/manuscripts')+'/journals'
    p=post(client,base+'/profiles',profile(),'p').json()
    r=post(client,base+'/recommendations',request(),'r').json()
    from app.domain.tasks.execution import run_task
    run_task(r['task']['id'],1)
    g=post(client,base+'/guides',guide(p),'g').json()
    t=post(client,base+'/targets',target(p,r,g),'t').json()
    body=dict(target_id=t['id'],manuscript=dict(id=m['id'],revision=1))
    c=post(client,base+'/checks',body,'c').json()
    from app.domain.journals.format_execution import run_format_task
    def fail(snapshot):raise RuntimeError('synthetic interruption')
    failed=run_format_task(c['task']['id'],1,checker=fail)
    assert failed['status']=='failed'
    retried=client.post('/api/v1/tasks/'+failed['id']+'/retry',json={'expected_revision':failed['revision']})
    assert retried.status_code==202,retried.text
    failed=run_format_task(c['task']['id'],retried.json()['revision'],checker=fail)
    assert failed['status']=='failed'
    from tests.api.test_manuscripts import body as ms_body
    new=post(client,path+'/'+m['id']+'/versions',ms_body(expected_revision=1,title='new synthetic title'),'v2').json()
    newtask=next(v['task_id'] for v in new['versions'] if v['revision']==2)
    assert run_task(newtask,1)['status']=='succeeded'
    newer=post(client,base+'/guides',guide(p,previous_version_id=g['id'],source_version='v2',source_text='Maximum body words: 10; count: en_whitespace_body'),'g2')
    assert newer.status_code==201,newer.text
    resumed=post(client,'/api/v1/tasks/'+failed['id']+'/resume',dict(operation='retry',wait_id=None,expected_task_revision=failed['revision'],input_version=failed['input_version']),'resume')
    assert resumed.status_code==202,resumed.text
    assert run_task(failed['id'],resumed.json()['revision'])['status']=='succeeded'
    saved=client.get(base+'/checks/'+c['id']).json()
    assert saved['input_snapshot']==c['input_snapshot']
    assert saved['result']['guide_id']==g['id']
    assert saved['result']['manuscript_version_id']==c['input_snapshot']['manuscript']['version_id']
    assert run_task(failed['id'],resumed.json()['revision']) is None
    assert post(client,base+'/checks',body,'c').json()==saved


def test_unpublished_foreign_and_unusable_guide_rules_never_pass(client):
    from tests.api.test_manuscripts import body as ms_body,setup as ms_setup
    path,_,_=ms_setup(client);base=path.removesuffix('/manuscripts')+'/journals'
    m=post(client,path,ms_body(),'m').json()
    p=post(client,base+'/profiles',profile(),'p').json()
    r=post(client,base+'/recommendations',request(),'r').json()
    from app.domain.tasks.execution import run_task
    run_task(r['task']['id'],1)
    response=post(client,base+'/guides',guide(p,source_status='expired',permission_status='disallowed'),'g')
    assert response.status_code==201,response.text
    g=response.json();t=post(client,base+'/targets',target(p,r,g),'t').json()
    body=dict(target_id=t['id'],manuscript=dict(id=m['id'],revision=1))
    assert post(client,base+'/checks',body,'pending').status_code==409
    assert run_task(m['versions'][0]['task_id'],1)['status']=='succeeded'
    c=post(client,base+'/checks',body,'c').json()
    assert run_task(c['task']['id'],1)['status']=='succeeded'
    result=client.get(base+'/checks/'+c['id']).json()['result']
    assert not any(i['status']=='pass' for i in result['items'])
    assert all(i['status']=='pending_verification' for i in result['items'] if i['key']!='public_consistency' and i['id']!='unit_requirements')
    assert post(client,setup(client)+'/checks',body,'foreign').status_code==404
    from tests.integration.test_project_ownership import account_client
    with account_client('format-other@example.test')[0] as other:
        assert other.get(base+'/checks/'+c['id']).status_code==404
        assert other.get('/api/v1/tasks/'+c['task']['id']).status_code==404


def test_guide_public_material_lifecycle_and_dispatcher(client):
    from tests.api.test_manuscripts import body as ms_body,setup as ms_setup
    path,filebase,file=ms_setup(client);base=path.removesuffix('/manuscripts')+'/journals'
    m=post(client,path,ms_body(),'m').json()
    from app.domain.tasks.execution import run_task
    run_task(m['versions'][0]['task_id'],1)
    p=post(client,base+'/profiles',profile(),'p').json();r=post(client,base+'/recommendations',request(),'r').json()
    run_task(r['task']['id'],1)
    response=post(client,base+'/guides',guide(p,material=dict(kind='original',id=file['id'],file_id=file['id'])),'g')
    assert response.status_code==201,response.text
    g=response.json();t=post(client,base+'/targets',target(p,r,g),'t').json()
    c=post(client,base+'/checks',dict(target_id=t['id'],manuscript=dict(id=m['id'],revision=1)),'c').json()
    assessment=client.get(filebase+'/lifecycle/assessment')
    assert assessment.status_code==200,assessment.text
    assert assessment.json()['counts']['journal_material_refs']==1
    assert any(reason['code']=='journal_history_retained' for reason in assessment.json()['reasons'])
    from app.workers.dispatcher import dispatch_once
    messages=[]
    assert dispatch_once(publish=messages.append)>0
    message=next(msg for msg in messages if msg['task_id']==c['task']['id'])
    assert run_task(message['task_id'],message['task_revision'])['status']=='succeeded'
    from app.maintenance.database_audit import audit_database
    with database_connection() as db:report=audit_database(db)
    assert report['ok'],report['schema_issues'] or [c for c in report['data_checks'] if c['invalid']]


def test_format_worker_lost_lease_recovers_same_input_and_seals_publication(client):
    path,m=manuscript(client);base=path.removesuffix('/manuscripts')+'/journals'
    p=post(client,base+'/profiles',profile(),'p').json();r=post(client,base+'/recommendations',request(),'r').json()
    from app.domain.tasks.execution import run_task
    run_task(r['task']['id'],1)
    g=post(client,base+'/guides',guide(p),'g').json();t=post(client,base+'/targets',target(p,r,g),'t').json()
    c=post(client,base+'/checks',dict(target_id=t['id'],manuscript=dict(id=m['id'],revision=1)),'c').json()
    from app.domain.journals.format_execution import run_format_task
    from app.adapters.task_execution_store import TaskExecutionStore
    def expire(snapshot):
        with database_connection(write=True) as db:
            db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s",(c['task']['id'],))
        assert TaskExecutionStore().recover_expired()==1
        return dict(should_not_publish=True)
    assert run_format_task(c['task']['id'],1,checker=expire) is None
    current=client.get(base+'/checks/'+c['id']).json()
    assert current['result'] is None and current['input_snapshot']==c['input_snapshot']
    assert current['task']['status']=='queued'
    assert run_task(c['task']['id'],current['task']['revision'])['status']=='succeeded'
    import pytest
    from sqlalchemy.exc import SQLAlchemyError
    with pytest.raises(SQLAlchemyError):
        with database_connection(write=True) as db:db.execute("UPDATE journal_format_checks SET result_json='{}' WHERE id=%s",(c['id'],))
    with pytest.raises(SQLAlchemyError):
        with database_connection(write=True) as db:db.execute("UPDATE tasks SET input_snapshot=jsonb_set(input_snapshot,'{real_network_calls}','true') WHERE id=%s",(c['task']['id'],))
    with database_connection(write=True) as db:
        db.execute('UPDATE tasks SET input_digest=%s WHERE id=%s',('a'*64,c['task']['id']))
    from app.maintenance.journal_format_audit import audit_journal_formats
    with database_connection() as db:report=audit_journal_formats(db)
    assert next(item for item in report if item['table']=='journal_format_checks')['invalid']==1


def test_unstructured_requested_unit_requirement_is_retained_without_profile_claim(client):
    base=setup(client);body=profile();body['fields'].pop('unit_requirements')
    p=post(client,base+'/profiles',body,'p').json()
    r=post(client,base+'/recommendations',request(unit_requirements=['institutional condition'],hard_filters=['article_types','unit_requirements']),'r').json()
    from app.domain.tasks.execution import run_task
    assert run_task(r['task']['id'],1)['status']=='succeeded'
    g=post(client,base+'/guides',guide(p),'g').json()
    response=post(client,base+'/targets',target(p,r,g),'t')
    assert response.status_code==201,response.text
    warning=next(w for w in response.json()['warnings'] if w['key']=='unit_requirements')
    assert 'institutional condition' in str(warning['actual'])


@pytest.mark.parametrize('source,quote,count_method,article_type,extract',[
    ('Maximum body words: 3000','Maximum body words: 3000','en_whitespace_body',None,True),
    ('Maximum body words: 3000','Maximum body words: 3000','en_whitespace_body',None,False),
    ('Maximum body words: 3000; count: en_whitespace_body','Maximum body words: 3000; count: en_whitespace_body','zh_hanzi_latin_body',None,True),
    ('[review] Maximum body words: 3000','[review] Maximum body words: 3000',None,'research',True),
    ('[review] Maximum body words: 3000','Maximum body words: 3000',None,None,True),
])
def test_manual_requirement_cannot_upgrade_explicit_count_scope_or_article_type(client,source,quote,count_method,article_type,extract):
    base,p,_=candidate(client)
    rule=dict(id='manual',key='word_limit',value=3000,status='known',quote=quote,location='line:1',count_method=count_method,article_type=article_type,note='manual correction')
    response=post(client,base+'/guides',guide(p,source_text=source,requirements=[rule],extract=extract),'cannot-upgrade')
    assert response.status_code==422,response.text


def test_manual_unmatched_sentence_and_unknown_count_remain_available(client):
    base,p,_=candidate(client)
    for index,source in enumerate(['Maximum body words: 3000','Keep the main text within 3000 words.']):
        rule=dict(id='manual',key='word_limit',value=3000,status='known',quote=source,location='line:1',count_method=None,note='manual supplied requirement')
        response=post(client,base+'/guides',guide(p,source_text=source,requirements=[rule]),'manual-'+str(index))
        assert response.status_code==201,response.text
        assert response.json()['requirements'][0]['count_method'] is None
