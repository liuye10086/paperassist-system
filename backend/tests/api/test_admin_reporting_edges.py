"""Focused reporting/linkage boundaries beyond the primary integration flow."""
from datetime import datetime,timezone

from app.db.database import database_connection
from tests.api.test_admin_operations import accounts,admin,seed_call,seed_task  # noqa:F401
from tests.integration.test_model_usage import context,configure,request  # noqa:F401


def test_authorized_task_validation_error_retains_verified_task_link(admin,accounts):
    _,task=seed_task(accounts[0]['id'])
    response=admin.get('/api/v1/tasks/'+task+'/events?after=-1')
    assert response.status_code==422,response.text
    logs=admin.get('/api/v1/admin/logs',params={'task_id':task}).json()['items']
    assert any(row['request_id']==response.headers['X-Request-ID'] and row['error_code']=='invalid_request' for row in logs)


def test_arbitrary_call_cannot_become_live_via_writing_flag(admin,accounts):
    owner=accounts[2]['id'];project,task=seed_task(owner)
    seed_call(owner,project,task,provenance='openai_live',cost=70)
    response=admin.get('/api/v1/admin/usage')
    assert response.status_code==200,response.text
    assert response.json()['by_provenance']['openai_live']['call_count']==0
    assert response.json()['by_provenance']['unknown']['call_count']==1


def test_cost_components_and_usage_dimensions_preserve_unknowns(admin,accounts):
    owner=accounts[2]['id'];project,task=seed_task(owner)
    partial=seed_call(owner,project,task,provenance='synthetic_fixture',usage={'input_tokens':20},cost=70,tool=True)
    complete=seed_call(owner,project,task,provenance='synthetic_fixture',usage={'input_tokens':3,'output_tokens':2},cost=15)
    with database_connection(write=True) as db:
        db.execute('UPDATE model_calls SET actual_token_micro_usd=100 WHERE id=%s',(partial,))
        db.execute('UPDATE model_calls SET actual_token_micro_usd=10 WHERE id=%s',(complete,))
        first=db.execute('SELECT created_at FROM model_calls WHERE id=%s',(partial,)).fetchone()['created_at']
    params={'user_id':owner,'project_id':project,'task_id':task,'model':'fixture-model','group_by':'day','page_size':1}
    result=admin.get('/api/v1/admin/usage',params=params)
    assert result.status_code==200,result.text
    data=result.json();summary=data['summary']
    assert data['total']==2 and len(data['items'])==1
    assert summary['actual_micro_usd'] is None and summary['actual_known_micro_usd']==110
    assert summary['partial_count']==1 and summary['reconciled_count']==1 and summary['actual_unknown_count']==1
    assert data['groups'][0]['key']==first.astimezone(timezone.utc).strftime('%Y-%m-%d')
    assert admin.get('/api/v1/admin/usage',params={**params,'model':'other-model'}).json()['total']==0
    assert admin.get('/api/v1/admin/usage',params={**params,'to':first.isoformat()}).json()['total']==0
    for dimension in ('user','project','task','model','month'):
        grouped=admin.get('/api/v1/admin/usage',params={**params,'group_by':dimension})
        assert grouped.status_code==200 and grouped.json()['group_total']==1


def test_nested_budget_reservations_are_counted_once_using_existing_accounting(admin,context):
    from psycopg.types.json import Jsonb
    service=configure(context)
    call=service.reserve_call(request(context[3]))
    assert service.begin_submission(call['id'])
    with database_connection(write=True) as db:
        db.execute("UPDATE model_calls SET provider_state=provider_state || %s WHERE id=%s",
                   (Jsonb({'provider_provenance':'synthetic_fixture'}),call['id']))
        assert db.execute('SELECT count(*) AS n FROM budget_reservations WHERE call_id=%s',(call['id'],)).fetchone()['n']==3
    summary=admin.get('/api/v1/admin/usage',params={'user_id':context[1]}).json()['summary']
    assert summary['reserved_micro_usd']==120 and summary['accounted_micro_usd']==0
    service.record_response(call['id'],event_key='partial',response_id='synthetic-response',
        request_id='synthetic-request',model='test-model',status='in_progress',usage={'input_tokens':20})
    result=admin.get('/api/v1/admin/usage',params={'user_id':context[1]})
    assert result.status_code==200,result.text
    data=result.json();summary=data['summary']
    assert summary['accounted_micro_usd']==20 and summary['reserved_micro_usd']==100
    assert summary['input_tokens']=={'known':20,'unknown_count':0}
    assert summary['output_tokens']=={'known':0,'unknown_count':1}
    assert data['by_provenance']['synthetic_fixture']['reserved_micro_usd']==100
    assert data['by_provenance']['openai_live']['call_count']==0


def test_usage_replay_keeps_latest_distinct_observation(admin,context):
    service=configure(context)
    call=service.reserve_call(request(context[3]))
    service.begin_submission(call['id'])
    common=dict(response_id='synthetic-response',request_id=None,model='test-model')
    service.record_response(call['id'],event_key='pending',status='completed',usage={'input_tokens':200},**common)
    service.record_response(call['id'],event_key='complete',status='completed',usage={'input_tokens':50,'output_tokens':5},**common)
    service.record_response(call['id'],event_key='replayed-pending',status='completed',usage={'input_tokens':200},**common)
    data=admin.get('/api/v1/admin/usage',params={'user_id':context[1]}).json()
    assert [data['items'][0][name] for name in ('input_tokens','output_tokens','total_tokens')]==[50,5,55]
    assert data['summary']['input_tokens']=={'known':50,'unknown_count':0}
    # A genuinely new observation after manual reconciliation remains reportable.
    with database_connection(write=True) as db:
        db.execute('UPDATE model_calls SET reconciliation_revision=1 WHERE id=%s',(call['id'],))
    service.record_response(call['id'],event_key='new-evidence',status='completed',usage={'input_tokens':60,'output_tokens':6},**common)
    latest=admin.get('/api/v1/admin/usage',params={'user_id':context[1]}).json()
    assert latest['items'][0]['total_tokens']==66
    assert latest['summary']['accounted_micro_usd']==data['summary']['accounted_micro_usd']


def test_tool_execution_counts_preserve_evidence_and_unknowns(admin,accounts):
    from psycopg.types.json import Jsonb
    owner=accounts[2]['id'];project,task=seed_task(owner)
    known=seed_call(owner,project,task,tool=True)
    unknown=seed_call(owner,project,task,tool=True)
    released=seed_call(owner,project,task,tool=True)
    with database_connection(write=True) as db:
        response=db.execute('SELECT provider_response_id FROM model_calls WHERE id=%s',(known,)).fetchone()['provider_response_id']
        db.execute('UPDATE model_calls SET provider_state=%s WHERE id=%s',(Jsonb({'tool_execution_evidence':{'response_id':response,'complete':True,'call_ids':['ci_1','ci_2']}}),known))
        db.execute("UPDATE model_calls SET status='released',provider_response_id=NULL WHERE id=%s",(released,))
    data=admin.get('/api/v1/admin/usage',params={'user_id':owner}).json()
    for summary in (data['summary'],data['by_provenance']['unknown'],data['groups'][0]['summary']):
        assert summary['tool_call_count']==2
        assert summary['tool_call_unknown_count']==1
        assert summary['configured_tool_call_count']==3
        assert summary['observed_actual_tool_uses']==2
        assert summary['actual_tool_usage_known_calls']==2
        assert summary['actual_tool_usage_unknown_calls']==1
        assert summary['actual_micro_usd'] is None
    counts={row['id']:row['tool_call_count'] for row in data['items']}
    assert counts=={known:2,unknown:None,released:0}
    known_call=next(row for row in data['items'] if row['id']==known)
    assert known_call['estimated_cost_micro_usd'] is None
    assert known_call['reconciliation']['actual_micro_usd'] is None
    metrics=admin.get('/api/v1/admin/metrics').json()
    assert metrics['tool_calls']==2 and metrics['tool_calls_unknown_count']==1
    assert metrics['actual_tool_usage_known_calls']==2 and metrics['actual_tool_usage_unknown_calls']==1


def test_gateway_persists_tool_evidence_without_body_and_does_not_regress(admin,context):
    from app.domain.model_usage.gateway import ModelGateway
    service=configure(context)
    call=service.reserve_call(request(context[3]));service.begin_submission(call['id'])
    gateway=ModelGateway(service,None)
    common=dict(response_id='synthetic-response',request_id=None,model='test-model',status='completed',usage={'input_tokens':50,'output_tokens':5})
    response={'id':'synthetic-response','status':'completed','output':[
        {'id':'ci_1','type':'code_interpreter_call','status':'completed','code':'PRIVATE-CODE'},
        {'id':'ci_2','type':'code_interpreter_call','status':'completed'},
        {'id':'ci_2','type':'code_interpreter_call','status':'completed'}]}
    gateway._record(call['id'],dict(**common,response=response),submitted=False)
    saved=service.get_call(call['id'])
    evidence=saved['provider_state']['tool_execution_evidence']
    assert evidence=={'response_id':'synthetic-response','complete':True,'call_ids':['ci_1','ci_2']}
    assert 'PRIVATE-CODE' not in str(saved)
    gateway._record(call['id'],dict(**common,response={'id':'synthetic-response','status':'in_progress','output':[]}),submitted=False)
    assert service.get_call(call['id'])['provider_state']['tool_execution_evidence']==evidence
    assert admin.get('/api/v1/admin/usage',params={'user_id':context[1]}).json()['summary']['tool_call_count']==2


def test_tool_evidence_handles_partial_missing_and_malformed_outputs():
    from app.domain.model_usage.tool_evidence import merge_tool_evidence,response_tool_evidence,tool_count
    assert response_tool_evidence({'id':'other','status':'completed','output':[]},'r') is None
    assert response_tool_evidence({'id':'r','status':'completed'},'r') is None
    assert response_tool_evidence({'id':'r','status':'completed','output':[{}]},'r')['complete'] is False
    assert response_tool_evidence({'id':'r','status':'completed','output':[{'type':'web_search_call','status':'completed','id':'w'}]},'r')['complete'] is False
    assert response_tool_evidence({'id':'r','status':'completed','output':[]},'r')=={'response_id':'r','complete':True,'call_ids':[]}
    failed=response_tool_evidence({'id':'r','status':'completed','output':[{'type':'code_interpreter_call','status':'failed','id':'ci_failed'}]},'r')
    assert failed=={'response_id':'r','complete':False,'call_ids':[]}
    evidence=response_tool_evidence({'id':'r','status':'in_progress','output':[
        {'type':'code_interpreter_call','status':'completed','id':'ci_1'},
        {'type':'code_interpreter_call','status':'interpreting','id':'ci_2'}]},'r')
    assert tool_count({'status':'submitted','provider_response_id':'r','provider_state':{'tool_execution_evidence':evidence}})==(1,True)
    previous={'response_id':'r','complete':False,'call_ids':[f'ci_{index}' for index in range(1000)]}
    merged=merge_tool_evidence(previous,{'response_id':'r','complete':True,'call_ids':['ci_new']})
    assert len(merged['call_ids'])==1000 and merged['complete'] is False
    assert tool_count({'status':'submitted','provider_response_id':'r','provider_state':{'tool_execution_evidence':merged}})==(1000,True)
