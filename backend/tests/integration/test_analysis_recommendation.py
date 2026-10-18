"""Recommendation disclosure is metadata-only and never approves analysis."""
from tests.helpers.legacy_recommendations import seed_legacy_recommendation
from tests.helpers.statistics import statistics_post
import pytest
from tests.api.test_analysis import client
from tests.integration.test_correlation_plan import prepared_correlations

def preview_request(prepared):
    return dict(dataset_id=prepared['id'],sheet_name=prepared['source']['sheet_name'],candidate_columns=['A','B'],
        output_language='en',research_summary='Only the individually confirmed research summary.')

def test_recommendation_preview_exposes_selected_metadata_and_no_row_values(client):
    base,_,prepared=prepared_correlations(client)
    response=seed_legacy_recommendation(client, base+'/analysis-recommendations/preview',json=preview_request(prepared))
    assert response.status_code==200,response.text
    value=response.json()
    assert [field['column'] for field in value['fields']]==['A','B']
    assert value['allowed_methods']==['descriptive','pearson','spearman']
    assert value['output_language']=='en' and len(value['source_digest'])==64
    assert not any(key in str(value) for key in ('"rows"','"values"','第三列'))
    from app.db.database import database_connection
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']==0

def test_recommendation_creation_requires_exact_independent_disclosure_confirmation(client):
    base,_,prepared=prepared_correlations(client)
    body=preview_request(prepared)
    endpoint=base+'/analysis-recommendations'
    assert seed_legacy_recommendation(client, endpoint,json=body,headers={'Idempotency-Key':'missing-confirmation'}).status_code==422
    preview=seed_legacy_recommendation(client, endpoint+'/preview',json=body)
    assert preview.status_code==200,preview.text
    value=preview.json()
    confirmation=dict(version=1,confirmed=True,source_digest='0'*64,labels={label['key']:label['value'] for label in value['labels']})
    rejected=seed_legacy_recommendation(client, endpoint,json={**body,'external_processing':confirmation},headers={'Idempotency-Key':'stale'})
    assert rejected.status_code==409,rejected.text

def planning_policy():
    return dict(policy=dict(model='gpt-5.6-sol',prompt_version='analysis_recommendation_v1',max_output_tokens=2000,
        timeout_seconds=15,tools=[],output_format='analysis_recommendation_v1',price=dict(version='synthetic-only',currency='USD',
        model='gpt-5.6-sol',input_micro_usd_per_million=100,cached_input_micro_usd_per_million=50,output_micro_usd_per_million=200)),
        input_token_allowance=100000,task_limit_micro_usd=500000)

def queued_recommendation(client,monkeypatch):
    monkeypatch.setattr('app.domain.analysis_recommendation.policy.get_execution_policy',lambda payload:planning_policy())
    base,_,prepared=prepared_correlations(client)
    body=preview_request(prepared);preview=seed_legacy_recommendation(client, base+'/analysis-recommendations/preview',json=body).json()
    body['external_processing']=dict(version=1,confirmed=True,source_digest=preview['source_digest'],labels={i['key']:i['value'] for i in preview['labels']})
    response=seed_legacy_recommendation(client, base+'/analysis-recommendations',json=body,headers={'Idempotency-Key':'planning'})
    assert response.status_code==202,response.text
    task=response.json()
    from tests.helpers.tasks import task_owner
    from app.domain.model_usage.service import ModelUsageService
    owner=task_owner(client);ledger=ModelUsageService(owner)
    for scope,key in [('user',owner),('project',task['project_id'])]: ledger.set_budget(scope,key,5000000,0)
    return base,prepared,task

def test_recommendation_task_is_claimable_without_publishing_setup(client,monkeypatch):
    base,_,task=queued_recommendation(client,monkeypatch)
    from app.adapters.task_execution_store import TaskExecutionStore
    lease=TaskExecutionStore().claim(task['id'],task['revision'])
    assert lease is not None,'Recommendation must use the unified fenced worker.'
    assert client.get(base+'/analysis-setup').json() is None

class RecommendationProvider:
    def __init__(self,*,pending=False,unknown=False,corrupt=False):
        self.pending=pending;self.unknown=unknown;self.corrupt=corrupt;self.posts=[];self.gets=[]
    def receipt(self):
        import json
        draft=dict(schema_version=1,method='pearson',mode='pair',columns=['A','B'],output_language='en',
            rationale=['Assess a linear association.'],assumptions=['Confirm independent observations.'],missing_information=[])
        if self.corrupt:draft['columns']=['A','C']
        usage=dict(input_tokens=100,output_tokens=50,total_tokens=150,input_tokens_details={'cached_tokens':0})
        response=dict(id='resp_planning_synthetic',model='gpt-5.6-sol',status='in_progress' if self.pending else 'completed',usage=usage,
            output=[{'type':'message','content':[{'type':'output_text','text':json.dumps(draft)}]}])
        return dict(response_id=response['id'],request_id='req_planning',model=response['model'],status=response['status'],usage=usage,response=response)
    def create(self,*,policy,instructions,payload):
        self.posts.append(payload)
        if self.unknown:raise RuntimeError('synthetic unknown submission')
        return self.receipt()
    def retrieve(self,response_id,*,policy):self.gets.append(response_id);return self.receipt()
    def close(self):pass

def test_recommendation_recovery_fetches_saved_receipt_once_and_requires_plan_approval(client,monkeypatch):
    from app.domain.tasks.recommendation_execution import run_recommendation_task
    base,prepared,task=queued_recommendation(client,monkeypatch)
    provider=RecommendationProvider(pending=True)
    deferred=run_recommendation_task(task['id'],task['revision'],provider_factory=lambda:provider)
    assert deferred['status']=='running' and len(provider.posts)==1
    provider.pending=False
    completed=run_recommendation_task(task['id'],deferred['revision'],provider_factory=lambda:provider)
    assert completed['status']=='succeeded' and len(provider.posts)==1 and len(provider.gets)==1
    view=client.get('/api/v1/tasks/'+task['id']+'/analysis-recommendation')
    assert view.status_code==200,view.text
    recommendation=view.json()['recommendation']
    assert recommendation['method']=='pearson'
    assert client.get(base+'/analysis-setup').json() is None
    assert client.get('/api/v1/tasks/'+task['id']+'/workspace').status_code==200
    from tests.integration.test_correlation_plan import create_correlation
    plan,_=create_correlation(client,base,prepared,changes={'recommendation_ref':{'task_id':task['id'],'sha256':recommendation['sha256']}})
    from tests.helpers.analysis_plan import run_plan
    assert run_plan(plan)['status']=='waiting_confirmation'
    assert statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).status_code==409
    assert 'rows' not in provider.posts[0] and len(provider.posts[0]['fields'])==2
    from app.maintenance.database_audit import audit_database
    from app.db.database import database_connection
    with database_connection() as db:
        audit=audit_database(db)
        assert audit['ok'],audit

@pytest.mark.parametrize('unknown',[True,False])
def test_uncertain_or_unapproved_recommendations_never_publish_or_repeat_posts(client,monkeypatch,unknown):
    from app.domain.tasks.recommendation_execution import run_recommendation_task
    base,_,task=queued_recommendation(client,monkeypatch)
    provider=RecommendationProvider(unknown=unknown,corrupt=not unknown)
    result=run_recommendation_task(task['id'],task['revision'],provider_factory=lambda:provider)
    assert result['status']==('waiting_confirmation' if unknown else 'failed')
    assert result['error_code']==('model_submission_unknown' if unknown else 'recommendation_invalid')
    assert run_recommendation_task(task['id'],task['revision'],provider_factory=lambda:provider) is None
    assert len(provider.posts)==1
    view=client.get('/api/v1/tasks/'+task['id']+'/workspace').json()
    assert view['allowed_actions']==[]
    assert client.get(base+'/analysis-setup').json() is None

def test_late_recommendation_receipt_recovers_without_another_submission(client,monkeypatch):
    from app.domain.tasks.recommendation_execution import run_recommendation_task
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.domain.model_usage.service import ModelUsageService
    from tests.helpers.tasks import task_owner
    from app.db.database import database_connection
    _,_,task=queued_recommendation(client,monkeypatch);provider=RecommendationProvider(unknown=True)
    waiting=run_recommendation_task(task['id'],task['revision'],provider_factory=lambda:provider)
    assert waiting['reason_code']=='submission_unknown'
    with database_connection() as db:call=db.execute('SELECT * FROM model_calls WHERE task_id=%s',(task['id'],)).fetchone()
    receipt=provider.receipt()
    ModelUsageService(task_owner(client)).record_response(call['id'],event_key='late-receipt',request_id=receipt['request_id'],
        response_id=receipt['response_id'],model=receipt['model'],status=receipt['status'],usage=receipt['usage'])
    assert TaskExecutionStore().recover_expired()==1
    current=client.get('/api/v1/tasks/'+task['id']+'/workspace').json()['task']
    assert current['status']=='queued'
    completed=run_recommendation_task(task['id'],current['revision'],provider_factory=lambda:provider)
    assert completed['status']=='succeeded' and len(provider.posts)==1 and len(provider.gets)==1

def test_budget_wait_releases_worker_and_resume_does_not_approve_a_plan(client,monkeypatch):
    from app.domain.tasks.recommendation_execution import run_recommendation_task
    from app.domain.model_usage.service import ModelUsageService
    from tests.helpers.tasks import task_owner
    base,_,task=queued_recommendation(client,monkeypatch)
    ledger=ModelUsageService(task_owner(client))
    budget=ledger.get_budget('project',task['project_id'])
    ledger.set_budget('project',task['project_id'],0,budget['revision'])
    provider=RecommendationProvider()
    waiting=run_recommendation_task(task['id'],task['revision'],provider_factory=lambda:provider)
    assert waiting['status']=='waiting_confirmation' and waiting['reason_code']=='budget_exceeded'
    assert provider.posts==[]
    view=client.get('/api/v1/tasks/'+task['id']+'/workspace').json()
    assert view['allowed_actions']==['resume']
    budget=ledger.get_budget('project',task['project_id']);ledger.set_budget('project',task['project_id'],5000000,budget['revision'])
    body=dict(operation='resume',wait_id=view['wait']['id'],expected_task_revision=view['task']['revision'],input_version=view['task']['input_version'])
    resumed=client.post('/api/v1/tasks/'+task['id']+'/resume',json=body,headers={'Idempotency-Key':'budget-resume'})
    assert resumed.status_code==202,resumed.text
    assert run_recommendation_task(task['id'],resumed.json()['revision'],provider_factory=lambda:provider)['status']=='succeeded'
    assert len(provider.posts)==1 and client.get(base+'/analysis-setup').json() is None

def test_recommended_plan_revision_cannot_expand_the_approved_candidate_set(client,monkeypatch):
    from app.domain.tasks.recommendation_execution import run_recommendation_task
    from tests.integration.test_correlation_plan import create_correlation
    from tests.helpers.analysis_plan import run_plan,review_plan,plan_decision,decide_plan
    base,prepared,task=queued_recommendation(client,monkeypatch);provider=RecommendationProvider()
    assert run_recommendation_task(task['id'],task['revision'],provider_factory=lambda:provider)['status']=='succeeded'
    result=client.get('/api/v1/tasks/'+task['id']+'/analysis-recommendation').json()['recommendation']
    plan,_=create_correlation(client,base,prepared,changes={'recommendation_ref':dict(task_id=task['id'],sha256=result['sha256'])})
    run_plan(plan);view=review_plan(client,plan)
    changed={**view['selection'],'columns':['A','C'],'units':{'A':'','C':''}}
    assert decide_plan(client,plan,plan_decision(view,'revise',changed),'expand').status_code==409


def test_recommendation_read_rejects_a_receipt_for_different_material(client,monkeypatch):
    from app.domain.tasks.recommendation_execution import run_recommendation_task
    from app.db.database import database_connection
    _,_,task=queued_recommendation(client,monkeypatch);provider=RecommendationProvider()
    assert run_recommendation_task(task['id'],task['revision'],provider_factory=lambda:provider)['status']=='succeeded'
    with database_connection(write=True) as db:
        db.execute('UPDATE model_calls SET input_digest=%s WHERE task_id=%s',('b'*64,task['id']))
    assert client.get('/api/v1/tasks/'+task['id']+'/analysis-recommendation').status_code==409


def test_recommendation_receipt_is_readable_in_project_and_task_usage(client,monkeypatch):
    from app.domain.tasks.recommendation_execution import run_recommendation_task
    _,_,task=queued_recommendation(client,monkeypatch);provider=RecommendationProvider()
    assert run_recommendation_task(task['id'],task['revision'],provider_factory=lambda:provider)['status']=='succeeded'
    for url in ('/api/v1/projects/'+task['project_id']+'/model-usage','/api/v1/tasks/'+task['id']+'/model-usage'):
        response=client.get(url)
        assert response.status_code==200,response.text
        assert response.json()['items'][0]['task_type']=='analysis_recommendation'
