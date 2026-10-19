"""Batch06 approval boundaries; all transport is local httpx MockTransport."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from types import SimpleNamespace
import json

import httpx
import pytest
from app.domain.literature_live.policy import LivePolicyError
from app.domain.model_usage.gateway import input_digest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


SCHEMA = 'pa_test_' + 'a' * 32
INSTRUCTIONS = 'Only return one public JSON suggestion.'
PAYLOAD = {'kind': 'search_plan', 'material': {'research_topic': 'Public aspirin'}}


def ledger_at(tmp_path, n=8):
    from app.domain.literature_live.batch06 import Batch06Ledger
    return Batch06Ledger(tmp_path / 'batch06.jsonl', batch_id='batch06-test', schema=SCHEMA,
        public_inputs=[dict(task_id=f'task-{i}', input_digest=str(i) * 64,
            payload_digest=input_digest(instructions=INSTRUCTIONS,payload=PAYLOAD)) for i in range(n)],
        pmcids=['PMC1','PMC2','PMC3'])


def grant(i=0):
    return dict(task_id=f'task-{i}',input_digest=str(i)*64,
                payload_digest=input_digest(instructions=INSTRUCTIONS,payload=PAYLOAD))


def test_batch06_ledger_is_an_explicit_separate_approval():
    import app.domain.literature_live as live
    assert hasattr(live,'Batch06Ledger'), 'Missing separate persistent Batch06 approval ledger'


def test_create_eight_read_forty_pmc_twelve_and_distinct_three_limits(tmp_path):
    ledger=ledger_at(tmp_path)
    for i in range(8):
        with ledger.locked() as state:
            attempt=ledger.reserve(state,'model_create',grant(i))
            ledger.finish(attempt,receipt={'response_id':f'resp_{i}','usage':None})
    with pytest.raises(LivePolicyError):
        with ledger.locked() as state: ledger.reserve(state,'model_create',grant())
    for _ in range(40):
        with ledger.locked() as state: ledger.reserve(state,'model_read',{'task_id':'task-0','response_id':'resp_0'})
    with pytest.raises(LivePolicyError):
        with ledger.locked() as state: ledger.reserve(state,'model_read',{'task_id':'task-0','response_id':'resp_0'})
    for _ in range(12):
        with ledger.locked() as state: ledger.reserve(state,'pmc',{'pmcid':'PMC1'})
    for pmcid in ['PMC1','PMC4']:
        with pytest.raises(LivePolicyError):
            with ledger.locked() as state: ledger.reserve(state,'pmc',{'pmcid':pmcid})
    summary=ledger.summary()
    assert [summary[k] for k in ('model_create_attempts','model_read_attempts','pmc_attempts')]==[8,40,12]
    assert summary['reserved_micro_usd']==2000000 and summary['estimated_cost_micro_usd'] is None


def test_unknown_create_cannot_resend_and_failure_or_reopen_never_resets(tmp_path):
    ledger=ledger_at(tmp_path)
    with ledger.locked() as state: ledger.reserve(state,'model_create',grant())
    ledger=ledger_at(tmp_path)
    with pytest.raises(LivePolicyError,match='batch06_submission_unknown'):
        with ledger.locked() as state: ledger.reserve(state,'model_create',grant())
    assert ledger.summary()['model_create_attempts']==1
    ledger.complete()
    reopened=ledger_at(tmp_path)
    with pytest.raises(LivePolicyError,match='live_closed'):
        with reopened.locked() as state: reopened.reserve(state,'pmc',{'pmcid':'PMC1'})


@pytest.mark.parametrize('truncate',[1, -1])
def test_truncation_or_complete_event_rollback_fails_closed(tmp_path,truncate):
    ledger=ledger_at(tmp_path);ledger.complete()
    lines=ledger.path.read_bytes().splitlines(keepends=True)
    ledger.path.write_bytes(b''.join(lines[:truncate]))
    with pytest.raises(LivePolicyError,match='live_ledger_invalid'):ledger_at(tmp_path)


def test_concurrent_restart_reservations_never_exceed_eight(tmp_path):
    ledger=ledger_at(tmp_path)
    def attempt(i):
        try:
            reopened=ledger_at(tmp_path)
            with reopened.locked() as state:reopened.reserve(state,'model_create',grant(i%8))
            return True
        except LivePolicyError:return False
    with ThreadPoolExecutor(max_workers=8) as pool:result=list(pool.map(attempt,range(24)))
    assert sum(result)==8 and ledger.summary()['model_create_attempts']==8


def provider(tmp_path,handler):
    from app.domain.literature_live.batch06 import Batch06ModelProvider
    ledger=ledger_at(tmp_path)
    value=Batch06ModelProvider(ledger,task_id='task-0',snapshot_digest='0'*64,api_key='synthetic-test-key',
        http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    config=SimpleNamespace(environment='test',schema=SCHEMA,url=SimpleNamespace(database='paperassist_system_test'))
    task=dict(id='task-0',input_digest='0'*64)
    value.authorize_task(task,config=config,instructions=INSTRUCTIONS,payload=PAYLOAD)
    return ledger,value,task,config


def test_provider_fixed_sdk_transport_durable_reserve_and_no_retry(tmp_path):
    calls=[]
    def wire(request):
        calls.append(request)
        journal=tmp_path/'batch06.jsonl'
        assert b'"kind":"model_create"' in journal.read_bytes()
        return httpx.Response(503,json={'error':{'message':'secret must not be logged'}})
    ledger,value,_,_=provider(tmp_path,wire)
    with pytest.raises(Exception):value.create(policy=value.policy,instructions=INSTRUCTIONS,payload=PAYLOAD)
    assert len(calls)==1
    content=json.loads(calls[0].content)
    assert calls[0].url==httpx.URL('https://api.openai.com/v1/responses')
    assert content['model']=='gpt-6.1-sol' and content['max_output_tokens']==3000
    assert content['reasoning']=={'effort':'low'} and content['service_tier']=='default'
    assert 'tools' not in content
    assert ledger.summary()['model_create_attempts']==1
    assert b'secret must not' not in ledger.path.read_bytes()
    with pytest.raises(LivePolicyError):value.create(policy=value.policy,instructions=INSTRUCTIONS,payload=PAYLOAD)
    assert len(calls)==1
    value.close()


@pytest.mark.parametrize('mode',['instructions','payload','policy','schema','task','database','environment','oversize'])
def test_frozen_authorization_mismatch_denied_before_http(tmp_path,mode):
    calls=[]
    ledger,value,task,config=provider(tmp_path,lambda request:calls.append(request))
    instructions=INSTRUCTIONS;payload=deepcopy(PAYLOAD);policy=value.policy
    if mode=='instructions':instructions+=' changed'
    if mode=='payload':payload['private']='secret'
    if mode=='policy':policy=policy.model_copy(update={'model':'gpt-6'})
    if mode=='schema':config.schema='pa_test_'+'b'*32
    if mode=='task':task['id']='another-task'
    if mode=='database':config.url=SimpleNamespace(database='paperassist_system')
    if mode=='environment':config.environment='development'
    if mode=='oversize':payload['text']='x'*12001
    with pytest.raises(LivePolicyError):
        value.authorize_task(task,config=config,instructions=instructions,payload=payload)
        value.create(policy=policy,instructions=instructions,payload=payload)
    assert not calls and ledger.summary()['model_create_attempts']==0
    value.close()


@pytest.mark.parametrize('field,value',[('public_inputs',[{'task_id':'invalid','input_digest':'not-a-hash','payload_digest':'x'}]),('pmcids',['PMC1','PMC2','PMC3','PMC4']),('schema','public')])
def test_manifest_rejects_empty_whitelist_four_pmcids_and_unisolated_schema(tmp_path,field,value):
    from app.domain.literature_live.batch06 import Batch06Ledger
    options=dict(batch_id='test',schema=SCHEMA,public_inputs=[grant()],pmcids=['PMC1'])
    options[field]=value
    with pytest.raises(LivePolicyError):Batch06Ledger(tmp_path/'other.jsonl',**options)


def test_parser_accepts_reasoning_before_json_but_denies_tool_output():
    from app.domain.literature_assistance.execution import parse_response
    value=dict(direction='Public topic',terms=['aspirin'],synonyms=[],mesh_candidates=[],query='aspirin',explanation='Public suggestion')
    response=dict(status='completed',output=[{'type':'reasoning','summary':[]},
        {'type':'message','content':[{'type':'output_text','text':json.dumps(value)}]}])
    snapshot={'input':{'kind':'search_plan'}}
    assert parse_response(response,snapshot)==value
    response['output'][0]={'type':'function_call','name':'unexpected'}
    with pytest.raises(ValueError):parse_response(response,snapshot)


def test_pmc_phase_one_time_model_freeze_persists_and_cannot_reset_pmc(tmp_path):
    from app.domain.literature_live.batch06 import Batch06Ledger
    options=dict(batch_id='pending',schema=SCHEMA,public_inputs=[],pmcids=['PMC1'])
    ledger=Batch06Ledger(tmp_path/'pending.jsonl',**options)
    with pytest.raises(LivePolicyError):
        with ledger.locked() as state:ledger.reserve(state,'model_create',grant())
    with ledger.locked() as state:ledger.reserve(state,'pmc',{'pmcid':'PMC1'})
    ledger.freeze_model_inputs([grant()])
    reopened=Batch06Ledger(ledger.path,**options)
    with reopened.locked() as state:reopened.reserve(state,'model_create',grant())
    assert reopened.summary()['pmc_attempts']==1
    assert reopened.summary()['model_inputs_frozen'] is True
    with pytest.raises(LivePolicyError):reopened.freeze_model_inputs([grant(1)])
    with pytest.raises(LivePolicyError):reopened.freeze_model_inputs([grant()])

def _process_reserve(options):
    from app.domain.literature_live.batch06 import Batch06Ledger
    path,i=options
    try:
        ledger=ledger_at(__import__('pathlib').Path(path))
        with ledger.locked() as state:ledger.reserve(state,'model_create',grant(i%8))
        return True
    except LivePolicyError:return False


def test_cross_process_attempts_cannot_reset_or_exceed_budget(tmp_path):
    import multiprocessing
    ledger=ledger_at(tmp_path)
    with multiprocessing.get_context('spawn').Pool(3) as pool:
        results=pool.map(_process_reserve,[(str(tmp_path),i) for i in range(18)])
    assert sum(results)==8 and ledger.summary()['reserved_micro_usd']==2000000


def test_pmc_fourth_identifier_denied_before_any_attempt(tmp_path):
    ledger=ledger_at(tmp_path)
    with pytest.raises(LivePolicyError):
        with ledger.locked() as state:ledger.reserve(state,'pmc',{'pmcid':'PMC4'})
    assert ledger.summary()['pmc_attempts']==0


def test_unknown_usage_stays_unknown_and_complete_usage_is_counted_once(tmp_path):
    ledger=ledger_at(tmp_path,n=1)
    with ledger.locked() as state:
        attempt=ledger.reserve(state,'model_create',grant())
        ledger.finish(attempt,receipt={'response_id':'resp_known','usage':None})
    assert ledger.summary()['estimated_cost_micro_usd'] is None
    usage=dict(input_tokens=100,output_tokens=50,total_tokens=150,
        input_tokens_details=dict(cached_tokens=10,cache_write_tokens=0))
    for _ in range(2):
        with ledger.locked() as state:
            attempt=ledger.reserve(state,'model_read',{'task_id':'task-0','response_id':'resp_known'})
            ledger.finish(attempt,receipt={'response_id':'resp_known','usage':usage})
    # 90*$2/M + 10*$0.1/M + 50*$10/M = 681 microUSD, never double billed by polling.
    assert ledger.summary()['estimated_cost_micro_usd']==681


def test_frozen_whitelist_and_checkpoint_cannot_change_on_restart(tmp_path):
    from app.domain.literature_live.batch06 import Batch06Ledger
    ledger=ledger_at(tmp_path)
    options=dict(batch_id='batch06-test',schema=SCHEMA,public_inputs=[grant()],pmcids=['PMC1','PMC2','PMC3'])
    with pytest.raises(LivePolicyError):Batch06Ledger(ledger.path,**options)
    watermark=ledger.path.with_name(ledger.path.name+'.lock')
    old=watermark.read_bytes()
    ledger.complete()
    watermark.write_bytes(old)
    with pytest.raises(LivePolicyError,match='live_ledger_invalid'):ledger_at(tmp_path)
