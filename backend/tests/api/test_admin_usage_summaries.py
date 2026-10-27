"""Immutable capture and source verification; synthetic persisted observations."""
from app.db.database import database_connection
from tests.api.test_admin_operations import accounts,admin,seed_task,seed_call,login
from tests.api.test_admin_reporting_edges import context,configure,request
from app.main import app
from fastapi.testclient import TestClient
import pytest

ROOT='/api/v1/admin/usage/summaries'


def test_tool_configuration_is_distinct_from_actual_evidence(admin,accounts):
    owner=accounts[2]['id'];project,task=seed_task(owner);seed_call(owner,project,task,tool=True)
    result=admin.get('/api/v1/admin/usage',params={'user_id':owner}).json()['summary']
    assert result['configured_tool_call_count']==1
    assert result['observed_actual_tool_uses']==0
    assert result['actual_tool_usage_unknown_calls']==1
    assert result['actual_tool_usage_known_calls']==0


def test_saved_summary_rebuilds_event_tokens_but_preserves_captured_mutable_state(admin,context):
    service=configure(context);call=service.reserve_call(request(context[3]));service.begin_submission(call['id'])
    common=dict(response_id='resp_capture',request_id=None,model='test-model')
    service.record_response(call['id'],event_key='partial',status='in_progress',usage={'input_tokens':200},**common)
    response=admin.post(ROOT,json={'user_id':context[1],'group_by':'model'})
    assert response.status_code==201,response.text
    saved=response.json();identity=saved['id']
    assert saved['result']['summary']['input_tokens']['known']==200
    service.record_response(call['id'],event_key='complete',status='completed',usage={'input_tokens':50,'output_tokens':5},**common)
    verified=admin.post(ROOT+'/'+identity+'/verify',json={})
    assert verified.status_code==200,verified.text
    assert verified.json()['verified'] is True
    assert verified.json()['recomputed_immutable_fields'] is True
    detail=admin.get(ROOT+'/'+identity).json()
    assert detail['result']==saved['result']
    assert 'budgets' not in detail['result']
    assert admin.get(ROOT).json()['items'][0]['id']==identity
    with TestClient(app) as ordinary:
        # context owner is not an administrator.
        assert ordinary.get(ROOT).status_code in (401,403)


def test_saved_summaries_reject_unknown_query_and_normal_user(admin,accounts):
    assert admin.post(ROOT,json={'provider_state':{'tool_count':99}}).status_code==422
    with TestClient(app) as ordinary:
        login(ordinary,accounts[2])
        assert ordinary.get(ROOT).status_code==403
        assert ordinary.post(ROOT,json={}).status_code==403


def test_conflicting_raw_response_cannot_prove_zero_tool_uses(admin,context):
    from app.domain.model_usage.gateway import ModelGateway
    service=configure(context);call=service.reserve_call(request(context[3]));service.begin_submission(call['id'])
    ModelGateway(service,None)._record(call['id'],dict(response_id='resp_conflict',request_id=None,model='test-model',
        status='in_progress',usage=None,response=dict(id='resp_conflict',status='completed',output=[])),submitted=False)
    result=admin.get('/api/v1/admin/usage',params={'user_id':context[1]}).json()['items'][0]
    assert result['tool_call_count'] is None


def test_bound_disabled_models_block_real_transport_before_reservation(admin,context):
    import httpx2,pytest
    from tests.api.test_admin_configurations import baseline,validated,switch
    from app.domain.admin_configuration.bindings import current,bind
    from app.adapters.models.openai_responses import OpenAIResponsesProvider
    from app.domain.model_usage.gateway import ModelGateway,ModelGatewayError,input_digest
    one=baseline(admin);validated(admin,one);switch(admin,one,0,'first')
    with database_connection(write=True) as db:bind(db,kind='task',object_id=context[3],version=current(db))
    service=configure(context);req=request(context[3]).model_copy(update={'input_digest':input_digest(instructions='safe',payload={})})
    seen=[]
    def transport(req):seen.append(req);raise AssertionError('Forbidden real transport')
    provider=OpenAIResponsesProvider(api_key='synthetic-not-real',http_client=httpx2.Client(transport=httpx2.MockTransport(transport)))
    with pytest.raises(ModelGatewayError) as exc:ModelGateway(service,provider).submit(req,instructions='safe',payload={})
    assert exc.value.code=='model_configuration_disabled'
    assert seen==[]
    with database_connection() as db:assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']==0
    provider.close()


def test_verify_does_not_blindly_trust_a_resealed_token_projection(admin,context):
    from app.db.database import migration_connection
    from app.domain.admin_usage_summaries import seal,fingerprint
    from psycopg.types.json import Jsonb
    service=configure(context);call=service.reserve_call(request(context[3]));service.begin_submission(call['id'])
    service.record_response(call['id'],event_key='known',response_id='resp_capture',request_id=None,model='test-model',status='completed',usage={'input_tokens':20})
    saved=admin.post(ROOT,json={'user_id':context[1]}).json()
    with migration_connection(write=True) as db:
        row=dict(db.execute('SELECT * FROM admin_usage_summaries WHERE id=%s',(saved['id'],)).fetchone())
        entry=row['source_manifest']['calls'][0]
        entry['captured_projection']['input_tokens']=999
        entry['captured_projection_sha256']=fingerprint(entry['captured_projection'])
        row['sha256']=seal(row)
        db.execute('ALTER TABLE admin_usage_summaries DISABLE TRIGGER admin_usage_summaries_seal')
        db.execute('UPDATE admin_usage_summaries SET source_manifest=%s,sha256=%s WHERE id=%s',(Jsonb(row['source_manifest']),row['sha256'],row['id']))
        db.execute('ALTER TABLE admin_usage_summaries ENABLE TRIGGER admin_usage_summaries_seal')
    result=admin.post(ROOT+'/'+saved['id']+'/verify',json={}).json()
    assert result['verified'] is False and 'token_projection_mismatch' in result['errors']


def test_summary_reconciliation_is_recomputed_from_original_events(admin,context):
    from tests.integration.test_model_reconciliation import plot,reconciliation,evidence
    service,call=plot(context);recon=reconciliation(context)
    recon.reconcile(call['id'],evidence('tool',600))
    saved=admin.post(ROOT,json={'user_id':context[1]}).json()
    recon.reconcile(call['id'],evidence('token',1000,1,'token-later'))
    result=admin.post(ROOT+'/'+saved['id']+'/verify',json={}).json()
    assert result['verified'] is True,result
    assert saved['result']['summary']['actual_known_micro_usd']==600


@pytest.mark.parametrize('corruption',['actual_total','partial_as_reconciled','no_event_amount','tool_applicability','reconciled_time'])
def test_verify_rejects_resealed_reconciliation_not_supported_by_original_events(admin,context,monkeypatch,corruption):
    from tests.integration.test_model_reconciliation import plot,reconciliation,evidence
    from app.db.database import migration_connection
    from app.domain.admin_usage_summaries import seal,fingerprint,totals
    from psycopg.types.json import Jsonb
    service,call=plot(context)
    if corruption=='actual_total':
        from types import SimpleNamespace
        from app.domain.model_usage import reconciliation as module
        fixed=module.datetime.now(module.timezone.utc)
        identifiers=iter(['ffffffff-ffff-4fff-8fff-fffffffffff0','00000000-0000-4000-8000-000000000001'])
        monkeypatch.setattr(module,'datetime',SimpleNamespace(now=lambda tz:fixed))
        monkeypatch.setattr(module,'uuid4',lambda:next(identifiers))
    if corruption!='no_event_amount':
        recon=reconciliation(context);recon.reconcile(call['id'],evidence('tool',600))
        if corruption=='actual_total':recon.reconcile(call['id'],evidence('token',1000,1,'token'))
    saved=admin.post(ROOT,json={'user_id':context[1]}).json()
    initial=admin.post(ROOT+'/'+saved['id']+'/verify',json={}).json()
    assert initial['verified'] is True,initial
    # Only this per-test schema's owner can reseal. This simulates a bad capture,
    # not a claim that ordinary runtime roles can alter the immutable table.
    with migration_connection(write=True) as db:
        row=dict(db.execute('SELECT * FROM admin_usage_summaries WHERE id=%s',(saved['id'],)).fetchone())
        entry=row['source_manifest']['calls'][0];value=entry['captured_projection']['reconciliation']
        if corruption=='actual_total':value['actual_micro_usd']=9999
        elif corruption=='partial_as_reconciled':value['status']='reconciled'
        elif corruption=='no_event_amount':value.update(status='reconciled',token_micro_usd=1000,tool_micro_usd=600,actual_micro_usd=1600)
        elif corruption=='tool_applicability':value['tool_applicable']=False
        else:value['reconciled_at']='2000-01-01T00:00:00+00:00'
        entry['captured_projection_sha256']=fingerprint(entry['captured_projection'])
        row['result']=totals([entry['captured_projection']],row['filters']['group_by']);row['sha256']=seal(row)
        db.execute('ALTER TABLE admin_usage_summaries DISABLE TRIGGER admin_usage_summaries_seal')
        db.execute('UPDATE admin_usage_summaries SET source_manifest=%s,result=%s,sha256=%s WHERE id=%s',
            (Jsonb(row['source_manifest']),Jsonb(row['result']),row['sha256'],row['id']))
        db.execute('ALTER TABLE admin_usage_summaries ENABLE TRIGGER admin_usage_summaries_seal')
    result=admin.post(ROOT+'/'+saved['id']+'/verify',json={}).json()
    assert result['verified'] is False,result
    assert 'reconciliation_projection_mismatch' in result['errors']
