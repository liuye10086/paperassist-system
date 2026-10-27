"""Recovery of original durable receipts only; synthetic providers, isolated schemas."""
import pytest

from tests.api.test_analysis import client
from tests.integration.test_analysis_recommendation import queued_recommendation, RecommendationProvider, planning_policy, preview_request
from tests.integration.test_correlation_plan import prepared_correlations
from tests.helpers.legacy_recommendations import seed_legacy_recommendation
from app.adapters.task_execution_store import TaskExecutionStore
from app.adapters.task_store import TaskStore
from app.db.database import database_connection
from app.domain.model_usage.service import ModelUsageService
from app.domain.tasks.recommendation_execution import run_recommendation_task
from tests.helpers.tasks import task_owner


def queued_version(client,monkeypatch,version):
    def policy(payload):
        value=planning_policy()
        value['policy'].update(prompt_version=f'analysis_recommendation_v{version}',output_format=f'analysis_recommendation_v{version}')
        return value
    monkeypatch.setattr('app.domain.analysis_recommendation.policy.get_execution_policy',policy)
    base,_,prepared=prepared_correlations(client)
    body=preview_request(prepared)
    if version>1: body['schema_version']=version
    endpoint=base+'/analysis-recommendations'
    preview=seed_legacy_recommendation(client,endpoint+'/preview',json=body)
    assert preview.status_code==200,preview.text
    value=preview.json()
    body['external_processing']=dict(version=1,confirmed=True,source_digest=value['source_digest'],labels={i['key']:i['value'] for i in value['labels']})
    response=seed_legacy_recommendation(client,endpoint,json=body,headers={'Idempotency-Key':'recovery-version'})
    assert response.status_code==202,response.text
    task=response.json();owner=task_owner(client);ledger=ModelUsageService(owner)
    for scope,key in [('user',owner),('project',task['project_id'])]: ledger.set_budget(scope,key,5000000,0)
    return task


@pytest.mark.parametrize('version',[1,2,3,4,5])
@pytest.mark.parametrize('crashed',[False,True])
def test_recommendation_recovery_matches_workflow_call_key(client,monkeypatch,version,crashed):
    task=queued_version(client,monkeypatch,version)
    provider=RecommendationProvider(unknown=True)
    class WorkerCrash(BaseException): pass
    if crashed:
        def crash(**kwargs):
            provider.posts.append(kwargs['payload'])
            raise WorkerCrash()
        provider.create=crash
        with pytest.raises(WorkerCrash):
            run_recommendation_task(task['id'],task['revision'],provider_factory=lambda:provider)
    else:
        waiting=run_recommendation_task(task['id'],task['revision'],provider_factory=lambda:provider)
        assert waiting['reason_code']=='submission_unknown'
    with database_connection(write=True) as db:
        if crashed:
            db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s",(task['id'],))
    store=TaskExecutionStore()
    assert store.recover_expired()==int(crashed)
    current=TaskStore(task_owner(client)).get(task['id'])
    assert current['status']=='waiting_confirmation' and current['reason_code']=='submission_unknown'
    assert store.recover_expired()==0
    with database_connection() as db:
        call=db.execute('SELECT * FROM model_calls WHERE task_id=%s',(task['id'],)).fetchone()
    receipt=provider.receipt()
    ModelUsageService(task_owner(client)).record_response(call['id'],event_key='late-receipt',request_id=receipt['request_id'],
        response_id=receipt['response_id'],model=receipt['model'],status=receipt['status'],usage=receipt['usage'])
    with database_connection(write=True) as db:
        db.execute("UPDATE model_calls SET call_key='unrelated:v1' WHERE id=%s",(call['id'],))
    assert store.recover_expired()==0
    with database_connection(write=True) as db:
        db.execute('UPDATE model_calls SET call_key=%s WHERE id=%s',(call['call_key'],call['id']))
    assert store.recover_expired()==1
    current=TaskStore(task_owner(client)).get(task['id'])
    assert current['status']=='queued'
    assert store.recover_expired()==0 and len(provider.posts)==1 and not provider.gets
    # Higher-version business output is deliberately invalid in this v1 provider;
    # every workflow must still GET/account its original response before parsing.
    result=run_recommendation_task(task['id'],current['revision'],provider_factory=lambda:provider)
    assert result['status'] in ('succeeded','failed')
    assert len(provider.posts)==1 and provider.gets==[receipt['response_id']]


def test_explanation_late_receipt_recovers_original_call(client,monkeypatch):
    # Exercise the adapter's persisted identity matching without requiring the
    # Linux numerical sandbox used to produce an explanation's business input.
    _,_,task=queued_recommendation(client,monkeypatch);owner=task_owner(client)
    provider=RecommendationProvider(unknown=True)
    waiting=run_recommendation_task(task['id'],task['revision'],provider_factory=lambda:provider)
    assert waiting['reason_code']=='submission_unknown'
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET task_type='explanation',workflow_version='explanation_v1' WHERE id=%s",(task['id'],))
        db.execute("UPDATE model_calls SET call_key='explanation:v1' WHERE task_id=%s",(task['id'],))
    store=TaskExecutionStore()
    assert store.recover_expired()==0
    with database_connection() as db:
        call=db.execute('SELECT * FROM model_calls WHERE task_id=%s',(task['id'],)).fetchone()
    receipt=provider.receipt()
    ModelUsageService(owner).record_response(call['id'],event_key='late-receipt',request_id=receipt['request_id'],
        response_id=receipt['response_id'],model=receipt['model'],status=receipt['status'],usage=receipt['usage'])
    assert store.recover_expired()==1
    with database_connection() as db:
        assert db.execute('SELECT status FROM tasks WHERE id=%s',(task['id'],)).fetchone()['status']=='queued'
    assert store.recover_expired()==0 and len(provider.posts)==1 and not provider.gets
