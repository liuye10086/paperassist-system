"""School manuscripts use shared services with separately frozen school provenance."""
from copy import deepcopy
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_school_templates import parsed, setup, post
from app.db.database import database_connection


def bound(client):
    path,template,item=parsed(client)
    chapters=[dict(id='school-intro',title='绪论',level=1),dict(id='school-methods',title='研究方法',level=1),dict(id='school-results',title='结果',level=1)]
    confirmed=post(client,path+'/school-templates/'+item['id']+'/confirm',dict(analysis_sha256=item['analysis_sha256'],decisions=[dict(conflict_id='conflict-1',option_id='text-2')],chapters=chapters)).json()
    profile=post(client,path+'/thesis-template-binding',dict(confirmation_id=confirmed['id'],expected_revision=0)).json()
    request=dict(title='合成研究',output_language='zh-CN',sources=[],thesis=dict(confirmation_id=confirmed['id'],profile_revision=profile['revision'],chapter_mappings=[dict(chapter_id=c['id'],purpose=p,output_language='project',result_group_ids=[]) for c,p in zip(chapters,['introduction','materials_and_methods','results'])]))
    return path,template,request


def test_readiness_and_separate_school_freeze(client):
    unbound,_=setup(client)
    readiness=client.get(unbound+'/manuscripts/config')
    assert readiness.status_code==200,readiness.text
    assert readiness.json()['thesis']['ready'] is False
    path,template,request=bound(client)
    config=client.get(path+'/manuscripts/config').json()
    assert config['project_type']=='thesis' and config['thesis']['ready']
    assert template['template_file_id'] in config['thesis']['template_source_file_ids']
    candidates=client.get(path+'/manuscripts/candidates').json()
    assert not any(s['file_id']==template['template_file_id'] for s in candidates['items'])
    preview=post(client,path+'/manuscripts/preview',request)
    assert preview.status_code==200,preview.text
    snap=preview.json()
    assert snap['thesis_context']['confirmation_id']==request['thesis']['confirmation_id']
    assert not snap['sources']
    assert [c['id'] for c in snap['sections']]==['school-intro','school-methods','school-results']
    mixed=deepcopy(request);mixed['sources']=[dict(kind='original',id=template['template_file_id'],file_id=template['template_file_id'],role='methods')]
    assert post(client,path+'/manuscripts/preview',mixed).status_code==422


def test_school_history_survives_profile_change_and_blocks_new_writing(client):
    from app.domain.tasks.execution import run_task
    path,_,request=bound(client)
    created=post(client,path+'/manuscripts',request,'school-create')
    assert created.status_code==201,created.text
    root=created.json();version=root['versions'][0]
    assert post(client,path+'/manuscripts',request,'school-create').json()==root
    with database_connection() as db:
        row=db.execute('SELECT school_confirmation_id FROM manuscript_versions WHERE id=%s',(version['id'],)).fetchone()
        assert row['school_confirmation_id']==request['thesis']['confirmation_id']
    run_task(version['task_id'],1)
    base=path+'/manuscripts/'+root['id']
    writing=post(client,base+'/writing-requests',dict(base_revision=1,mode='full_draft'),'school-writing')
    assert writing.status_code==202,writing.text
    run_task(writing.json()['id'],1)
    waited=client.get(base+'/writing-requests/'+writing.json()['id']).json()
    assert waited['task']['status']=='waiting_confirmation' and waited['candidate'] is None
    # This legacy synthetic analysis intentionally lacks any page section source.
    incomplete_export=post(client,base+'/versions/1/exports',{},'school-export')
    assert incomplete_export.status_code==422
    assert incomplete_export.json()['detail']['code']=='school_export_input_invalid'
    old=deepcopy(version['snapshot'])
    profile=client.get(path+'/thesis-profile').json()
    fields={k:profile[k] for k in ('school','department','major','degree_type','education_level','applicable_version')}
    assert client.put(path+'/thesis-profile',json=dict(expected_revision=profile['revision'],**(fields|dict(major='新专业')))).status_code==200
    history=client.get(base+'/versions/1')
    assert history.status_code==200,history.text
    assert history.json()['snapshot']==old and history.json()['current_changes']
    assert post(client,base+'/writing-requests',dict(base_revision=1,mode='full_draft'),'stale-writing').status_code==409
    assert post(client,path+'/manuscripts/preview',request).status_code==409


def test_foreign_binding_and_sci_school_input_are_rejected(client):
    path,_,request=bound(client)
    other,_=setup(client)
    assert post(client,other+'/manuscripts/preview',request).status_code in (404,409,422)
    sci=client.post('/api/v1/projects',json=dict(name='SCI',research_topic='synthetic',project_type='sci')).json()
    assert post(client,f'/api/v1/projects/{sci["id"]}/manuscripts/preview',request).status_code==422

def test_school_synthetic_candidate_and_review_publish_share_history(client):
    from app.domain.tasks.execution import run_task
    from app.domain.manuscript_writing.execution import run_manuscript_writing_task
    from tests.api.test_manuscript_writing_execution import WritingProvider,budgets
    path,_,request=bound(client)
    base=post(client,path+'/manuscripts',request,'create').json()
    run_task(base['versions'][0]['task_id'],1)
    endpoint=path+'/manuscripts/'+base['id']
    task=post(client,endpoint+'/writing-requests',dict(base_revision=1,mode='full_draft'),'write').json()['task']
    budgets(client,task)
    class SchoolProvider(WritingProvider):
        def receipt(self):
            import json
            receipt=super().receipt()
            content=receipt['response']['output'][0]['content'][0]
            sections=json.loads(content['text'])['sections']
            content['text']=json.dumps(dict(sections=[dict(id=s['id'],paragraphs=s['paragraphs']) for s in sections]))
            return receipt
    provider=SchoolProvider()
    result=run_manuscript_writing_task(task['id'],task['revision'],provider=provider)
    assert result['status']=='succeeded',result
    candidate=client.get(endpoint+'/writing-requests/'+task['id']).json()['candidate']
    assert candidate['writing_provenance']['provider_provenance']=='synthetic_fixture'
    assert client.get(endpoint).json()['current_revision']==1
    published=post(client,endpoint+'/writing-requests/'+task['id']+'/publish',dict(expected_revision=1),'publish')
    assert published.status_code==201,published.text
    version=published.json()['versions'][0]
    assert version['snapshot']==candidate
    assert run_task(version['task_id'],1)['status']=='succeeded'
    review=post(client,endpoint+'/reviews',dict(base_revision=2),'review')
    assert review.status_code==201,review.text
    report=review.json()['report']
    assert report['scientifically_verified'] is False
    reviewed=post(client,endpoint+'/reviews/'+review.json()['id']+'/publish',dict(expected_revision=2),'review-publish')
    assert reviewed.status_code==201,reviewed.text
    assert run_task(reviewed.json()['versions'][0]['task_id'],1)['status']=='succeeded'
    with database_connection() as db:
        versions=db.execute('SELECT school_confirmation_id FROM manuscript_versions WHERE manuscript_id=%s',(base['id'],)).fetchall()
        assert len(versions)==3 and all(v['school_confirmation_id']==request['thesis']['confirmation_id'] for v in versions)
    assert client.get(endpoint+'/versions/1').json()['snapshot']==base['versions'][0]['snapshot']
    from app.maintenance.database_audit import audit_database
    with database_connection() as db:audit=audit_database(db)
    assert audit['ok'],audit['schema_issues'] or [c for c in audit['data_checks'] if c['invalid']]


def test_school_v2_direct_request_is_rejected_before_bundle_lookup(client):
    from app.domain.tasks.execution import run_task
    path,_,request=bound(client)
    base=post(client,path+'/manuscripts',request,'create').json()
    run_task(base['versions'][0]['task_id'],1)
    response=post(client,path+'/manuscripts/'+base['id']+'/writing-requests',dict(schema_version=2,bundle_id='missing',bundle_sha256='a'*64,authorization_id='missing',logical_task_id='school'),'v2')
    assert response.status_code==422,response.text
    assert response.json()['detail']['code']=='manuscript_writing_not_authorized'

def test_school_uses_existing_offline_figure_language_service(client):
    from tests.api.test_manuscript_figure_language import uploaded
    path,_,request=bound(client);project=path.rsplit('/',1)[1]
    file=uploaded(client,project)
    body=dict(source=dict(kind='original',id=file['id'],file_id=file['id']),original_sha256=file['sha256'],mode='no_text_confirmation',output_language='zh-CN',reason='人工核对合成白图无文字',title='合成图',caption='合成观察')
    response=post(client,path+'/manuscript-figure-language-versions',body,'school-image')
    assert response.status_code==201,response.text
    image=response.json()
    assert client.get(image['download_url']).content.startswith(b'\x89PNG')
    assert any(s['kind']=='figure_language_version' and s['id']==image['id'] for s in client.get(path+'/manuscripts/candidates').json()['items'])

def test_invalid_school_mapping_is_422_and_owner_scope_is_private(client):
    from tests.integration.test_project_ownership import account_client
    path,_,request=bound(client)
    invalid=deepcopy(request)
    invalid['thesis']['chapter_mappings'][0]['purpose']='references'
    invalid['thesis']['chapter_mappings'][1]['purpose']='references'
    assert post(client,path+'/manuscripts/preview',invalid).status_code==422
    invalid=deepcopy(request);invalid['thesis']['chapter_mappings'].reverse()
    assert post(client,path+'/manuscripts/preview',invalid).status_code==422
    root=post(client,path+'/manuscripts',request,'private').json()
    with account_client('school-manuscript-other@example.test')[0] as other:
        assert other.get(path+'/manuscripts/'+root['id']).status_code==404
        assert other.get(path+'/manuscripts/config').status_code==404
        assert post(other,path+'/manuscripts/preview',request).status_code==404


def test_template_asset_change_keeps_history_and_fails_pending_publication(client):
    from app.domain.tasks.execution import run_task
    path,template,request=bound(client)
    root=post(client,path+'/manuscripts',request,'frozen').json()
    with database_connection(write=True) as db:
        db.execute('UPDATE files SET sha256=%s WHERE id=%s',('a'*64,template['template_file_id']))
    old=client.get(path+'/manuscripts/'+root['id'])
    assert old.status_code==200,old.text
    assert old.json()['versions'][0]['snapshot']==root['versions'][0]['snapshot']
    assert old.json()['versions'][0]['current_changes']
    config=client.get(path+'/manuscripts/config').json()
    assert config['thesis']['ready'] is False
    assert post(client,path+'/manuscripts',request,'changed').status_code==409
    result=run_task(root['versions'][0]['task_id'],1)
    assert result['status']=='failed',result
