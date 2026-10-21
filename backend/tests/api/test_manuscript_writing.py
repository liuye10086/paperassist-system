from tests.api.test_manuscripts import client,setup,body
from tests.api.test_literature_evidence import post
from app.domain.tasks.execution import run_task

def test_writing_requires_published_base_and_freezes_idempotently(client):
    path,_,_=setup(client)
    draft=post(client,path,body(),'base').json();mid=draft['id'];version=draft['versions'][0]
    endpoint=path+'/'+mid+'/writing-requests'
    request=dict(base_revision=1,mode='full_draft',instructions='Synthetic offline draft',keywords=['Synthetic'],acknowledgements='')
    assert post(client,endpoint,request,'writing').status_code==409
    run_task(version['task_id'],1)
    response=post(client,endpoint,request,'writing')
    assert response.status_code==202,response.text
    view=response.json()
    assert view['candidate'] is None and view['base_revision']==1
    assert view['task']['task_type']=='manuscript_writing'
    assert post(client,endpoint,request,'writing').json()==view
    assert post(client,endpoint,request|dict(instructions='Changed'),'writing').status_code==409
    assert client.get(endpoint).json()['items'][0]['id']==view['id']
    assert post(client,endpoint+'/'+view['id']+'/publish',dict(expected_revision=1),'publish').status_code==409

def candidate_ready(client):
    from app.db.database import database_connection
    from app.domain.manuscript_writing.context import compose_candidate
    from app.domain.literature.service import digest
    from psycopg.types.json import Jsonb
    path,_,_=setup(client);base=post(client,path,body(),'base').json();version=base['versions'][0]
    run_task(version['task_id'],1)
    endpoint=path+'/'+base['id']+'/writing-requests'
    view=post(client,endpoint,dict(base_revision=1,mode='full_draft',instructions='Synthetic full draft'),'write').json()
    with database_connection(write=True) as db:
        task=db.execute('SELECT * FROM tasks WHERE id=%s',(view['id'],)).fetchone()
        from app.domain.manuscript_writing.context import normalize_sections
        sections=normalize_sections(task['input_snapshot']['base_snapshot'])
        for section in sections:
            if section['id'] not in ('title','references'):
                section['paragraphs']=[dict(id='writing:'+section['id']+':one',text='Missing study facts require review.',source_ids=[],citations=[],numeric_bindings=[])]
        candidate=compose_candidate(dict(sections=sections),task['input_snapshot'])
        db.execute('UPDATE manuscript_writing_requests SET candidate_json=%s,candidate_sha256=%s WHERE task_id=%s',(Jsonb(candidate),digest(candidate),view['id']))
        db.execute("UPDATE tasks SET status='succeeded' WHERE id=%s",(view['id'],))
    return path,base,endpoint,view,candidate


def test_explicit_publish_preserves_history_and_uses_existing_publication(client):
    path,base,endpoint,view,candidate=candidate_ready(client)
    publish=endpoint+'/'+view['id']+'/publish'
    response=post(client,publish,dict(expected_revision=1),'publish')
    assert response.status_code==201,response.text
    root=response.json();assert root['current_revision']==2
    assert root['versions'][1]['snapshot']==base['versions'][0]['snapshot']
    assert root['versions'][0]['snapshot']==candidate
    assert root['versions'][0]['status']=='pending'
    run_task(root['versions'][0]['task_id'],1)
    assert client.get(path+'/'+base['id']).json()['versions'][0]['status']=='published'
    assert post(client,publish,dict(expected_revision=1),'publish').status_code==200
    assert post(client,publish,dict(expected_revision=1),'other-key').status_code==409
    export=post(client,path+'/'+base['id']+'/versions/2/exports',{},'docx').json()
    assert run_task(export['task_id'],1)['status']=='succeeded'


def test_candidate_cannot_publish_after_new_version(client):
    path,base,endpoint,view,_=candidate_ready(client)
    assert post(client,path+'/'+base['id']+'/versions',body(expected_revision=1),'newer').status_code==201
    assert post(client,endpoint+'/'+view['id']+'/publish',dict(expected_revision=1),'publish').status_code==409


def test_cross_owner_writing_is_private(client):
    from tests.integration.test_project_ownership import account_client
    path,base,endpoint,view,_=candidate_ready(client)
    with account_client('writing-other@example.test')[0] as other:
        assert other.get(endpoint).status_code==404
        assert other.get(endpoint+'/'+view['id']).status_code==404
        assert post(other,endpoint,dict(base_revision=1,mode='full_draft'),'other').status_code==404
        assert post(other,endpoint+'/'+view['id']+'/publish',dict(expected_revision=1),'pub').status_code==404

def test_writing_audit_detects_candidate_binding_tampering(client):
    from app.db.database import database_connection
    from app.maintenance.manuscript_writing_audit import audit_manuscript_writing
    path,base,endpoint,view,_=candidate_ready(client)
    with database_connection() as db: assert all(c['invalid']==0 for c in audit_manuscript_writing(db))
    with database_connection(write=True) as db: db.execute("UPDATE manuscript_writing_requests SET candidate_sha256=%s WHERE task_id=%s",('a'*64,view['id']))
    with database_connection() as db: assert any(c['invalid'] for c in audit_manuscript_writing(db))
    assert client.get(endpoint+'/'+view['id']).status_code==409

def test_global_audit_accepts_waiting_failed_and_successful_synthetic_writing(client):
    from tests.api.test_manuscript_writing_execution import create,WritingProvider,budgets
    from app.domain.manuscript_writing.execution import run_manuscript_writing_task
    from app.db.database import database_connection
    from app.maintenance.database_audit import audit_database
    class UniqueProvider(WritingProvider):
        def receipt(self):
            result=super().receipt()
            result['response_id']='resp_'+self.payload['input']['instructions'].replace(' ','_')+'_'+self.identity
            result['response']['id']=result['response_id']
            return result
    for mode in ('waiting','failed','succeeded'):
        task,_=create(client)
        if mode=='waiting': result=run_manuscript_writing_task(task['id'],task['revision'])
        else:
            from app.domain.model_usage.service import ModelUsageService
            with database_connection() as db:
                user=db.execute('SELECT user_id FROM tasks WHERE id=%s',(task['id'],)).fetchone()['user_id']
            usage=ModelUsageService(user)
            for scope,key in (('user',user),('project',task['project_id']),('task',task['id'])):
                with usage.store.connection() as db: current=usage.store.budget(db,scope,key)
                usage.set_budget(scope,key,5000000,current['revision'] if current else 0)
            provider=UniqueProvider(invalid=mode=='failed');provider.identity=task['id']
            result=run_manuscript_writing_task(task['id'],task['revision'],provider=provider)
        assert result['status']==dict(waiting='waiting_confirmation',failed='failed',succeeded='succeeded')[mode],result
    with database_connection() as db:
        audit=audit_database(db)
        assert audit['ok'],audit['schema_issues'] or [c for c in audit['data_checks'] if c['invalid']]

def test_rewrite_requires_existing_complete_manuscript(client):
    path,_,_=setup(client);base=post(client,path,body(),'base').json();run_task(base['versions'][0]['task_id'],1)
    endpoint=path+'/'+base['id']+'/writing-requests'
    response=post(client,endpoint,dict(base_revision=1,mode='rewrite_section',target_section='discussion'),'rewrite')
    assert response.status_code==409,response.text

def test_rewrite_of_complete_version_preserves_other_sections_and_historical_versions(client):
    from app.db.database import database_connection
    from app.domain.manuscript_writing.context import compose_candidate
    from app.domain.literature.service import digest
    from psycopg.types.json import Jsonb
    path,base,endpoint,view,candidate=candidate_ready(client)
    full=post(client,endpoint+'/'+view['id']+'/publish',dict(expected_revision=1),'full-publish').json()
    assert run_task(full['versions'][0]['task_id'],1)['status']=='succeeded'
    response=post(client,endpoint,dict(base_revision=2,mode='rewrite_section',target_section='discussion',instructions='Rewrite only discussion'),'rewrite')
    assert response.status_code==202,response.text
    writing=response.json()
    with database_connection(write=True) as db:
        task=db.execute('SELECT * FROM tasks WHERE id=%s',(writing['id'],)).fetchone()
        rewritten=compose_candidate(dict(sections=[dict(id='discussion',paragraphs=[dict(id='writing:discussion:one',text='Missing discussion facts require verification.',source_ids=[],citations=[],numeric_bindings=[])])]),task['input_snapshot'])
        assert [s for s in rewritten['sections'] if s['id']!='discussion']==[s for s in candidate['sections'] if s['id']!='discussion']
        assert all(rewritten[k]==candidate[k] for k in ('methods','results_groups','sources','citation_snapshot','references','issues'))
        db.execute('UPDATE manuscript_writing_requests SET candidate_json=%s,candidate_sha256=%s WHERE task_id=%s',(Jsonb(rewritten),digest(rewritten),writing['id']))
        db.execute("UPDATE tasks SET status='succeeded' WHERE id=%s",(writing['id'],))
    third=post(client,endpoint+'/'+writing['id']+'/publish',dict(expected_revision=2),'rewrite-publish')
    assert third.status_code==201,third.text
    root=third.json();assert root['versions'][1]['snapshot']==candidate
    assert root['versions'][2]['snapshot']==base['versions'][0]['snapshot']
