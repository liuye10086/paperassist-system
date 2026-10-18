from tests.helpers.legacy_recommendations import seed_legacy_recommendation
from tests.helpers.legacy_plans import seed_legacy_plan
import json
import pytest
from tests.api.test_analysis import client
from tests.integration.test_correlation_plan import prepared_correlations
from tests.integration.test_analysis_recommendation import planning_policy,RecommendationProvider
from tests.helpers.tasks import task_owner
from tests.test_batch09_research_contracts import draft


class IntentProvider(RecommendationProvider):
    def __init__(self,*,missing=False,**kwargs):
        super().__init__(**kwargs);self.missing=missing
    def receipt(self):
        receipt=super().receipt()
        value=draft()
        if self.missing:value.update(method=None,columns=[],missing_information=['Choose a valid method'])
        receipt['response']['output'][0]['content'][0]['text']=json.dumps(value)
        return receipt


@pytest.mark.parametrize('missing',[False,True])
def test_v4_one_call_recovers_both_intent_and_method_from_actual_edited_summary(client,monkeypatch,missing,tmp_path):
    from app.domain.tasks.recommendation_execution import run_recommendation_task
    from app.domain.model_usage.service import ModelUsageService
    policy=planning_policy();policy['policy'].update(prompt_version='analysis_recommendation_v4',output_format='analysis_recommendation_v4')
    monkeypatch.setattr('app.domain.analysis_recommendation.policy.get_execution_policy',lambda payload:policy)
    base,_,prepared=prepared_correlations(client)
    body=dict(schema_version=4,dataset_id=prepared['id'],sheet_name=prepared['source']['sheet_name'],candidate_columns=['A'],
        output_language='en',research_summary='PRIVATE LOCAL SUMMARY')
    preview=seed_legacy_recommendation(client, base+'/analysis-recommendations/preview',json=body)
    assert preview.status_code==200,preview.text
    labels={v['key']:v['value'] for v in preview.json()['labels']};labels['research_summary']='Describe age.'
    body['external_processing']=dict(version=1,confirmed=True,source_digest=preview.json()['source_digest'],labels=labels)
    response=seed_legacy_recommendation(client, base+'/analysis-recommendations',json=body,headers={'Idempotency-Key':'intent'})
    assert response.status_code==202,response.text
    task=response.json();owner=task_owner(client);ledger=ModelUsageService(owner)
    for scope,key in [('user',owner),('project',task['project_id'])]:ledger.set_budget(scope,key,5000000,0)
    provider=IntentProvider(pending=True,missing=missing)
    pending=run_recommendation_task(task['id'],task['revision'],provider_factory=lambda:provider)
    assert pending['status']=='running'
    provider.pending=False
    done=run_recommendation_task(task['id'],pending['revision'],provider_factory=lambda:provider)
    assert done['status']=='succeeded',done
    assert len(provider.posts)==1 and len(provider.gets)==1
    assert provider.posts[0]['research_summary']=='Describe age.' and 'PRIVATE' not in str(provider.posts)
    result=client.get('/api/v1/tasks/'+task['id']+'/analysis-recommendation')
    assert result.status_code==200,result.text
    assert result.json()['recommendation']['intent']['evidence']==[dict(start=0,end=12,quote='Describe age')]
    assert result.json()['recommendation']['method']==(None if missing else 'descriptive')
    fixture=tmp_path/('research-recommendation-'+('missing' if missing else 'fulfilled')+'-fixture.json')
    fixture.write_text(json.dumps(result.json(),ensure_ascii=False),encoding='utf-8')
    assert client.get(base+'/analysis-setup').json() is None

    if missing:
        from tests.integration.test_research_plan import research
        from tests.helpers.analysis_plan import run_plan,review_plan
        proposal=result.json()['recommendation']
        body=dict(schema_version=4,input_kind='data',file_id=prepared['source']['file_id'],dataset_id=prepared['id'],
            expected_setup_revision=0,selection=None,research_request=research(),evidence_version_ids=[],
            recommendation_ref=dict(task_id=task['id'],sha256=proposal['sha256']))
        adopted=seed_legacy_plan(client, base+'/analysis-plans',json=body,headers={'Idempotency-Key':'adopt-missing'})
        assert adopted.status_code==202,adopted.text
        assert run_plan(adopted.json())['status']=='waiting_input'
        requirement=review_plan(client,adopted.json())
        assert requirement['recommendation_ref']==body['recommendation_ref'] and requirement['result'] is None
    else:
        from tests.integration.test_research_plan import research
        from tests.api.test_analysis import selection
        from tests.helpers.analysis_plan import run_plan,review_plan,decide_plan
        from tests.test_batch09_research_flow import decision
        selected=selection(numeric_column='A',group_column=None,unit='')
        body=dict(schema_version=4,input_kind='data',file_id=prepared['source']['file_id'],dataset_id=prepared['id'],
            expected_setup_revision=0,selection=selected,research_request=research(),evidence_version_ids=[],
            recommendation_ref=dict(task_id=task['id'],sha256=result.json()['recommendation']['sha256']))
        adopted=seed_legacy_plan(client, base+'/analysis-plans',json=body,headers={'Idempotency-Key':'adopt-actionable'})
        assert adopted.status_code==202,adopted.text
        plan=adopted.json();assert run_plan(plan)['status']=='waiting_confirmation'
        view=review_plan(client,plan)
        cleared=decide_plan(client,plan,decision(view,'revise',selection=None),'retract-method')
        assert cleared.status_code==202,cleared.text
        assert run_plan(cleared.json())['status']=='waiting_input'
        view=review_plan(client,plan)
        assert view['selection'] is None and view['recommendation_ref']==body['recommendation_ref']
        restored=decide_plan(client,plan,decision(view,'revise',selection=selected),'restore-method')
        assert restored.status_code==202,restored.text
        assert run_plan(restored.json())['status']=='waiting_confirmation'
