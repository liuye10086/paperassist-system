"""Read-only projections of saved call facts; synthetic transport, isolated schema."""
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_literature import project
from tests.integration.test_literature_assistance import create,budgets,SyntheticProvider
from app.domain.literature_assistance.execution import run_assistance_task


def detail(client, task):
    return client.get(f'/api/v1/projects/{task["project_id"]}/literature/assistance/tasks/{task["id"]}').json()


def test_saved_usage_projection_never_infers_live_source_or_exposes_internal_identifiers(client):
    task=create(client,project(client));budgets(client,task)
    provider=SyntheticProvider()
    assert run_assistance_task(task['id'],task['revision'],provider_factory=lambda:provider)['status']=='succeeded'
    value=detail(client,task)
    assert len(value['model_calls'])==1
    call=value['model_calls'][0]
    assert call['provenance']=='not_recorded'
    assert call['model']=='gpt-5.6-sol' and call['status']=='completed'
    assert call['usage']==dict(input_tokens=100,output_tokens=50,total_tokens=150,cached_input_tokens=0)
    assert call['estimated_cost_micro_usd'] is not None
    assert not {'id','call_id','input_digest','policy_snapshot','provider_response_id'} & set(call)
    assert value['real_calls_enabled'] is False


def test_no_call_and_failed_unknown_call_do_not_invent_zero_usage_or_cost(client):
    task=create(client,project(client));assert detail(client,task)['model_calls']==[]
    budgets(client,task)
    provider=SyntheticProvider(unknown=True)
    run_assistance_task(task['id'],task['revision'],provider_factory=lambda:provider)
    call=detail(client,task)['model_calls'][0]
    assert call['status']=='submission_unknown' and call['provenance']=='not_recorded'
    assert call['usage'] is None and call['estimated_cost_micro_usd'] is None


def test_mock_official_model_completed_call_remains_unknown_source_when_business_result_failed(client,tmp_path):
    import httpx
    from tests.integration.test_literature_batch06_assistance import bound_provider,response
    task=create(client,project(client));budgets(client,task)
    invalid=dict(direction='Public topic',terms=['aspirin'],synonyms=[dict(term='invalid object')],
        mesh_candidates=[],query='aspirin',explanation='Public suggestion')
    _,provider=bound_provider(tmp_path,task,lambda request:httpx.Response(200,json=response(invalid)))
    saved=run_assistance_task(task['id'],task['revision'],provider_factory=lambda:provider)
    assert saved['status']=='failed' and saved['error_code']=='literature_assistance_invalid'
    value=detail(client,task);call=value['model_calls'][0]
    assert value['result'] is None and value['task']['status']=='failed'
    assert call['status']=='completed' and call['model']=='gpt-6.1-sol'
    assert call['provenance']=='not_recorded'
    assert call['estimated_cost_micro_usd']>0 and call['usage']['total_tokens']==150
