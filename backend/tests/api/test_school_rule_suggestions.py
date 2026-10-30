"""Synthetic school advice uses real isolated task and immutable confirmation rows."""
import json
from uuid import uuid4
import pytest
from tests.api.test_school_templates import client, setup, post
from tests.adapters.test_school_front_matter import synthetic
from app.domain.school_templates.execution import run_school_template_task
from app.db.database import database_connection

@pytest.fixture(autouse=True)
def no_real_school_processing(monkeypatch):monkeypatch.setenv('PAPERASSIST_SCHOOL_RULE_MODEL_ENABLED','0')

def analyzed(client,variant='A'):
    path,request=setup(client)
    request['supplement_text']='正文：小四号字。签名须人工填写。'
    response=post(client,path+'/school-templates',request,'base');assert response.status_code==202,response.text
    created=response.json()
    assert run_school_template_task(created['task']['id'],1,parser=lambda *a:synthetic(label='SYNTHETIC '+variant,size=18 if variant=='A' else 14))['status']=='succeeded'
    item=client.get(path+'/school-templates').json()['items'][0]
    return path,item

def test_identity_note_preview_and_creation_are_rejected_without_task_or_call_and_legacy_advice_still_reads(client,monkeypatch):
    path,item=analyzed(client)
    identity_note=next(n for n in item['analysis']['notes'] if n['text']=='作者签名：示例签名')
    base=path+'/school-templates/'+item['id']
    with database_connection() as db:
        before=dict(tasks=db.execute('SELECT count(*) AS n FROM tasks').fetchone()['n'],calls=db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'])
    request=dict(analysis_sha256=item['analysis_sha256'],note_ids=[identity_note['id']])
    preview=post(client,base+'/rule-suggestion-preview',request,'identity-preview')
    assert preview.status_code==422,preview.text
    created=post(client,base+'/rule-suggestions',dict(**request,bundle_sha256='a'*64,confirmed=True),'identity-create')
    assert created.status_code==422,created.text
    with database_connection() as db:
        after=dict(tasks=db.execute('SELECT count(*) AS n FROM tasks').fetchone()['n'],calls=db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'])
    assert before==after
    assert identity_note['id'] not in item['rule_suggestion_note_eligibility']['eligible_note_ids']
    assert dict(note_id=identity_note['id'],reason_code='identity_source') in item['rule_suggestion_note_eligibility']['blocked_notes']
    # Existing frozen suggestions are read from their old immutable snapshot,
    # independently of the new request's material-selection guard.
    with monkeypatch.context() as legacy:
        legacy.setattr('app.domain.school_templates.suggestion_eligibility.note_eligibility',lambda analysis,*args:dict(eligible_note_ids=[n['id'] for n in analysis['notes']],blocked_notes=[]))
        preview=post(client,base+'/rule-suggestion-preview',request,'legacy-preview').json()
        saved=post(client,base+'/rule-suggestions',dict(**request,bundle_sha256=preview['bundle_sha256'],confirmed=True),'legacy-request').json()
    from tests.integration.test_literature_assistance import budgets
    from app.domain.school_templates.suggestion_execution import run_school_suggestion_task
    budgets(client,saved['task']);note=preview['material']['notes'][0]
    provider=Fixture(dict(candidates=[dict(id='legacy',target_id=None,value=None,note_alias=note['alias'],start=0,end=len(note['text']),quote=note['text'],status='unknown',reason='Retained legacy synthetic output; never adopted.')]))
    assert run_school_suggestion_task(saved['task']['id'],1,provider=provider)['status']=='succeeded'
    historical=client.get(path+'/school-rule-suggestions/'+saved['id']).json()
    def new_material_rejected(*args,**kwargs):raise ValueError('new request policy rejected')
    monkeypatch.setattr('app.domain.school_templates.suggestion_service.material',new_material_rejected)
    assert client.get(path+'/school-rule-suggestions/'+saved['id']).json()==historical
    assert client.get(base+'/rule-suggestions').status_code==200
    assert len(provider.posts)==1 and historical['result']['candidates'][0]['quote']==identity_note['text']

class Fixture:
    source_kind='synthetic_fixture'
    def __init__(self,draft,unknown=False):self.draft=draft;self.posts=[];self.gets=[];self.unknown=unknown;self.pending=False;self.response_id='resp_school_'+uuid4().hex
    def create(self,**options):
        self.posts.append(options)
        if self.unknown:raise TimeoutError()
        return self.receipt()
    def retrieve(self,response_id,**options):self.gets.append(response_id);return self.receipt()
    def receipt(self):
        status='in_progress' if self.pending else 'completed'
        return dict(response_id=self.response_id,request_id='synthetic',model='gpt-6.1-sol',status=status,usage=dict(input_tokens=20,output_tokens=20),
            response=dict(status=status,output=[dict(type='message',content=[dict(type='output_text',text=json.dumps(self.draft))])]))

def create(client,path,item):
    note=next(n for n in item['analysis']['notes'] if '正文：小四号字。' in n['text'])
    base=path+'/school-templates/'+item['id'];request=dict(analysis_sha256=item['analysis_sha256'],note_ids=[note['id']])
    response=post(client,base+'/rule-suggestion-preview',request,'preview')
    assert response.status_code==200,response.text
    preview=response.json();request.update(bundle_sha256=preview['bundle_sha256'],confirmed=True)
    response=post(client,base+'/rule-suggestions',request,'suggestion');assert response.status_code==202,response.text
    return base,request,preview,response.json()

@pytest.mark.parametrize('variant',['A','B'])
def test_school_advice_preview_synthetic_task_human_confirmation_and_binding(client,variant):
    path,item=analyzed(client,variant);base,request,preview,suggestion=create(client,path,item)
    assert preview['real_calls_enabled'] is False
    assert 'file_id' not in json.dumps(preview['material']) and 'word/document.xml' not in json.dumps(preview['material'])
    from tests.integration.test_literature_assistance import budgets
    budgets(client,suggestion['task'])
    from app.domain.school_templates.suggestion_execution import run_school_suggestion_task
    note=preview['material']['notes'][0]
    draft=dict(candidates=[dict(id='r1',target_id='body.font_size_pt',value='12',note_alias=note['alias'],start=0,end=len(note['text']),quote=note['text'],status='proposed',reason='Synthetic candidate; quote existence is not semantic correctness.')])
    provider=Fixture(draft)
    assert run_school_suggestion_task(suggestion['task']['id'],1,provider=provider)['status']=='succeeded'
    assert len(provider.posts)==1
    result=client.get(path+'/school-rule-suggestions/'+suggestion['id']);assert result.status_code==200,result.text
    result=result.json();assert result['model_calls'][0]['provider_provenance']=='synthetic_fixture'
    assert client.get(base.rsplit('/school-templates/',1)[0]+'/school-templates').json()['items'][0]['analysis']==item['analysis']
    assert post(client,base+'/rule-suggestions',request,'suggestion').json()==result
    assert client.get('/api/v1/tasks/'+suggestion['task']['id']+'/workspace').status_code==200
    confirmation=dict(schema_version=2,analysis_sha256=item['analysis_sha256'],chapters=[{k:c[k] for k in ('id','title','level')} for c in item['analysis']['chapters']],
        decisions=[dict(conflict_id=c['id'],option_id=c['options'][0]['id']) for c in item['analysis']['conflicts']],
        suggestion_id=result['id'],suggestion_artifact_sha256=result['artifact_sha256'],suggestion_decisions=[])
    assert post(client,base+'/confirm',confirmation,'missing').status_code==422
    confirmation['suggestion_decisions']=[dict(candidate_id='r1',action='accept',reason='Human explicitly checked the source and interpretation.')]
    response=post(client,base+'/confirm',confirmation,'confirm-v2');assert response.status_code==201,response.text
    saved=response.json();assert any(r['id']=='body.font_size_pt' and r['value']==12 for r in saved['rules'])
    assert post(client,base+'/confirm',confirmation,'confirm-v2').json()==saved
    assert post(client,path+'/thesis-template-binding',dict(confirmation_id=saved['id'],expected_revision=0),'bind').status_code==200
    assert post(client,base+'/confirm',confirmation,'replace').status_code==409
    fork=post(client,base+'/fork',{},'fork');assert fork.status_code==202,fork.text
    assert fork.json()['previous_version_id']==item['id'] and fork.json()['confirmation'] is None
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM school_rule_suggestions').fetchone()['n']==1
    with pytest.raises(Exception):
        with database_connection(write=True) as db:db.execute('UPDATE school_rule_suggestions SET result_json=result_json WHERE id=%s',(result['id'],))
    from app.maintenance.database_audit import audit_database
    with database_connection() as db:
        audit=audit_database(db)
        assert audit['ok'],audit['schema_issues'] or [c for c in audit['data_checks'] if c['invalid']]
    file_id=item['sources'][0]['file_id']
    response=client.get(path+'/files/'+file_id+'/lifecycle/assessment');assert response.status_code==200,response.text
    assert response.json()['counts']['school_rule_suggestions']==1
    assert response.json()['physical_deletion_available'] is False

def draft_for(preview,status='proposed'):
    note=preview['material']['notes'][0]
    return dict(candidates=[dict(id='r1',target_id='body.font_size_pt' if status=='proposed' else None,value='12' if status=='proposed' else None,
        note_alias=note['alias'],start=0,end=len(note['text']),quote=note['text'],status=status,reason='Synthetic advice; manual interpretation required.')])

def test_closed_and_missing_budget_paths_have_zero_posts_then_budget_resume_is_scoped(client):
    path,item=analyzed(client);_,_,preview,suggestion=create(client,path,item)
    from app.domain.school_templates.suggestion_execution import run_school_suggestion_task
    waiting=run_school_suggestion_task(suggestion['task']['id'],1)
    assert waiting['status']=='waiting_confirmation'
    with database_connection() as db:assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']==0
    workspace=client.get('/api/v1/tasks/'+waiting['id']+'/workspace').json()
    resume=dict(operation='resume',wait_id=workspace['wait']['id'],expected_task_revision=waiting['revision'],input_version=waiting['input_version'])
    response=post(client,'/api/v1/tasks/'+waiting['id']+'/resume',resume,'resume-closed');assert response.status_code==202,response.text
    provider=Fixture(draft_for(preview))
    waiting=run_school_suggestion_task(waiting['id'],response.json()['revision'],provider=provider)
    assert waiting['reason_code']=='budget_exceeded' and provider.posts==[]
    workspace=client.get('/api/v1/tasks/'+waiting['id']+'/workspace').json()
    from tests.integration.test_literature_assistance import budgets
    budgets(client,waiting)
    resume.update(wait_id=workspace['wait']['id'],expected_task_revision=waiting['revision'])
    response=post(client,'/api/v1/tasks/'+waiting['id']+'/resume',resume,'resume-budget');assert response.status_code==202,response.text
    assert run_school_suggestion_task(waiting['id'],response.json()['revision'],provider=provider)['status']=='succeeded'
    assert len(provider.posts)==1

def test_unknown_submission_never_reposts_and_known_response_continues_by_get(client):
    path,item=analyzed(client);base,_,preview,suggestion=create(client,path,item)
    from app.domain.school_templates.suggestion_execution import run_school_suggestion_task
    from tests.integration.test_literature_assistance import budgets
    budgets(client,suggestion['task']);provider=Fixture(draft_for(preview),unknown=True)
    waiting=run_school_suggestion_task(suggestion['task']['id'],1,provider=provider)
    assert waiting['reason_code']=='submission_unknown' and len(provider.posts)==1
    assert client.get('/api/v1/tasks/'+waiting['id']+'/workspace').json()['allowed_actions']==[]
    assert post(client,'/api/v1/tasks/'+waiting['id']+'/retry',dict(expected_revision=waiting['revision']),'unknown-retry').status_code==409
    assert run_school_suggestion_task(waiting['id'],waiting['revision'],provider=provider) is None
    assert len(provider.posts)==1
    request=dict(analysis_sha256=item['analysis_sha256'],note_ids=[n['id'] for n in preview['notes']],bundle_sha256=preview['bundle_sha256'],confirmed=True)
    next_task=post(client,base+'/rule-suggestions',request,'second-call').json()['task']
    from app.domain.model_usage.service import ModelUsageService
    from tests.helpers.tasks import task_owner
    ModelUsageService(task_owner(client)).set_budget('task',next_task['id'],5000000,0)
    pending=Fixture(draft_for(preview));pending.pending=True
    deferred=run_school_suggestion_task(next_task['id'],1,provider=pending)
    assert deferred['status']=='running'
    pending.pending=False
    assert run_school_suggestion_task(next_task['id'],deferred['revision'],provider=pending)['status']=='succeeded'
    assert len(pending.posts)==1 and pending.gets==[pending.response_id]

def test_invalid_output_is_retained_and_cannot_be_adopted_or_read_by_foreign_owner(client):
    path,item=analyzed(client);_,_,preview,suggestion=create(client,path,item)
    from tests.integration.test_literature_assistance import budgets
    from app.domain.school_templates.suggestion_execution import run_school_suggestion_task
    budgets(client,suggestion['task']);draft=draft_for(preview);draft['candidates'][0]['quote']='Invented quote'
    result=run_school_suggestion_task(suggestion['task']['id'],1,provider=Fixture(draft))
    assert result['status']=='failed' and result['error_code']=='model_response_invalid'
    advice=client.get(path+'/school-rule-suggestions/'+suggestion['id']).json()
    assert advice['result']['validation_status']=='invalid' and advice['artifact_sha256']
    with database_connection() as db:
        row=db.execute('SELECT raw_output_json FROM school_rule_suggestions WHERE id=%s',(suggestion['id'],)).fetchone()
        assert row['raw_output_json']['invalid_response']
    from tests.integration.test_project_ownership import account_client
    with account_client('school-suggestion-other@example.test')[0] as other:
        assert other.get(path+'/school-rule-suggestions/'+suggestion['id']).status_code==404
