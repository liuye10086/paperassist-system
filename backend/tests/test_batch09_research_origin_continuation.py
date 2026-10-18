from tests.helpers.legacy_recommendations import seed_legacy_recommendation
from tests.helpers.legacy_plans import seed_legacy_plan
from tests.api.test_analysis import client
from tests.integration.test_batch09_filter_pipeline import published,ROWS,filtering,accept
from tests.integration.test_analysis_recommendation import planning_policy
from tests.test_batch09_research_recommendation import IntentProvider
from tests.integration.test_research_plan import research
from tests.helpers.analysis_plan import run_plan,review_plan
from tests.helpers.tasks import task_owner


def test_explicit_continuation_origin_requires_real_controlled_descendant(client,monkeypatch):
    from app.domain.tasks.recommendation_execution import run_recommendation_task
    from app.domain.model_usage.service import ModelUsageService
    base,parent=published(client,ROWS)
    policy=planning_policy();policy['policy'].update(prompt_version='analysis_recommendation_v4',output_format='analysis_recommendation_v4')
    monkeypatch.setattr('app.domain.analysis_recommendation.policy.get_execution_policy',lambda payload:policy)
    body=dict(schema_version=4,dataset_id=parent['id'],sheet_name=parent['source']['sheet_name'],candidate_columns=['A'],output_language='en',research_summary='Describe age.')
    preview=seed_legacy_recommendation(client, base+'/analysis-recommendations/preview',json=body).json()
    body['external_processing']=dict(version=1,confirmed=True,source_digest=preview['source_digest'],labels={x['key']:x['value'] for x in preview['labels']})
    task=seed_legacy_recommendation(client, base+'/analysis-recommendations',json=body,headers={'Idempotency-Key':'origin-proposal'}).json()
    owner=task_owner(client);ledger=ModelUsageService(owner)
    for scope,key in [('user',owner),('project',task['project_id'])]:ledger.set_budget(scope,key,5000000,0)
    provider=IntentProvider()
    assert run_recommendation_task(task['id'],task['revision'],provider_factory=lambda:provider)['status']=='succeeded'
    result=client.get('/api/v1/tasks/'+task['id']+'/analysis-recommendation').json()['recommendation']
    ref=dict(task_id=task['id'],sha256=result['sha256'])
    requirement=dict(schema_version=4,input_kind='data',file_id=parent['source']['file_id'],dataset_id=parent['id'],expected_setup_revision=0,
        selection=None,research_request=research(),evidence_version_ids=[])
    parent_task=seed_legacy_plan(client, base+'/analysis-plans',json=requirement,headers={'Idempotency-Key':'requirement'}).json()
    assert run_plan(parent_task)['status']=='waiting_input';view=review_plan(client,parent_task)
    request={k:view[k] for k in ('input_version','checkpoint_id','wait_id','plan_revision')}
    request.update(expected_task_revision=view['task']['revision'],file_id=parent['source']['file_id'],dataset_id=parent['id'],expected_setup_revision=0,
        selection=None,research_request=research(),origin_recommendation_ref=ref)
    url='/api/v1/tasks/'+parent_task['id']+'/analysis-plan/continuations'
    rejected=client.post(url,json=request,headers={'Idempotency-Key':'not-derived'})
    assert rejected.status_code==409,rejected.text
    filter_task,_=filtering(client,base,parent)
    filtered,_,_=accept(client,filter_task)
    request['dataset_id']=filtered['id']
    response=client.post(url,json=request,headers={'Idempotency-Key':'derived'})
    assert response.status_code==202,response.text
    child=response.json()['task'];assert run_plan(child)['status']=='waiting_input'
    saved=review_plan(client,child)
    assert saved['origin_recommendation_ref']==ref and saved['recommendation_ref'] is None and saved['result'] is None
    assert client.post(url,json=request,headers={'Idempotency-Key':'derived'}).json()==response.json()
    assert review_plan(client,parent_task)['continuation']==response.json()
    assert len(provider.posts)==1
