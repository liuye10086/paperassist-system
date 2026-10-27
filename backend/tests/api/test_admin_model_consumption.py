"""Configuration consumption with synthetic providers, never external transport."""
from copy import deepcopy
import json
import pytest
from app.db.database import database_connection
from tests.api.test_admin_configurations import accounts, admin, baseline, saved, validated, switch, ROOT
from tests.api.test_manuscript_writing_live import client, preview, authorize, request_v2, LiveFixture
from tests.api.test_literature_evidence import post
from tests.integration.test_literature_assistance import budgets
from app.domain.manuscript_writing.execution import run_manuscript_writing_task


def test_old_bundle_authorization_and_fake_post_keep_price_instruction_and_caps(admin,client):
    one=baseline(admin)
    one=saved(admin,one,'prompts','writing_instruction','Use concise sentences.')
    validated(admin,one);assert switch(admin,one,0,'one').status_code==200
    root,bundle=preview(client)
    assert 'Use concise sentences.' in json.loads(bundle['wire_json'])['instructions']
    two_body=deepcopy(one['bundle'])
    two_body['prompts']['writing_instruction']='Use short paragraphs.'
    two_body['models']['writing']['execution']['policy']['price']['version']='synthetic-v2'
    two_body['models']['writing']['execution']['policy']['price']['output_micro_usd_per_million']=1000000
    two_body['models']['writing']['execution']['task_limit_micro_usd']=2000000
    two_body['models']['max_corrections']=0
    response=admin.post(ROOT+'/'+one['id']+'/save',json={'bundle':two_body});assert response.status_code==201
    two=response.json();validated(admin,two);assert switch(admin,two,1,'two').status_code==200
    assert client.get(root+'/writing-previews/'+bundle['id']).json()==bundle
    _,auth=authorize(client,root,bundle)
    assert auth['manifest']['logical_task_cap_micro_usd']==3000000
    assert auth['manifest']['max_corrections']==2
    response=post(client,root+'/writing-requests',request_v2(bundle,auth),'old-execute')
    assert response.status_code==202,response.text
    task=response.json()['task']
    from app.domain.model_usage.service import ModelUsageService
    from tests.helpers.tasks import task_owner
    service=ModelUsageService(task_owner(client))
    for scope,key in [('user',task_owner(client)),('project',task['project_id'])]:service.set_budget(scope,key,5000000,0)
    provider=LiveFixture()
    assert run_manuscript_writing_task(task['id'],task['revision'],provider=provider)['status']=='succeeded'
    assert provider.posts==[bundle['wire_json']]
    newer=post(client,root+'/writing-previews',bundle['request_json'],'new-preview').json()
    assert 'Use short paragraphs.' in json.loads(newer['wire_json'])['instructions']
    assert newer['policy_json']['price']['version']=='synthetic-v2'
    assert client.get(root+'/writing-previews').json()['capabilities']['logical_task_cap_micro_usd']==2000000
    authorization_path=root.split('/manuscripts/')[0]+'/writing-authorizations'
    authorization_request=dict(schema_version=2,confirmed=True,tasks=[dict(logical_task_id='task-'+str(i),bundles=[dict(bundle_id=newer['id'],bundle_sha256=newer['bundle_sha256'])]) for i in range(4)])
    authorization_response=post(client,authorization_path,authorization_request,'new-authorization')
    assert authorization_response.status_code==201,authorization_response.text
    new_auth=authorization_response.json()
    assert new_auth['manifest']['max_corrections']==0 and new_auth['manifest']['logical_task_cap_micro_usd']==2000000
    next_response=post(client,root+'/writing-requests',request_v2(newer,new_auth),'new-execute')
    assert next_response.status_code==202,next_response.text
    next_task=next_response.json()['task'];next_provider=LiveFixture()
    assert run_manuscript_writing_task(next_task['id'],next_task['revision'],provider=next_provider)['status']=='succeeded'
    assert next_provider.posts==[newer['wire_json']]
    with database_connection() as db:
        call=db.execute('SELECT price_snapshot FROM model_calls WHERE task_id=%s',(task['id'],)).fetchone()
        assert call['price_snapshot']==bundle['policy_json']['price']
        binding=db.execute("SELECT version_id FROM admin_configuration_bindings WHERE kind='task' AND object_id=%s",(task['id'],)).fetchone()
        assert binding['version_id']==one['id']
        next_call=db.execute('SELECT price_snapshot FROM model_calls WHERE task_id=%s',(next_task['id'],)).fetchone()
        assert next_call['price_snapshot']==newer['policy_json']['price'] and next_call['price_snapshot']!=call['price_snapshot']
    assert switch(admin,one,2,'back','rollback').status_code==200
    after=post(client,root+'/writing-previews',bundle['request_json'],'rollback-preview').json()
    assert after['wire_json']==bundle['wire_json']


def test_literature_fixed_provider_changes_fail_before_activation(admin):
    one=baseline(admin);body=deepcopy(one['bundle'])
    body['models']['literature']['execution']['policy']['price']['version']='unsupported-new-price'
    response=admin.post(ROOT+'/'+one['id']+'/save',json={'bundle':body});assert response.status_code==201
    result=admin.post(ROOT+'/'+response.json()['id']+'/validate',json={}).json()
    assert result['status']=='failed'
    assert 'literature_fixed_provider_policy' in result['domains']['models']['errors']


@pytest.mark.parametrize('change',['provenance','future_caps','future_disabled'])
def test_legacy_literature_ignores_future_metadata_and_caps(admin,client,monkeypatch,change):
    from tests.integration.test_literature_assistance import create,SyntheticProvider
    from tests.api.test_literature import project
    from app.domain.literature_assistance.execution import run_assistance_task,instructions_for
    from app.domain.model_usage.gateway import ModelGateway
    task=create(client,project(client));budgets(client,task)
    with database_connection() as db:
        original=dict(db.execute('SELECT * FROM tasks WHERE id=%s',(task['id'],)).fetchone())
    one=baseline(admin);validated(admin,one)
    assert switch(admin,one,0,'baseline').status_code==200
    body=deepcopy(one['bundle']);entry=body['models']['literature']
    if change=='provenance':entry.update(price_source='synthetic_fixture',price_status='synthetic')
    elif change=='future_caps':entry['execution'].update(input_token_allowance=10000,task_limit_micro_usd=100000)
    else:body['models']['literature']=None
    response=admin.post(ROOT+'/'+one['id']+'/save',json={'bundle':body});assert response.status_code==201
    two=response.json();validated(admin,two)
    activated=switch(admin,two,1,'future-only')
    assert activated.status_code==200,activated.text
    seen=[];submit=ModelGateway.submit
    def record(gateway,request,**kwargs):
        seen.append((request,kwargs));return submit(gateway,request,**kwargs)
    monkeypatch.setattr(ModelGateway,'submit',record)
    provider=SyntheticProvider()
    result=run_assistance_task(task['id'],task['revision'],provider_factory=lambda:provider)
    assert result['status']=='succeeded',result
    assert seen[0][0].policy.model_dump()==type(seen[0][0].policy).model_validate(provider.policy).model_dump()
    assert seen[0][0].input_token_allowance==100000  # Original synthetic fallback, not future cap.
    assert seen[0][1]['instructions']==instructions_for(original['input_snapshot'])
    with database_connection() as db:
        current=db.execute('SELECT * FROM tasks WHERE id=%s',(task['id'],)).fetchone()
        assert current['input_snapshot']==original['input_snapshot'] and current['input_digest']==original['input_digest']
        assert not db.execute("SELECT 1 FROM admin_configuration_bindings WHERE kind='task' AND object_id=%s",(task['id'],)).fetchone()
        assert db.execute("SELECT limit_micro_usd FROM model_budgets WHERE scope_type='task' AND scope_key=%s",(task['id'],)).fetchone()['limit_micro_usd']==5000000


def test_legacy_literature_fallback_has_no_current_policy_dependency():
    from app.domain.admin_configuration.legacy import _affected
    task=dict(task_type='literature_assistance',input_snapshot={})
    assert not _affected(task,['models.literature.execution.policy.price.version'])
    assert not _affected(task,['models.literature.execution.policy.model'])
    assert not _affected(task,['models.literature'])
    assert not _affected(task,['prompts.literature_instruction'])


def test_binding_instruction_does_not_change_strict_snapshot(admin,accounts):
    from tests.api.test_admin_operations import seed_task
    from app.domain.admin_configuration import bindings
    from app.domain.admin_configuration import model_consumption
    one=baseline(admin);one=saved(admin,one,'prompts','explanation_instruction','Be concise.')
    validated(admin,one);switch(admin,one,0,'one')
    _,identity=seed_task(accounts[0]['id'])
    with database_connection(write=True) as db:
        old=dict(db.execute('SELECT * FROM tasks WHERE id=%s',(identity,)).fetchone())
        bindings.bind(db,kind='task',object_id=identity,version=bindings.current(db))
    two=saved(admin,one,'prompts','explanation_instruction','Be detailed.')
    validated(admin,two);switch(admin,two,1,'two')
    with database_connection() as db:
        assert 'Be concise.' in model_consumption.task_instructions(db,old,'fixed safety','explanation')
        current=dict(db.execute('SELECT * FROM tasks WHERE id=%s',(identity,)).fetchone())
        assert current['input_snapshot']==old['input_snapshot'] and current['input_digest']==old['input_digest']


def test_literature_new_tasks_bind_policy_and_instruction_without_snapshot_changes(admin,client):
    from tests.integration.test_literature_assistance import create,SyntheticProvider
    from tests.api.test_literature import project
    from app.domain.literature_assistance.execution import run_assistance_task
    from app.domain.model_usage.service import ModelUsageService
    from tests.helpers.tasks import task_owner
    one=baseline(admin);one=saved(admin,one,'prompts','literature_instruction','Explain uncertainty briefly.')
    validated(admin,one);switch(admin,one,0,'first')
    task=create(client,project(client))
    with database_connection() as db:
        binding=db.execute("SELECT version_id FROM admin_configuration_bindings WHERE kind='task' AND object_id=%s",(task['id'],)).fetchone()
        assert binding and binding['version_id']==one['id']
        snapshot=db.execute('SELECT input_snapshot FROM tasks WHERE id=%s',(task['id'],)).fetchone()['input_snapshot']
        assert set(snapshot)=={'schema_version','project_id','workflow_version','input','material'}
    service=ModelUsageService(task_owner(client))
    for scope,key in [('user',task_owner(client)),('project',task['project_id'])]:service.set_budget(scope,key,5000000,0)
    provider=SyntheticProvider();seen=[]
    original=provider.create
    def create_response(**kw):
        seen.append(kw);response=original(**kw);response['model']=kw['policy'].model;response['response']['model']=kw['policy'].model;return response
    provider.create=create_response
    assert run_assistance_task(task['id'],task['revision'],provider_factory=lambda:provider)['status']=='succeeded'
    assert seen[0]['policy'].model=='gpt-6.1-sol'
    assert 'Explain uncertainty briefly.' in seen[0]['instructions']


def test_recommendation_tightened_cap_and_final_instruction_allowance():
    from app.domain.analysis_recommendation.policy import validate_execution_policy,INSTRUCTIONS
    policy=dict(policy=dict(model='gpt-5.6-sol',prompt_version='analysis_recommendation_v1',max_output_tokens=100,output_format='analysis_recommendation_v1',
        price=dict(version='synthetic',model='gpt-5.6-sol',input_micro_usd_per_million=1,cached_input_micro_usd_per_million=1,output_micro_usd_per_million=1)),input_token_allowance=10000,task_limit_micro_usd=100000)
    assert validate_execution_policy(policy)['task_limit_micro_usd']==100000
    with pytest.raises(Exception):validate_execution_policy(policy,{},instructions=INSTRUCTIONS+'x'*10000)


def test_queued_recommendation_executes_old_bound_instruction_and_readback_digest(admin,client,monkeypatch,tmp_path):
    from tests.integration.test_analysis_recommendation import planning_policy,queued_recommendation,RecommendationProvider
    from app.domain.tasks.recommendation_execution import run_recommendation_task
    path=tmp_path/'synthetic-policy.json';path.write_text(json.dumps(planning_policy()),encoding='utf-8')
    monkeypatch.setenv('PAPERASSIST_ANALYSIS_RECOMMENDATION_POLICY_FILE',str(path))
    one=baseline(admin);one=saved(admin,one,'prompts','recommendation_instruction','Brief rationale.')
    validated(admin,one);assert switch(admin,one,0,'first').status_code==200
    _,_,task=queued_recommendation(client,monkeypatch)
    two=saved(admin,one,'prompts','recommendation_instruction','Detailed rationale.')
    validated(admin,two);assert switch(admin,two,1,'second').status_code==200
    provider=RecommendationProvider();seen=[];original=provider.create
    def record(**kw):seen.append(kw);return original(**kw)
    provider.create=record
    result=run_recommendation_task(task['id'],task['revision'],provider_factory=lambda:provider)
    assert result['status']=='succeeded',result
    assert 'Brief rationale.' in seen[0]['instructions'] and 'Detailed rationale.' not in seen[0]['instructions']
    response=client.get('/api/v1/tasks/'+task['id']+'/analysis-recommendation')
    assert response.status_code==200,response.text


def test_bound_figure_explanation_retains_its_material_output_schema():
    from app.domain.admin_configuration.model_consumption import execution
    from tests.domain.test_explanation_policy import execution_policy
    base=execution_policy();base['input_token_allowance']=100000
    version={'bundle':{'models':{'explanation':{'execution':base}},'prompts':{'explanation_instruction':''}}}
    payload={'schema_version':2,'figure_explanation_contract':1,'language':'en','facts':{},'required_references':{}}
    actual=execution(version,'explanation',payload,figure=True)
    assert actual['policy']['prompt_version']=='figure_explanation_v1'
    assert actual['policy']['output_format']=='analysis_explanation_v2'
