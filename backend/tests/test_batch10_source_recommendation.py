"""A fake provider proves one bounded call; no paid provider is constructed."""
import json
import pytest
from tests.api.test_analysis import client,selection
from tests.integration.test_correlation_plan import prepared_correlations
from tests.integration.test_analysis_recommendation import planning_policy,RecommendationProvider
from tests.helpers.tasks import task_owner
from tests.test_batch10_source_contracts import v5_draft
from tests.integration.test_research_plan import research
from tests.helpers.analysis_plan import run_plan,review_plan

@pytest.mark.parametrize('status',['matched','unspecified','ambiguous','other'])
def test_v5_one_call_source_reference_and_frozen_local_mapping(client,monkeypatch,status):
    from app.domain.tasks.recommendation_execution import run_recommendation_task
    from app.domain.model_usage.service import ModelUsageService
    from app.db.database import database_connection
    class Provider(RecommendationProvider):
        def receipt(self):
            receipt=super().receipt();value=v5_draft();value['source_reference']['status']=status
            if status=='unspecified':value['source_reference'].update(references=[],evidence=[])
            receipt['response']['output'][0]['content'][0]['text']=json.dumps(value)
            return receipt
    policy=planning_policy();policy['policy'].update(prompt_version='analysis_recommendation_v5',output_format='analysis_recommendation_v5')
    monkeypatch.setattr('app.domain.analysis_recommendation.policy.get_execution_policy',lambda payload:policy)
    base,_,prepared=prepared_correlations(client)
    body=dict(schema_version=5,dataset_id=prepared['id'],sheet_name=prepared['source']['sheet_name'],candidate_columns=['A'],output_language='en',research_summary='LOCAL SUMMARY SENTINEL')
    preview=client.post(base+'/analysis-recommendations/preview',json=body)
    assert preview.status_code==200,preview.text
    mapping=preview.json()['source_mapping'];assert [x['code'] for x in mapping]==['F1','S1','D1']
    labels={v['key']:v['value'] for v in preview.json()['labels']};labels['research_summary']='Use F1/S1/D1 age.'
    body['external_processing']=dict(version=1,confirmed=True,source_digest=preview.json()['source_digest'],labels=labels)
    created=client.post(base+'/analysis-recommendations',json=body,headers={'Idempotency-Key':'v5-source'})
    assert created.status_code==202,created.text
    task=created.json();owner=task_owner(client);ledger=ModelUsageService(owner)
    for scope,key in [('user',owner),('project',task['project_id'])]:ledger.set_budget(scope,key,5000000,0)
    provider=Provider();done=run_recommendation_task(task['id'],task['revision'],provider_factory=lambda:provider)
    assert done['status']=='succeeded',done
    assert len(provider.posts)==1
    payload=provider.posts[0]
    assert payload['source_aliases']==[dict(code='F1',level='file'),dict(code='S1',level='sheet'),dict(code='D1',level='dataset')]
    assert 'LOCAL SUMMARY SENTINEL' not in str(payload) and 'source_mapping' not in payload
    for entry in mapping:
        if entry['level']!='dataset':assert entry['name'] not in json.dumps(payload)
    result=client.get('/api/v1/tasks/'+task['id']+'/analysis-recommendation')
    assert result.status_code==200,result.text
    proposal=result.json()['recommendation'];assert proposal['source_reference']['status']==status
    selected=selection(numeric_column='A',group_column=None,unit='')
    planned=client.post(base+'/analysis-plans',json=dict(schema_version=5,input_kind='data',file_id=prepared['source']['file_id'],dataset_id=prepared['id'],expected_setup_revision=0,selection=selected,research_request=research(),evidence_version_ids=[],recommendation_ref=dict(task_id=task['id'],sha256=proposal['sha256'])),headers={'Idempotency-Key':'adopt'})
    assert planned.status_code==202,planned.text
    assert run_plan(planned.json())['status']=='waiting_input'
    review=review_plan(client,planned.json())
    assert review['source_reference']==proposal['source_reference'] and review['check']['research_missing']==['source_confirmation']
