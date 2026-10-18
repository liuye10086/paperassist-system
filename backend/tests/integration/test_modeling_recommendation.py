"""v3 metadata-only planning keeps budget, recovery and explicit adoption."""
from tests.helpers.legacy_recommendations import seed_legacy_recommendation
import json
from tests.api.test_analysis import client
from tests.integration.test_correlation_plan import prepared_correlations
from tests.integration.test_comparison_plan import independent_rows
from tests.integration.test_analysis_recommendation import preview_request,planning_policy,RecommendationProvider
from tests.domain.test_modeling_recommendation_contracts import draft
from tests.helpers.tasks import task_owner


class ModelingProvider(RecommendationProvider):
    def receipt(self):
        receipt=super().receipt()
        value=draft('roc_auc')
        receipt['response']['output'][0]['content'][0]['text']=json.dumps(value)
        return receipt


def test_v3_recommendation_has_minimal_metadata_and_single_call_recovery(client,monkeypatch):
    from app.domain.tasks.recommendation_execution import run_recommendation_task
    from app.domain.model_usage.service import ModelUsageService
    policy=planning_policy()
    policy['policy'].update(prompt_version='analysis_recommendation_v3',output_format='analysis_recommendation_v3')
    monkeypatch.setattr('app.domain.analysis_recommendation.policy.get_execution_policy',lambda payload:policy)
    base,_,prepared=prepared_correlations(client,rows=independent_rows())
    body={**preview_request(prepared),'schema_version':3}
    response=seed_legacy_recommendation(client, base+'/analysis-recommendations/preview',json=body)
    assert response.status_code==200,response.text
    preview=response.json()
    assert preview['version']==3 and len(preview['allowed_methods'])==13
    assert preview['allowed_methods'][-4:]==['ols','logistic','roc_auc','kaplan_meier']
    assert 'rows' not in preview and 'values' not in preview
    body['external_processing']=dict(version=1,confirmed=True,source_digest=preview['source_digest'],
                                    labels={v['key']:v['value'] for v in preview['labels']})
    response=seed_legacy_recommendation(client, base+'/analysis-recommendations',json=body,headers={'Idempotency-Key':'modeling-advice'})
    assert response.status_code==202,response.text
    task=response.json();owner=task_owner(client);ledger=ModelUsageService(owner)
    for scope,key in [('user',owner),('project',task['project_id'])]:ledger.set_budget(scope,key,5000000,0)
    provider=ModelingProvider(pending=True)
    waiting=run_recommendation_task(task['id'],task['revision'],provider_factory=lambda:provider)
    assert waiting['status']=='running'
    provider.pending=False
    done=run_recommendation_task(task['id'],waiting['revision'],provider_factory=lambda:provider)
    assert done['status']=='succeeded',done
    assert len(provider.posts)==1 and len(provider.gets)==1
    response=client.get('/api/v1/tasks/'+task['id']+'/analysis-recommendation')
    assert response.status_code==200,response.text
    assert response.json()['recommendation']['schema_version']==3
    assert client.get(base+'/analysis-setup').json() is None
