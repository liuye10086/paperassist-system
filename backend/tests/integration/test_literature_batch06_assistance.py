"""Explicit batch06 provider with synthetic HTTP only, isolated PostgreSQL schemas."""
import json
import httpx
import pytest
from app.db.database import database_connection,get_database_config
from app.domain.model_usage.gateway import input_digest
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_literature import project
from tests.integration.test_literature_assistance import create,budgets,review_task,SyntheticProvider


def bound_provider(tmp_path,task,handler):
    from app.domain.literature_live.batch06 import Batch06Ledger,Batch06ModelProvider
    from app.domain.literature_assistance.execution import INSTRUCTIONS
    with database_connection() as db:
        saved=dict(db.execute('SELECT * FROM tasks WHERE id=%s',(task['id'],)).fetchone())
    snapshot=saved['input_snapshot']
    payload=dict(kind=snapshot['input']['kind'],output_language=snapshot['input']['output_language'],material=snapshot['material'])
    ledger=Batch06Ledger(tmp_path/'batch06.jsonl',batch_id='integration',schema=get_database_config().schema,
        public_inputs=[dict(task_id=task['id'],input_digest=saved['input_digest'],payload_digest=input_digest(instructions=INSTRUCTIONS,payload=payload))],pmcids=[])
    return ledger,Batch06ModelProvider(ledger,task_id=task['id'],snapshot_digest=saved['input_digest'],api_key='local-test-only',
        http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def response(value,status='completed'):
    return dict(id='resp_batch06',object='response',created_at=1,model='gpt-6.1-sol',status=status,
        usage=dict(input_tokens=100,output_tokens=50,total_tokens=150,input_tokens_details=dict(cached_tokens=0)),
        output=[dict(id='rs_1',type='reasoning',summary=[]),dict(id='msg_1',type='message',role='assistant',status='completed',
            content=[dict(type='output_text',text=json.dumps(value),annotations=[])])])


def test_explicit_batch06_sdk_provider_executes_through_gateway_and_projects_suggestion(client,tmp_path):
    from app.domain.literature_assistance.execution import run_assistance_task
    task=create(client,project(client));budgets(client,task);calls=[]
    value=dict(direction='Public topic',terms=['aspirin'],synonyms=[],mesh_candidates=[],query='aspirin',explanation='Public suggestion')
    def wire(request):
        calls.append(request)
        return httpx.Response(200,json=response(value,'in_progress' if len(calls)==1 else 'completed'))
    ledger,p=bound_provider(tmp_path,task,wire)
    # New provider per execution matches normal worker lifecycle (close is expected).
    first=run_assistance_task(task['id'],task['revision'],provider_factory=lambda:p)
    assert first['status']=='running',first
    _,p=bound_provider(tmp_path,task,wire)
    done=run_assistance_task(task['id'],first['revision'],provider_factory=lambda:p)
    assert done['status']=='succeeded',done
    assert [r.method for r in calls]==['POST','GET']
    assert ledger.summary()['model_create_attempts']==ledger.summary()['model_read_attempts']==1
    with database_connection() as db:
        call=db.execute('SELECT * FROM model_calls WHERE task_id=%s',(task['id'],)).fetchone()
        assert call['policy_snapshot']['model']=='gpt-6.1-sol'
        assert call['policy_snapshot']['input_token_allowance']==12000
        assert db.execute('SELECT count(*) AS n FROM usage_events').fetchone()['n']>0
        assert db.execute('SELECT result_json FROM literature_assistance_requests').fetchone()['result_json']==value


def test_explicit_real_review_is_advice_and_never_creates_manual_review(client,tmp_path):
    from app.domain.literature_assistance.execution import run_assistance_task
    task,path,claim,request=review_task(client);budgets(client,task)
    value=dict(status='partial',relevance='related',reason='Public abstract only',narrowed_statement='Bounded statement',
        limitations=['Abstract only'],evidence_ids=request['evidence_ids'])
    ledger,p=bound_provider(tmp_path,task,lambda req:httpx.Response(200,json=response(value)))
    result=run_assistance_task(task['id'],task['revision'],provider_factory=lambda:p)
    assert result['status']=='succeeded',result
    assert client.get(path+'/claims/'+claim['id']+'/reviews').json()['total']==0
    assert ledger.summary()['model_create_attempts']==1


def test_arbitrary_source_kind_cannot_authorize_real_provider(client):
    from app.domain.literature_assistance.execution import run_assistance_task
    task=create(client,project(client));budgets(client,task)
    p=SyntheticProvider();p.source_kind='stage05_batch06_public'
    result=run_assistance_task(task['id'],task['revision'],provider_factory=lambda:p)
    assert result['status']=='failed' and result['error_code']=='literature_assistance_not_authorized'
    assert not p.posts

def test_unknown_batch06_post_stays_waiting_and_reopened_provider_never_reposts(client,tmp_path):
    from app.domain.literature_assistance.execution import run_assistance_task
    from app.domain.literature_live.policy import LivePolicyError
    task=create(client,project(client));budgets(client,task);calls=[]
    def wire(req):
        calls.append(req)
        raise httpx.ConnectError('synthetic unknown submission',request=req)
    ledger,p=bound_provider(tmp_path,task,wire)
    result=run_assistance_task(task['id'],task['revision'],provider_factory=lambda:p)
    assert result['status']=='waiting_confirmation' and result['reason_code']=='submission_unknown',result
    assert ledger.summary()['model_create_attempts']==1 and len(calls)==1
    assert run_assistance_task(task['id'],result['revision'],provider_factory=lambda:p) is None
    _,reopened=bound_provider(tmp_path,task,wire)
    from app.domain.literature_assistance.execution import INSTRUCTIONS
    with database_connection() as db:
        saved=dict(db.execute('SELECT * FROM tasks WHERE id=%s',(task['id'],)).fetchone())
    snapshot=saved['input_snapshot']
    payload=dict(kind=snapshot['input']['kind'],output_language=snapshot['input']['output_language'],material=snapshot['material'])
    reopened.authorize_task(saved,config=get_database_config(),instructions=INSTRUCTIONS,payload=payload)
    with pytest.raises(LivePolicyError,match='batch06_submission_unknown'):
        reopened.create(policy=reopened.policy,instructions=INSTRUCTIONS,payload=payload)
    reopened.close()
    assert len(calls)==1

def test_bare_openai_provider_cannot_spoof_synthetic_source_kind(client):
    from app.domain.literature_assistance.execution import run_assistance_task
    from app.adapters.models.openai_responses import OpenAIResponsesProvider
    task=create(client,project(client));budgets(client,task);calls=[]
    p=OpenAIResponsesProvider(api_key='local-test',http_client=httpx.Client(transport=httpx.MockTransport(lambda req:calls.append(req))))
    p.source_kind='synthetic_fixture'
    p.policy=SyntheticProvider.policy
    result=run_assistance_task(task['id'],task['revision'],provider_factory=lambda:p)
    assert result['status']=='failed' and result['error_code']=='literature_assistance_not_authorized',result
    assert not calls
