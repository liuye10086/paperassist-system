"""Isolated synthetic v2 consent and submission tests; never real provider evidence."""
import hashlib
import json
from copy import deepcopy
import pytest
from tests.api.test_manuscripts import client, setup, body
from tests.api.test_literature_evidence import post
from tests.integration.test_literature_assistance import budgets
from app.domain.tasks.execution import run_task
from app.domain.manuscript_writing.execution import run_manuscript_writing_task
from app.db.database import database_connection


def preview(client):
    path, _, _ = setup(client)
    manuscript = post(client, path, body(), 'base').json()
    assert run_task(manuscript['versions'][0]['task_id'], 1)['status'] == 'succeeded'
    root = path + '/' + manuscript['id']
    request = dict(schema_version=2, base_revision=1, mode='full_draft', output_language='en',
                   selected_source_ids=[], selected_evidence_ids=[])
    response = post(client, root + '/writing-previews', request, 'preview')
    assert response.status_code == 201, response.text
    return root, response.json()


def authorize(client, root, bundle, **extra):
    path = root.split('/manuscripts/')[0] + '/writing-authorizations'
    tasks = [dict(logical_task_id='task-'+str(i), bundles=[dict(bundle_id=bundle['id'], bundle_sha256=bundle['bundle_sha256'])]) for i in range(4)]
    response = post(client, path, dict(schema_version=2, confirmed=True, tasks=tasks, **extra), 'authorize')
    assert response.status_code == 201, response.text
    return path, response.json()


def request_v2(bundle, authorization):
    return dict(schema_version=2, bundle_id=bundle['id'], bundle_sha256=bundle['bundle_sha256'],
                authorization_id=authorization['id'], logical_task_id='task-0')


def test_preview_is_exact_minimal_and_does_not_create_model_call(client):
    root, bundle = preview(client)
    wire = bundle['wire_json']
    assert hashlib.sha256(wire.encode()).hexdigest() == bundle['wire_sha256'] == bundle['bundle_sha256']
    parsed = json.loads(wire)
    assert isinstance(parsed['input'], str)
    assert parsed['model'] == 'gpt-5.4-2026-03-05'
    assert parsed['max_output_tokens'] == 12000
    assert parsed['service_tier'] == 'default'
    assert parsed['text']['format']['strict'] is True
    assert bundle['input_token_allowance'] == len(wire.encode()) + 4096
    assert bundle['reserved_micro_usd'] <= 430000
    for excluded in ('base_snapshot', 'project_id', 'user_id', 'metadata_source', 'api_key', 'file_path'):
        assert excluded not in wire
    assert client.get(root + '/writing-previews/' + bundle['id']).json() == bundle
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0


def test_preview_rejects_private_posix_path_without_model_calls(client,monkeypatch):
    root,bundle=preview(client)
    def forbidden(*args,**kwargs): raise AssertionError('Preview must never construct provider')
    monkeypatch.setattr('app.domain.manuscript_writing.live_execution.create_production_provider',forbidden)
    request={**bundle['request_json'],'instructions':'请读取/data/private/patients.csv'}
    response=post(client,root+'/writing-previews',request,'blocked-path')
    assert response.status_code==422,response.text
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']==0
        assert db.execute('SELECT count(*) AS n FROM manuscript_writing_bundles').fetchone()['n']==1


@pytest.mark.parametrize('denial', ['missing', 'hash', 'closed', 'unapproved'])
def test_unauthorized_requests_never_create_calls(client, denial):
    root, bundle = preview(client)
    path, authorization = authorize(client, root, bundle)
    request = request_v2(bundle, authorization)
    if denial == 'missing': request['authorization_id'] = 'missing'
    if denial == 'hash': request['bundle_sha256'] = '0' * 64
    if denial == 'closed': assert post(client, path + '/' + authorization['id'] + '/close', {}, 'close').status_code == 200
    if denial == 'unapproved': request['logical_task_id'] = 'unknown'
    response = post(client, root + '/writing-requests', request, 'write')
    assert response.status_code in (403, 404, 409), response.text
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0


class LiveFixture:
    source_kind = 'synthetic_fixture'
    def __init__(self, pending=False, unknown=False, model=None, usage=True):
        self.posts=[]; self.gets=[]; self.pending=pending; self.unknown=unknown; self.model=model; self.usage=usage
    def create_frozen(self, *, wire_json):
        self.posts.append(wire_json)
        if self.unknown: raise TimeoutError()
        return self.receipt()
    def retrieve(self, response_id, *, policy):
        self.gets.append(response_id)
        return self.receipt()
    def receipt(self):
        from app.domain.manuscript_writing.policy import MODEL
        output={'sections':[{'id':s,'paragraphs':[dict(id=s+':1', text='Synthetic candidate needs review.',source_aliases=[],evidence_aliases=[],study_numeric_bindings=[])]} for s in ('title','abstract','introduction','results','discussion','materials_and_methods')]}
        status='in_progress' if self.pending else 'completed'
        return dict(response_id='resp_fixture_'+str(id(self)),request_id='fixture',model=self.model or MODEL,status=status,
            usage=dict(input_tokens=100, output_tokens=100, input_tokens_details=dict(cached_tokens=0)) if self.usage else None,
            response=dict(status=status,output=[dict(type='message',content=[dict(type='output_text',text=json.dumps(output))])]))
    def close(self): pass


def create_live(client):
    root, bundle=preview(client);path, auth=authorize(client,root,bundle)
    response=post(client,root+'/writing-requests',request_v2(bundle,auth),'live')
    assert response.status_code==202,response.text
    task=response.json()['task'];budgets(client,task)
    return root,bundle,path,auth,task


def test_live_candidate_is_synthetic_pending_and_publication_is_blocked(client):
    root,bundle,path,auth,task=create_live(client);provider=LiveFixture()
    result=run_manuscript_writing_task(task['id'],task['revision'],provider=provider)
    assert result['status']=='succeeded',result
    assert provider.posts==[bundle['wire_json']]
    view=client.get(root+'/writing-requests/'+task['id']).json()
    assert view['candidate']['writing_provenance']['verification_status']=='pending'
    assert view['candidate']['writing_provenance']['provider_provenance']=='synthetic_fixture'
    published=post(client,root+'/writing-requests/'+task['id']+'/publish',dict(expected_revision=1),'publish')
    assert published.status_code==409,published.text
    with database_connection() as db:
        row=db.execute('SELECT * FROM manuscript_writing_call_admissions').fetchone()
        assert row['status']=='submission_started'


def test_closed_authorization_allows_saved_get_without_another_post(client):
    root,bundle,path,auth,task=create_live(client);provider=LiveFixture(pending=True)
    running=run_manuscript_writing_task(task['id'],task['revision'],provider=provider)
    assert running['status']=='running',running
    post(client,path+'/'+auth['id']+'/close',{},'close');provider.pending=False
    result=run_manuscript_writing_task(task['id'],running['revision'],provider=provider)
    assert result['status']=='succeeded',result
    assert len(provider.posts)==len(provider.gets)==1


def test_unknown_submission_never_reposts_or_releases_budget(client):
    root,bundle,path,auth,task=create_live(client);provider=LiveFixture(unknown=True)
    result=run_manuscript_writing_task(task['id'],task['revision'],provider=provider)
    assert result['reason_code']=='submission_unknown',result
    run_manuscript_writing_task(task['id'],result['revision'],provider=provider)
    assert len(provider.posts)==1
    with database_connection() as db:
        assert db.execute("SELECT status FROM budget_reservations LIMIT 1").fetchone()['status']=='held'


@pytest.mark.parametrize('mode',['missing_usage','wrong_model','invalid_cached'])
def test_uncertain_receipt_keeps_reservation_and_model_mismatch_has_no_candidate(client,mode):
    root,bundle,path,auth,task=create_live(client)
    provider=LiveFixture(model='different-model' if mode=='wrong_model' else None,usage=mode!='missing_usage')
    original=provider.receipt
    def receipt():
        value=original()
        if mode=='invalid_cached': value['usage']['input_tokens_details']['cached_tokens']=999
        return value
    provider.receipt=receipt
    result=run_manuscript_writing_task(task['id'],task['revision'],provider=provider)
    if mode=='wrong_model':
        assert result['status']=='failed',result
        assert client.get(root+'/writing-requests/'+task['id']).json()['candidate'] is None
    with database_connection() as db:
        call=db.execute('SELECT * FROM model_calls').fetchone()
        assert call['usage_status']=='pending' and call['estimated_cost_micro_usd'] is None
        assert db.execute('SELECT status FROM budget_reservations LIMIT 1').fetchone()['status']=='held'
    assert client.get(path+'/'+auth['id']).json()['occupied_micro_usd']==bundle['reserved_micro_usd']


def test_default_v2_never_uses_environment_key_in_test(client,monkeypatch):
    root,bundle,path,auth,task=create_live(client)
    monkeypatch.setenv('PAPERASSIST_WRITING_LIVE_ENABLED','1');monkeypatch.setenv('OPENAI_API_KEY','synthetic-not-real')
    result=run_manuscript_writing_task(task['id'],task['revision'])
    assert result['status']=='waiting_confirmation'
    assert client.get(root+'/writing-previews').json()['capabilities']['real_calls_enabled'] is False
    with database_connection() as db: assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']==0


def test_v2_saved_call_has_trusted_synthetic_label_before_candidate_exists(client):
    root,bundle,path,auth,task=create_live(client);provider=LiveFixture(pending=True)
    run_manuscript_writing_task(task['id'],task['revision'],provider=provider)
    view=client.get(root+'/writing-requests/'+task['id']).json()
    assert view['candidate'] is None
    assert view['model_calls'][0]['provider_provenance']=='synthetic_fixture'


def test_source_revision_changed_after_preview_rejects_before_call(client):
    root,bundle,path,auth,task=create_live(client)
    new=post(client,root+'/versions',body(expected_revision=1),'change')
    assert new.status_code==201,new.text
    provider=LiveFixture();result=run_manuscript_writing_task(task['id'],task['revision'],provider=provider)
    assert result['status']=='failed' and not provider.posts
    with database_connection() as db: assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']==0


def test_cross_project_and_user_bundle_authorizations_are_denied(client,postgres_schema):
    from app.domain.manuscript_writing.authorization import LiveWritingService
    from app.domain.report_collections.service import scoped_store
    from app.core.exceptions import StorageError
    root,bundle,path,auth,task=create_live(client)
    other_root,other_bundle=preview(client)
    response=post(client,other_root+'/writing-requests',request_v2(bundle,auth),'foreign')
    assert response.status_code==409,response.text
    foreign=LiveWritingService(scoped_store('unrelated-user',postgres_schema))
    with pytest.raises(StorageError): foreign.get_preview(task['project_id'],bundle['manuscript_id'],bundle['id'])
    with pytest.raises(StorageError): foreign.get_authorization(task['project_id'],auth['id'])


def test_unapproved_new_bundle_is_not_covered_by_remaining_corrections(client):
    root,bundle,path,auth,task=create_live(client)
    data=deepcopy(bundle['request_json']);data['instructions']='A new correction prompt'
    other=post(client,root+'/writing-previews',data,'new-preview')
    assert other.status_code==201,other.text
    response=post(client,root+'/writing-requests',request_v2(other.json(),auth),'new-correction')
    assert response.status_code==409,response.text


def test_pending_candidate_cannot_claim_live_provenance_from_fixture(client):
    from psycopg.types.json import Jsonb
    from app.domain.literature.service import digest
    root,bundle,path,auth,task=create_live(client);provider=LiveFixture()
    assert run_manuscript_writing_task(task['id'],task['revision'],provider=provider)['status']=='succeeded'
    with database_connection(write=True) as db:
        row=db.execute('SELECT candidate_json FROM manuscript_writing_requests WHERE task_id=%s',(task['id'],)).fetchone()
        candidate=row['candidate_json'];candidate['writing_provenance']['provider_provenance']='openai_live'
        db.execute('UPDATE manuscript_writing_requests SET candidate_json=%s,candidate_sha256=%s WHERE task_id=%s',(Jsonb(candidate),digest(candidate),task['id']))
    assert client.get(root+'/writing-requests/'+task['id']).status_code==409


def test_changed_selected_source_after_authorization_causes_zero_posts(client):
    path,_,file=setup(client)
    data=body(sources=[dict(kind='original',id=file['id'],file_id=file['id'],role='methods')])
    manuscript=post(client,path,data,'base').json();version=manuscript['versions'][0]
    assert run_task(version['task_id'],1)['status']=='succeeded'
    root=path+'/'+manuscript['id']
    response=post(client,root+'/writing-previews',dict(schema_version=2,base_revision=1,mode='full_draft',output_language='en',selected_source_ids=[file['id']],selected_evidence_ids=[]),'preview')
    assert response.status_code==201,response.text
    bundle=response.json();auth_path,auth=authorize(client,root,bundle)
    response=post(client,root+'/writing-requests',request_v2(bundle,auth),'write');assert response.status_code==202,response.text
    task=response.json()['task'];budgets(client,task)
    with database_connection(write=True) as db: db.execute('UPDATE files SET sha256=%s WHERE id=%s',('0'*64,file['id']))
    provider=LiveFixture();result=run_manuscript_writing_task(task['id'],task['revision'],provider=provider)
    assert result['status']=='failed' and not provider.posts
    with database_connection() as db: assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']==0


def test_receipt_storage_failure_and_expired_lease_never_repeat_post(client,monkeypatch):
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.domain.model_usage.service import ModelUsageService
    root,bundle,path,auth,task=create_live(client);provider=LiveFixture()
    def fail(*args,**kwargs): raise RuntimeError('fixture persistence failure')
    monkeypatch.setattr(ModelUsageService,'record_response',fail)
    result=run_manuscript_writing_task(task['id'],task['revision'],provider=provider)
    assert result['reason_code']=='submission_unknown'
    run_manuscript_writing_task(task['id'],result['revision'],provider=provider)
    assert len(provider.posts)==1


def test_crashed_worker_after_begin_is_unknown_and_never_resubmits(client):
    from tests.integration.test_writing_live_admission import prepare,reserve
    from app.adapters.task_execution_store import TaskExecutionStore
    root,bundle,path,auth,task=create_live(client);args=prepare(client,bundle,task);service,request,lease=args
    call=reserve(args);assert service.begin_submission(call['id'],execution_lease=lease,expected_task_revision=request.expected_task_revision)
    with database_connection(write=True) as db: db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s",(task['id'],))
    assert TaskExecutionStore().recover_expired()==1
    current=client.get('/api/v1/tasks/'+task['id']).json()
    assert current['reason_code']=='submission_unknown',current
    provider=LiveFixture();run_manuscript_writing_task(task['id'],current['revision'],provider=provider)
    assert not provider.posts


@pytest.mark.parametrize('mutation',['verified','unknown_evidence','unknown_source','invented_numeric','unknown_figure','references'])
def test_untrusted_model_flags_aliases_and_numbers_never_form_candidate(client,mutation):
    root,bundle,path,auth,task=create_live(client);provider=LiveFixture();original=provider.receipt
    def receipt():
        result=original();value=json.loads(result['response']['output'][0]['content'][0]['text']);p=value['sections'][0]['paragraphs'][0]
        if mutation=='verified': p['verified']=True
        if mutation=='unknown_evidence': p['evidence_aliases']=['unknown']
        if mutation=='unknown_source': p['source_aliases']=['unknown']
        if mutation=='invented_numeric': p['text']='Invented n=999'
        if mutation=='unknown_figure': p['text']='See Figure 999.'
        if mutation=='references': value['sections'][-1]['id']='references'
        result['response']['output'][0]['content'][0]['text']=json.dumps(value);return result
    provider.receipt=receipt
    result=run_manuscript_writing_task(task['id'],task['revision'],provider=provider)
    assert result['status']=='failed',result
    assert client.get(root+'/writing-requests/'+task['id']).json()['candidate'] is None


def test_preapproved_known_correction_bundle_uses_same_logical_task_budget(client):
    from app.domain.model_usage.service import ModelUsageService
    from tests.helpers.tasks import task_owner
    root,bundle=preview(client)
    data=deepcopy(bundle['request_json']);data['instructions']='Tighten facts, structure and limitations using these same materials.'
    correction=post(client,root+'/writing-previews',data,'known-correction').json()
    tasks=[dict(logical_task_id='task-'+str(i),bundles=[dict(bundle_id=bundle['id'],bundle_sha256=bundle['bundle_sha256'])]) for i in range(4)]
    tasks[0]['bundles'].append(dict(bundle_id=correction['id'],bundle_sha256=correction['bundle_sha256']))
    path=root.split('/manuscripts/')[0]+'/writing-authorizations'
    response=post(client,path,dict(schema_version=2,confirmed=True,tasks=tasks),'approve-known-materials')
    assert response.status_code==201,response.text
    auth=response.json()
    for i,selected in enumerate((bundle,correction)):
        response=post(client,root+'/writing-requests',request_v2(selected,auth),'explicit-'+str(i));assert response.status_code==202,response.text
        task=response.json()['task']
        if i==0: budgets(client,task)
        else: ModelUsageService(task_owner(client)).set_budget('task',task['id'],5000000,0)
        provider=LiveFixture();assert run_manuscript_writing_task(task['id'],task['revision'],provider=provider)['status']=='succeeded'
        assert provider.posts==[selected['wire_json']]
    view=client.get(path+'/'+auth['id']).json()
    assert view['occupied_posts']==2
    assert view['logical_task_usage'][0]['occupied_posts']==2
