"""New comparison recommendations freeze v2 while historical v1 keeps its prompt."""
from tests.helpers.legacy_recommendations import seed_legacy_recommendation
import copy
import json
import pytest
from tests.api.test_analysis import client
from tests.integration.test_comparison_plan import independent_rows,make_plan
from tests.integration.test_correlation_plan import prepared_correlations
from tests.integration.test_analysis_recommendation import preview_request,planning_policy,RecommendationProvider,queued_recommendation
from tests.helpers.tasks import task_owner


def policy_v2():
    value=planning_policy();value['policy'].update(prompt_version='analysis_recommendation_v2',output_format='analysis_recommendation_v2');return value


class ComparisonProvider(RecommendationProvider):
    def __init__(self,*,blank=False,legacy=False,**kwargs):
        super().__init__(**kwargs);self.blank=blank;self.legacy=legacy;self.instructions=[]
    def receipt(self):
        receipt=super().receipt()
        draft=dict(schema_version=2,method='welch_t',mode='independent',columns=['A','B'],
            roles=dict(numeric_column='A',group_column='B',pair_id_column=None,before_column=None,after_column=None),
            output_language='en',rationale=['Compare the mean outcome across two independent groups.'],
            assumptions=['Confirm independent units and normal group populations.'],missing_information=[])
        if self.legacy:
            draft=json.loads(receipt['response']['output'][0]['content'][0]['text'])
        if self.blank:draft.update(rationale=[],assumptions=[])
        if self.corrupt:draft['roles']['group_column']='C'
        receipt['response']['output'][0]['content'][0]['text']=json.dumps(draft)
        return receipt
    def create(self,*,policy,instructions,payload):
        self.instructions.append(instructions)
        return super().create(policy=policy,instructions=instructions,payload=payload)


def queued_v2(client,monkeypatch):
    monkeypatch.setattr('app.domain.analysis_recommendation.policy.get_execution_policy',lambda payload:policy_v2())
    base,_,prepared=prepared_correlations(client,rows=independent_rows())
    body={**preview_request(prepared),'schema_version':2}
    preview=seed_legacy_recommendation(client, base+'/analysis-recommendations/preview',json=body)
    assert preview.status_code==200,preview.text
    disclosure=preview.json()
    assert disclosure['version']==2 and len(disclosure['allowed_methods'])==9
    assert disclosure['allowed_modes']==['pair','matrix','independent','paired','multiple']
    assert 'rows' not in disclosure and 'values' not in disclosure and 'local-private' not in json.dumps(disclosure)
    body['external_processing']=dict(version=1,confirmed=True,source_digest=disclosure['source_digest'],labels={i['key']:i['value'] for i in disclosure['labels']})
    response=seed_legacy_recommendation(client, base+'/analysis-recommendations',json=body,headers={'Idempotency-Key':'recommendation-v2'})
    assert response.status_code==202,response.text
    task=response.json()
    from app.domain.model_usage.service import ModelUsageService
    owner=task_owner(client);ledger=ModelUsageService(owner)
    for scope,key in [('user',owner),('project',task['project_id'])]:ledger.set_budget(scope,key,5000000,0)
    return base,prepared,task


def test_v2_recommendation_recovery_preserves_roles_and_separate_approval(client,monkeypatch):
    from app.domain.tasks.recommendation_execution import run_recommendation_task
    from tests.helpers.analysis_plan import run_plan
    base,prepared,task=queued_v2(client,monkeypatch);provider=ComparisonProvider(pending=True)
    waiting=run_recommendation_task(task['id'],task['revision'],provider_factory=lambda:provider)
    assert waiting['status']=='running'
    provider.pending=False
    completed=run_recommendation_task(task['id'],waiting['revision'],provider_factory=lambda:provider)
    assert completed['status']=='succeeded' and len(provider.posts)==1 and len(provider.gets)==1
    response=client.get('/api/v1/tasks/'+task['id']+'/analysis-recommendation')
    assert response.status_code==200,response.text
    view=response.json();result=view['recommendation']
    assert view['request']['schema_version']==2 and view['input_version']['workflow_version']=='analysis_recommendation_v2'
    assert result['schema_version']==2 and result['roles']['numeric_column']=='A'
    assert client.get(base+'/analysis-setup').json() is None
    plan,_=make_plan(client,base,prepared)
    assert run_plan(plan)['status']=='waiting_confirmation'
    assert provider.posts[0]['schema_version']==2 and 'roles' in provider.instructions[0]


@pytest.mark.parametrize('blank,corrupt',[(True,False),(False,True)])
def test_v2_invalid_explanation_or_crossed_role_never_publishes(client,monkeypatch,blank,corrupt):
    from app.domain.tasks.recommendation_execution import run_recommendation_task
    base,_,task=queued_v2(client,monkeypatch);provider=ComparisonProvider(blank=blank,corrupt=corrupt)
    value=run_recommendation_task(task['id'],task['revision'],provider_factory=lambda:provider)
    assert value['status']=='failed' and value['error_code']=='recommendation_invalid'
    assert client.get(base+'/analysis-setup').json() is None


def test_new_v1_recommendation_requires_reason_but_legacy_empty_receipt_is_readable(client,monkeypatch):
    from app.domain.tasks.recommendation_execution import run_recommendation_task
    from app.db.database import database_connection
    base,_,task=queued_recommendation(client,monkeypatch);provider=ComparisonProvider(blank=True,legacy=True)
    failed=run_recommendation_task(task['id'],task['revision'],provider_factory=lambda:provider)
    assert failed['status']=='failed' and failed['error_code']=='recommendation_invalid'
    assert client.get(base+'/analysis-setup').json() is None


def test_frozen_legacy_v1_can_continue_and_read_saved_empty_explanations(client,monkeypatch):
    from app.domain.tasks.recommendation_execution import run_recommendation_task
    from app.db.database import database_connection
    from app.domain.analysis_recommendation.policy import INSTRUCTIONS
    base,_,task=queued_recommendation(client,monkeypatch)
    with database_connection(write=True) as db:
        snapshot=db.execute('SELECT input_snapshot FROM tasks WHERE id=%s',(task['id'],)).fetchone()['input_snapshot']
        snapshot.pop('require_explanation',None)
        from psycopg.types.json import Jsonb
        db.execute('UPDATE tasks SET input_snapshot=%s WHERE id=%s',(Jsonb(snapshot),task['id']))
    provider=ComparisonProvider(blank=True,legacy=True)
    assert run_recommendation_task(task['id'],task['revision'],provider_factory=lambda:provider)['status']=='succeeded'
    assert provider.instructions==[INSTRUCTIONS]
    view=client.get('/api/v1/tasks/'+task['id']+'/analysis-recommendation')
    assert view.status_code==200,view.text
    assert view.json()['recommendation']['rationale']==[]
    assert view.json()['recommendation']['assumptions']==[]


@pytest.mark.parametrize('version',[2.0,True])
def test_recommendation_v2_version_is_an_exact_integer(client,version):
    base,_,prepared=prepared_correlations(client,rows=independent_rows())
    response=seed_legacy_recommendation(client, base+'/analysis-recommendations/preview',json={**preview_request(prepared),'schema_version':version})
    assert response.status_code==422,response.text


def test_saved_v2_malformed_draft_fails_closed_as_source_conflict(client,monkeypatch):
    from app.domain.tasks.recommendation_execution import run_recommendation_task
    from app.db.database import database_connection
    from app.domain.dataset_preparation.service import request_digest
    from psycopg.types.json import Jsonb
    _,_,task=queued_v2(client,monkeypatch);provider=ComparisonProvider()
    assert run_recommendation_task(task['id'],task['revision'],provider_factory=lambda:provider)['status']=='succeeded'
    with database_connection(write=True) as db:
        row=db.execute('SELECT id,state_json FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',(task['id'],)).fetchone()
        state=row['state_json'];value=state['recommendation'];value['roles']['numeric_column']='C'
        value['sha256']=request_digest({k:v for k,v in value.items() if k!='sha256'})
        db.execute('UPDATE task_checkpoints SET state_json=%s WHERE id=%s',(Jsonb(state),row['id']))
    response=client.get('/api/v1/tasks/'+task['id']+'/analysis-recommendation')
    assert response.status_code==409,response.text
    assert response.json()['detail']['code']=='task_source_conflict'
