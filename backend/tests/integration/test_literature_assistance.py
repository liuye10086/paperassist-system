"""Isolated, synthetic-only assistance; live external calls remain unauthorized."""
import json
import pytest

from app.db.database import database_connection
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_literature import project


def body():
    return dict(kind='search_plan', research_topic='Synthetic topic', source_context='Only saved context', output_language='en')


def create(client, pid, request=None, key='assistance'):
    response = client.post(f'/api/v1/projects/{pid}/literature/assistance/tasks',
        json=request or body(), headers={'Idempotency-Key': key})
    assert response.status_code == 202, response.text
    return response.json()


def test_default_assistance_durable_authorization_wait_has_no_model_records(client):
    pid = project(client)
    task = create(client, pid)
    from app.domain.literature_assistance.execution import run_assistance_task
    from app.workers.dispatcher import dispatch_once
    from app.domain.tasks.execution import run_task
    messages=[]
    assert dispatch_once(publish=messages.append)==1
    assert messages[0]['task_id']==task['id']
    waiting = run_task(task['id'], task['revision'])
    assert waiting['status'] == 'waiting_confirmation'
    workspace = client.get('/api/v1/tasks/' + task['id'] + '/workspace')
    assert workspace.status_code == 200, workspace.text
    assert workspace.json()['wait']['kind'] == 'literature_model_authorization'
    assert workspace.json()['allowed_actions'] == []
    detail = client.get(f'/api/v1/projects/{pid}/literature/assistance/tasks/{task["id"]}').json()
    assert detail['result'] is None and detail['real_calls_enabled'] is False
    assert run_assistance_task(task['id'], task['revision']) is None
    with database_connection() as db:
        for table in ('model_calls', 'budget_reservations'):
            assert db.execute('SELECT count(*) AS n FROM ' + table).fetchone()['n'] == 0


def test_assistance_contract_rejects_unbound_evidence_and_unsupported_partial():
    from app.domain.literature_assistance.contracts import validate_result
    snapshot = dict(input=dict(kind='evidence_review', evidence_ids=['real-id']),
                    material=dict(evidence=[dict(id='real-id', reading_scope='abstract', quote='Actual quote')]))
    result = dict(status='supported', relevance='related', reason='Based on abstract only',
                  narrowed_statement='', limitations=['Abstract only'], evidence_ids=['fake-id'])
    with pytest.raises(ValueError):
        validate_result(result, snapshot)
    result.update(status='partial', evidence_ids=['real-id'])
    with pytest.raises(ValueError):
        validate_result(result, snapshot)


class SyntheticProvider:
    source_kind = 'synthetic_fixture'
    policy = dict(model='gpt-5.6-sol',prompt_version='literature_assistance_v1',max_output_tokens=2000,timeout_seconds=15,tools=[],output_format='text',price=dict(version='synthetic-only',currency='USD',model='gpt-5.6-sol',input_micro_usd_per_million=100,cached_input_micro_usd_per_million=50,output_micro_usd_per_million=200))

    def __init__(self, *, pending=False, invalid=False, get_failures=0, unknown=False):
        self.pending, self.invalid = pending, invalid
        self.get_failures, self.unknown = get_failures, unknown
        self.posts, self.gets = [], []

    def receipt(self):
        value = dict(direction='Explore the supplied topic', terms=['synthetic'], synonyms=[],
                     mesh_candidates=[dict(term='Synthetic candidate', verified=False)],
                     query='synthetic[Title/Abstract]', explanation='Suggested query; MeSH candidates are unverified.')
        if self.invalid:
            value['mesh_candidates'][0]['verified'] = True
        usage = dict(input_tokens=100, output_tokens=50, total_tokens=150, input_tokens_details={'cached_tokens': 0})
        response = dict(id='resp_assistance_synthetic', model='gpt-5.6-sol',
            status='in_progress' if self.pending else 'completed', usage=usage,
            output=[dict(type='message', content=[dict(type='output_text', text=json.dumps(value))])])
        return dict(response_id=response['id'], request_id='req_assistance', model=response['model'],
                    status=response['status'], usage=usage, response=response)

    def create(self, *, policy, instructions, payload):
        self.posts.append(payload)
        if self.unknown:
            raise RuntimeError('Synthetic uncertain POST')
        return self.receipt()

    def retrieve(self, response_id, *, policy):
        self.gets.append(response_id)
        if self.get_failures:
            self.get_failures -= 1
            from app.adapters.models.openai_responses import ModelProviderError
            raise ModelProviderError('model_provider_request_failed', status_code=503)
        return self.receipt()

    def close(self):
        pass


def budgets(client, task):
    from app.domain.model_usage.service import ModelUsageService
    from tests.helpers.tasks import task_owner
    service = ModelUsageService(task_owner(client))
    for scope, key in [('user', task_owner(client)), ('project', task['project_id']), ('task', task['id'])]:
        service.set_budget(scope, key, 5000000, 0)


def test_synthetic_assistance_uses_budget_usage_and_saved_receipt_without_duplicate_post(client):
    from app.domain.literature_assistance.execution import run_assistance_task
    task = create(client, project(client)); budgets(client, task)
    provider = SyntheticProvider(pending=True)
    deferred = run_assistance_task(task['id'], task['revision'], provider_factory=lambda: provider)
    assert deferred['status'] == 'running', deferred
    provider.pending = False
    done = run_assistance_task(task['id'], deferred['revision'], provider_factory=lambda: provider)
    assert done['status'] == 'succeeded', done
    assert len(provider.posts) == len(provider.gets) == 1
    assert run_assistance_task(task['id'], done['revision'], provider_factory=lambda: provider) is None
    endpoint = f'/api/v1/projects/{task["project_id"]}/literature/assistance/tasks'
    result = client.get(endpoint + '/' + task['id']).json()['result']
    assert result['mesh_candidates'][0]['verified'] is False
    assert client.get(endpoint).json()['total'] == 1
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 1
        assert db.execute('SELECT count(*) AS n FROM budget_reservations').fetchone()['n'] > 0
        assert db.execute('SELECT count(*) AS n FROM usage_events').fetchone()['n'] > 0


@pytest.mark.parametrize('mode', ['no_budget', 'invalid', 'unknown', 'receipt_store_failure'])
def test_assistance_budget_and_invalid_or_unknown_output_never_publish(client, mode, monkeypatch):
    from app.domain.literature_assistance.execution import run_assistance_task
    task = create(client, project(client))
    if mode != 'no_budget': budgets(client, task)
    if mode=='receipt_store_failure':
        def fail_record(*args,**kwargs):raise OSError('Synthetic receipt persistence failure')
        monkeypatch.setattr('app.domain.model_usage.service.ModelUsageService.record_response',fail_record)
    provider = SyntheticProvider(invalid=mode == 'invalid', unknown=mode == 'unknown')
    result = run_assistance_task(task['id'], task['revision'], provider_factory=lambda: provider)
    assert result['status'] == ('failed' if mode == 'invalid' else 'waiting_confirmation'), result
    if mode == 'no_budget': assert not provider.posts
    with database_connection() as db:
        assert db.execute('SELECT result_json FROM literature_assistance_requests').fetchone()['result_json'] is None


def review_task(client):
    from tests.integration.test_literature_evidence import setup
    from tests.api.test_literature_evidence import post
    pid, path, claim, reference, quote = setup(client)
    saved = post(client,path+'/claims/'+claim['id']+'/evidence',quote,'assistance-quote')
    assert saved.status_code == 201,saved.text
    request = dict(kind='evidence_review',claim_id=claim['id'],claim_revision=1,
                   project_reference_id=reference['id'],evidence_ids=[saved.json()['id']],output_language='en')
    return create(client,pid,request),path,claim,request


def test_stale_claim_rejects_execution_before_model_and_old_task_remains_readable(client):
    from app.domain.literature_assistance.execution import run_assistance_task
    from tests.api.test_literature_evidence import post
    task,path,claim,request = review_task(client)
    revised = post(client,path+'/claims/'+claim['id']+'/versions',
        dict(expected_revision=1,content='New claim',context='',output_language='en'),'new-claim')
    assert revised.status_code == 201,revised.text
    provider = SyntheticProvider()
    result = run_assistance_task(task['id'],task['revision'],provider_factory=lambda:provider)
    assert result['status']=='failed' and result['error_code']=='task_source_conflict',result
    assert not provider.posts
    endpoint = f'/api/v1/projects/{task["project_id"]}/literature/assistance/tasks'
    assert client.get(endpoint+'/'+task['id']).status_code == 200
    replay = client.post(endpoint,json=request,headers={'Idempotency-Key':'assistance'})
    assert replay.status_code == 200 and replay.json()['id']==task['id']
    assert client.post(endpoint,json=request,headers={'Idempotency-Key':'stale-new-key'}).status_code==409
    workspace = client.get('/api/v1/tasks/'+task['id']+'/workspace')
    assert workspace.status_code==200,workspace.text
    assert workspace.json()['source']['is_current'] is False


def test_review_suggestion_bound_to_actual_quote_never_creates_manual_decision(client):
    from app.domain.literature_assistance.execution import run_assistance_task
    task,path,claim,request = review_task(client);budgets(client,task)
    provider = SyntheticProvider()
    original = provider.receipt
    def receipt():
        output = original()
        output['response']['output'][0]['content'][0]['text'] = json.dumps(dict(
            status='partial',relevance='related',reason='Saved synthetic abstract only',
            narrowed_statement='Synthetic bounded statement',limitations=['Abstract only'],evidence_ids=request['evidence_ids']))
        return output
    provider.receipt = receipt
    result = run_assistance_task(task['id'],task['revision'],provider_factory=lambda:provider)
    assert result['status']=='succeeded',result
    assert provider.posts[0]['material']['evidence'][0]['quote']=='Synthetic protocol fixture'
    assert client.get(path+'/claims/'+claim['id']+'/reviews').json()['total']==0
    from tests.api.test_literature_evidence import post
    revised=post(client,path+'/claims/'+claim['id']+'/versions',
        dict(expected_revision=1,content='Revised after model suggestion',context='',output_language='en'),'after-suggestion')
    assert revised.status_code==201,revised.text
    detail=client.get(f'/api/v1/projects/{task["project_id"]}/literature/assistance/tasks/{task["id"]}')
    assert detail.status_code==200,detail.text
    assert detail.json()['result']['evidence_ids']==request['evidence_ids']
    with database_connection() as db:
        from app.maintenance.literature_assistance_audit import audit_literature_assistance
        assert all(c['invalid']==0 for c in audit_literature_assistance(db))
    with database_connection(write=True) as db:
        db.execute("UPDATE model_calls SET input_digest=%s WHERE task_id=%s",('0'*64,task['id']))
    with database_connection() as db:
        assert audit_literature_assistance(db)[0]['invalid']==1


@pytest.mark.parametrize('mode',['foreign_output_id','source_changed','changed_during_call'])
def test_model_output_and_changed_sources_fail_closed(client,mode):
    from app.domain.literature_assistance.execution import run_assistance_task
    from tests.api.test_literature_evidence import post
    from psycopg.types.json import Jsonb
    task,path,claim,request=review_task(client);budgets(client,task)
    provider=SyntheticProvider()
    original=provider.receipt
    def receipt():
        value=original()
        ids=['invented'] if mode=='foreign_output_id' else request['evidence_ids']
        value['response']['output'][0]['content'][0]['text']=json.dumps(dict(status='supported',relevance='related',
            reason='Synthetic abstract',narrowed_statement='',limitations=['Abstract only'],evidence_ids=ids))
        if mode=='changed_during_call':
            response=post(client,path+'/claims/'+claim['id']+'/versions',
                dict(expected_revision=1,content='Concurrent revision',context='',output_language='en'),'concurrent')
            assert response.status_code==201,response.text
        return value
    provider.receipt=receipt
    if mode=='source_changed':
        with database_connection(write=True) as db:
            hit=db.execute('SELECT * FROM literature_search_hits WHERE project_reference_id=%s',(request['project_reference_id'],)).fetchone()
            value=dict(hit['record_json']);value['abstract']=[dict(label=None,text='Tampered content')]
            db.execute('UPDATE literature_search_hits SET record_json=%s WHERE id=%s',(Jsonb(value),hit['id']))
    result=run_assistance_task(task['id'],task['revision'],provider_factory=lambda:provider)
    assert result['status']=='failed',result
    assert result['error_code']==('literature_assistance_invalid' if mode=='foreign_output_id' else 'task_source_conflict'),result
    if mode=='source_changed':assert not provider.posts
    with database_connection() as db:
        assert db.execute('SELECT result_json FROM literature_assistance_requests').fetchone()['result_json'] is None


def test_cross_project_and_forged_evidence_request_rejected(client):
    task,path,claim,request = review_task(client)
    pid = task['project_id']
    endpoint = f'/api/v1/projects/{pid}/literature/assistance/tasks'
    assert client.post(endpoint,json={**request,'evidence_ids':['invented']},headers={'Idempotency-Key':'fake'}).status_code in (404,422)
    other = project(client,'thesis')
    assert client.get(endpoint.replace(pid,other)+'/'+task['id']).status_code==404
    assert client.post(endpoint,json={**body(),'extra':'forged'},headers={'Idempotency-Key':'extra'}).status_code==422
    assert client.post(endpoint,json={**request,'evidence_ids':request['evidence_ids']*2},headers={'Idempotency-Key':'duplicate'}).status_code==422


def test_assistance_finite_read_retries_never_repeat_post(client):
    from app.domain.literature_assistance.execution import run_assistance_task
    task = create(client,project(client));budgets(client,task)
    provider = SyntheticProvider(pending=True,get_failures=4)
    current = run_assistance_task(task['id'],task['revision'],provider_factory=lambda:provider)
    for count in range(1,5):
        current = run_assistance_task(task['id'],current['revision'],provider_factory=lambda:provider)
        assert current['retry_count']==min(count,3),current
    assert current['status']=='failed' and current['error_code']=='model_provider_unavailable',current
    assert len(provider.posts)==1 and len(provider.gets)==4


def test_budget_resume_and_worker_recovery_are_existing_task_operations(client):
    from app.domain.literature_assistance.execution import run_assistance_task
    from app.adapters.task_execution_store import TaskExecutionStore
    task = create(client,project(client));provider=SyntheticProvider()
    waiting=run_assistance_task(task['id'],task['revision'],provider_factory=lambda:provider)
    budgets(client,task)
    workspace=client.get('/api/v1/tasks/'+task['id']+'/workspace').json()
    resumed=client.post('/api/v1/tasks/'+task['id']+'/resume',json=dict(operation='resume',wait_id=workspace['wait']['id'],
        expected_task_revision=waiting['revision'],input_version=waiting['input_version']),headers={'Idempotency-Key':'budget-resume'})
    assert resumed.status_code==202,resumed.text
    assert run_assistance_task(task['id'],resumed.json()['revision'],provider_factory=lambda:provider)['status']=='succeeded'
    second=create(client,task['project_id'],key='worker-recovery')
    repository=TaskExecutionStore();lease=repository.claim(second['id'],second['revision'])
    assert lease is not None
    with database_connection(write=True) as db:
        db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s",(second['id'],))
    assert repository.recover_expired()==1
    recovered=client.get('/api/v1/tasks/'+second['id']).json()
    assert recovered['status']=='queued'
    assert run_assistance_task(second['id'],recovered['revision'])['status']=='waiting_confirmation'


def test_late_receipt_recovery_and_lease_loss_never_repeat_submission(client):
    from app.domain.literature_assistance.execution import run_assistance_task
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.domain.model_usage.service import ModelUsageService
    from tests.helpers.tasks import task_owner
    task=create(client,project(client));budgets(client,task)
    provider=SyntheticProvider(unknown=True)
    waiting=run_assistance_task(task['id'],task['revision'],provider_factory=lambda:provider)
    assert waiting['reason_code']=='submission_unknown'
    with database_connection() as db:
        call=db.execute('SELECT * FROM model_calls WHERE task_id=%s',(task['id'],)).fetchone()
    receipt=provider.receipt()
    service=ModelUsageService(task_owner(client))
    service.record_response(call['id'],event_key='late-synthetic-receipt',response_id=receipt['response_id'],
        model=receipt['model'],status=receipt['status'],usage=receipt['usage'],request_id=receipt['request_id'])
    repository=TaskExecutionStore()
    assert repository.recover_expired()==1
    task=client.get('/api/v1/tasks/'+task['id']).json()
    provider.unknown=False
    original=provider.receipt
    def expire():
        with database_connection(write=True) as db:
            db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s AND status='running'",(task['id'],))
        return original()
    provider.receipt=expire
    assert run_assistance_task(task['id'],task['revision'],provider_factory=lambda:provider) is None
    with database_connection() as db:
        assert db.execute('SELECT result_json FROM literature_assistance_requests').fetchone()['result_json'] is None
    provider.receipt=original
    assert repository.recover_expired()==1
    task=client.get('/api/v1/tasks/'+task['id']).json()
    done=run_assistance_task(task['id'],task['revision'],provider_factory=lambda:provider)
    assert done['status']=='succeeded',done
    assert len(provider.posts)==1


@pytest.mark.parametrize('scope',['projects','tasks'])
def test_completed_assistance_usage_is_readable_in_public_api(client,scope):
    from app.domain.literature_assistance.execution import run_assistance_task
    task=create(client,project(client));budgets(client,task)
    provider=SyntheticProvider()
    result=run_assistance_task(task['id'],task['revision'],provider_factory=lambda:provider)
    assert result['status']=='succeeded',result
    identity=task['project_id'] if scope=='projects' else task['id']
    response=client.get(f'/api/v1/{scope}/{identity}/model-usage')
    assert response.status_code==200,response.text
    usage=response.json()
    assert usage['total']==1 and usage['items'][0]['task_type']=='literature_assistance'
    assert usage['items'][0]['status']=='completed'
    assert usage['estimated_micro_usd']>0
