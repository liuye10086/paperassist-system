"""Synthetic-only engineering checks; these are not scientific writing validation."""
from copy import deepcopy
import json
import pytest

from tests.api.test_manuscripts import client,setup,body
from tests.api.test_literature_evidence import post
from tests.integration.test_literature_assistance import SyntheticProvider,budgets
from app.domain.tasks.execution import run_task
from app.domain.manuscript_writing.execution import run_manuscript_writing_task
from app.db.database import database_connection


def create(client):
    path,_,_=setup(client)
    manuscript=post(client,path,body(),'base').json();version=manuscript['versions'][0]
    assert run_task(version['task_id'],1)['status']=='succeeded'
    endpoint=path+'/'+manuscript['id']+'/writing-requests'
    response=post(client,endpoint,dict(base_revision=1,mode='full_draft',instructions='Only synthetic engineering prose',keywords=[],acknowledgements=''),'write')
    assert response.status_code==202,response.text
    return response.json()['task'],endpoint


class WritingProvider(SyntheticProvider):
    policy=deepcopy(SyntheticProvider.policy)|{'prompt_version':'sci-writing-v1'}

    def create(self,*,policy,instructions,payload):
        self.payload=payload
        return super().create(policy=policy,instructions=instructions,payload=payload)

    def receipt(self):
        receipt=super().receipt()
        sections=deepcopy(self.payload['normalized_sections'])
        for section in sections:
            if section['id'] in ('title','references'): continue
            section['paragraphs']=[dict(id='writing:'+section['id']+':1',text='Synthetic prose. Missing study facts require verification.',source_ids=[],citations=[],numeric_bindings=[])]
        if self.invalid: sections[4]['paragraphs'][0]['text']='Invented n = 999'
        receipt['response']['output'][0]['content'][0]['text']=json.dumps({'sections':sections})
        return receipt


def test_default_writer_waits_without_budget_or_provider_calls(client):
    task,endpoint=create(client)
    result=run_manuscript_writing_task(task['id'],task['revision'])
    assert result['status']=='waiting_confirmation',result
    assert result['error_code']=='manuscript_writing_not_authorized',result
    view=client.get(endpoint+'/'+task['id']).json()
    assert view['candidate'] is None and view['real_calls_enabled'] is False
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']==0


def test_synthetic_async_writer_uses_one_submission_and_persists_traceable_candidate(client):
    task,endpoint=create(client);budgets(client,task);provider=WritingProvider(pending=True)
    waiting=run_manuscript_writing_task(task['id'],task['revision'],provider=provider)
    assert waiting['status']=='running',waiting
    provider.pending=False
    result=run_manuscript_writing_task(task['id'],waiting['revision'],provider=provider)
    assert result['status']=='succeeded',result
    assert len(provider.posts)==len(provider.gets)==1
    candidate=client.get(endpoint+'/'+task['id']).json()['candidate']
    assert candidate['writing_provenance']['model_call_id']
    assert candidate['writing_provenance']['verification_status']=='not_verified'
    for usage_path in ('/api/v1/projects/'+task['project_id']+'/model-usage','/api/v1/tasks/'+task['id']+'/model-usage'):
        usage=client.get(usage_path)
        assert usage.status_code==200,usage.text
        assert usage.json()['items'][0]['task_type']=='manuscript_writing'
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']==1
        assert db.execute('SELECT count(*) AS n FROM budget_reservations').fetchone()['n']>0
        assert db.execute('SELECT count(*) AS n FROM usage_events').fetchone()['n']>0


def test_source_changed_between_slices_retrieves_and_accounts_original_response(client):
    task,endpoint=create(client);budgets(client,task);provider=WritingProvider(pending=True)
    original=provider.receipt
    def complete_usage():
        receipt=original();receipt['usage']['input_tokens_details']['cache_write_tokens']=0
        return receipt
    provider.receipt=complete_usage
    pending=run_manuscript_writing_task(task['id'],task['revision'],provider=provider)
    changed=post(client,endpoint.rsplit('/writing-requests',1)[0]+'/versions',body(expected_revision=1),'change-after-post')
    assert changed.status_code==201,changed.text
    still_pending=run_manuscript_writing_task(task['id'],pending['revision'],provider=provider)
    assert still_pending['status']=='running' and len(provider.gets)==1
    provider.pending=False
    failed=run_manuscript_writing_task(task['id'],still_pending['revision'],provider=provider)
    assert failed['status']=='failed' and failed['error_code']=='task_source_conflict'
    assert len(provider.posts)==1 and len(provider.gets)==2
    with database_connection() as db:
        call=db.execute('SELECT * FROM model_calls WHERE task_id=%s',(task['id'],)).fetchone()
        assert provider.gets==[call['provider_response_id']]*2
        assert call['status']=='completed' and call['usage_status']=='estimated'
        assert {r['status'] for r in db.execute('SELECT status FROM budget_reservations WHERE call_id=%s',(call['id'],))}=={'settled'}
        assert db.execute('SELECT candidate_json FROM manuscript_writing_requests WHERE task_id=%s',(task['id'],)).fetchone()['candidate_json'] is None


@pytest.mark.parametrize('mode',['invalid','unknown','no_budget'])
def test_invalid_unknown_and_no_budget_never_publish(client,mode):
    task,endpoint=create(client)
    if mode!='no_budget': budgets(client,task)
    provider=WritingProvider(invalid=mode=='invalid',unknown=mode=='unknown')
    result=run_manuscript_writing_task(task['id'],task['revision'],provider=provider)
    assert result['status']==('failed' if mode=='invalid' else 'waiting_confirmation'),result
    assert client.get(endpoint+'/'+task['id']).json()['candidate'] is None
    if mode=='no_budget': assert not provider.posts
    if mode=='unknown':
        assert result['reason_code']=='submission_unknown'
        assert run_manuscript_writing_task(task['id'],result['revision'],provider=provider) is None
        assert len(provider.posts)==1


def test_budget_wait_can_resume_after_explicit_budget_is_available(client):
    task,_=create(client);provider=WritingProvider()
    waiting=run_manuscript_writing_task(task['id'],task['revision'],provider=provider)
    assert waiting['reason_code']=='budget_exceeded'
    budgets(client,task)
    workspace=client.get('/api/v1/tasks/'+task['id']+'/workspace').json()
    response=client.post('/api/v1/tasks/'+task['id']+'/resume',json=dict(operation='resume',wait_id=workspace['wait']['id'],expected_task_revision=waiting['revision'],input_version=waiting['input_version']),headers={'Idempotency-Key':'resume'})
    assert response.status_code==202,response.text
    assert run_manuscript_writing_task(task['id'],response.json()['revision'],provider=provider)['status']=='succeeded'
    assert len(provider.posts)==1


def test_finite_get_retries_and_manual_recovery_never_repeat_submission(client):
    task,_=create(client);budgets(client,task)
    provider=WritingProvider(pending=True,get_failures=4)
    current=run_manuscript_writing_task(task['id'],task['revision'],provider=provider)
    provider.pending=False
    for count in range(1,5):
        current=run_manuscript_writing_task(task['id'],current['revision'],provider=provider)
        assert current['retry_count']==min(count,3),current
    assert current['status']=='failed' and current['error_code']=='model_provider_unavailable',current
    response=client.post('/api/v1/tasks/'+task['id']+'/retry',json={'expected_revision':current['revision']})
    assert response.status_code==202,response.text
    done=run_manuscript_writing_task(task['id'],response.json()['revision'],provider=provider)
    assert done['status']=='succeeded',done
    assert len(provider.posts)==1 and len(provider.gets)==5


def test_expired_worker_lease_recovers_without_external_provider(client):
    from app.adapters.task_execution_store import TaskExecutionStore
    task,_=create(client);repository=TaskExecutionStore()
    assert repository.claim(task['id'],task['revision']) is not None
    with database_connection(write=True) as db:
        db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s",(task['id'],))
    assert repository.recover_expired()==1
    task=client.get('/api/v1/tasks/'+task['id']).json()
    assert task['status']=='queued'
    assert run_manuscript_writing_task(task['id'],task['revision'])['status']=='waiting_confirmation'


def test_injected_provider_must_be_explicit_synthetic_fixture(client):
    from app.core.exceptions import StorageError
    task,_=create(client);provider=WritingProvider();provider.source_kind='untrusted'
    with pytest.raises(StorageError,match='仅隔离测试'):
        run_manuscript_writing_task(task['id'],task['revision'],provider=provider)
    assert not provider.posts

def test_expired_observation_resume_retrieves_saved_response_once_without_new_budget(client):
    from datetime import datetime,timedelta,timezone
    from psycopg.types.json import Jsonb
    from app.domain.model_usage.observation import consume_grant
    from app.domain.model_usage.service import ModelUsageService
    task,_=create(client);budgets(client,task);provider=WritingProvider(pending=True)
    running=run_manuscript_writing_task(task['id'],task['revision'],provider=provider)
    with database_connection(write=True) as db:
        call=db.execute('SELECT * FROM model_calls WHERE task_id=%s',(task['id'],)).fetchone()
        state=deepcopy(call['provider_state']);past=datetime.now(timezone.utc)-timedelta(hours=1)
        state['observation'].update(started_at=(past-timedelta(minutes=20)).isoformat(),deadline_at=past.isoformat())
        db.execute('UPDATE model_calls SET provider_state=%s WHERE id=%s',(Jsonb(state),call['id']))
        before=db.execute('SELECT count(*) AS n FROM budget_reservations').fetchone()['n']
    waiting=run_manuscript_writing_task(task['id'],running['revision'],provider=provider)
    assert waiting['reason_code']=='observation_expired',waiting
    workspace=client.get('/api/v1/tasks/'+task['id']+'/workspace')
    assert workspace.status_code==200,workspace.text
    workspace=workspace.json()
    assert workspace['allowed_actions']==['resume'],workspace
    assert workspace['wait']['kind']=='remote_observation'
    resumed=client.post('/api/v1/tasks/'+task['id']+'/resume',json=dict(operation='resume',wait_id=workspace['wait']['id'],expected_task_revision=waiting['revision'],input_version=waiting['input_version']),headers={'Idempotency-Key':'observe-original'})
    assert resumed.status_code==202,resumed.text
    provider.pending=False
    done=run_manuscript_writing_task(task['id'],resumed.json()['revision'],provider=provider)
    assert done['status']=='succeeded',done
    assert len(provider.posts)==1 and len(provider.gets)==1
    with database_connection() as db:
        fresh=db.execute('SELECT * FROM model_calls WHERE id=%s',(call['id'],)).fetchone()
        assert fresh['provider_response_id']==call['provider_response_id']
        assert fresh['provider_state']['observation']['retrieval_grant']['consumed_at'] is not None
        assert db.execute('SELECT count(*) AS n FROM budget_reservations').fetchone()['n']==before
    assert consume_grant(ModelUsageService(call['user_id']).store,call['id'],call['provider_response_id']) is False
