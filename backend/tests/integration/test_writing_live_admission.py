from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from tests.api.test_manuscripts import client
from tests.api.test_manuscript_writing_live import create_live,request_v2
from tests.api.test_literature_evidence import post
from tests.helpers.tasks import task_owner
from app.adapters.task_execution_store import TaskExecutionStore
from app.domain.model_usage.service import ModelUsageService
from app.domain.model_usage.contracts import CallRequest
from app.domain.manuscript_writing.policy import policy,MODEL
from app.core.exceptions import StorageError
from app.db.database import database_connection,migration_connection

def prepare(client,bundle,task):
    repository=TaskExecutionStore();lease=repository.claim(task['id'],task['revision'])
    with repository.connection() as db: running=repository.require_lease(db,lease)
    request=CallRequest(task_id=task['id'],expected_task_revision=running['revision'],call_key='manuscript-writing-v2',
        input_digest=bundle['gateway_digest'],policy=policy(),input_token_allowance=bundle['input_token_allowance'])
    return ModelUsageService(task_owner(client)),request,lease

def next_task(client,root,bundle,auth,index,logical='task-0'):
    request=request_v2(bundle,auth);request['logical_task_id']=logical
    response=post(client,root+'/writing-requests',request,'next-'+str(index));assert response.status_code==202,response.text
    task=response.json()['task'];service=ModelUsageService(task_owner(client));service.set_budget('task',task['id'],5000000,0)
    return task

def reserve(args):
    service,request,lease=args
    return service.reserve_call(request,execution_lease=lease)

def test_closed_between_reserve_and_begin_blocks_and_reserved_seat_can_release(client):
    root,bundle,path,auth,task=create_live(client);args=prepare(client,bundle,task);service,request,lease=args;call=reserve(args)
    assert reserve(args)['id']==call['id']
    post(client,path+'/'+auth['id']+'/close',{},'close')
    with pytest.raises(StorageError): service.begin_submission(call['id'],execution_lease=lease,expected_task_revision=request.expected_task_revision)
    service.release_unsubmitted(call['id'],event_key='release',reason_code='cancelled')
    assert client.get(path+'/'+auth['id']).json()['occupied_posts']==0

def test_started_seat_cannot_release_after_close(client):
    root,bundle,path,auth,task=create_live(client);args=prepare(client,bundle,task);service,request,lease=args;call=reserve(args)
    assert service.begin_submission(call['id'],execution_lease=lease,expected_task_revision=request.expected_task_revision)
    post(client,path+'/'+auth['id']+'/close',{},'close')
    with pytest.raises(StorageError): service.release_unsubmitted(call['id'],event_key='release',reason_code='cancelled')
    assert client.get(path+'/'+auth['id']).json()['occupied_posts']==1

def test_admission_insert_failure_rolls_back_call_and_all_budget_reservations(client):
    root,bundle,path,auth,task=create_live(client);args=prepare(client,bundle,task)
    with migration_connection(write=True) as db:
        db.execute("CREATE FUNCTION reject_live_admission() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'fixture rejection'; END $$")
        db.execute('CREATE TRIGGER reject_live_admission BEFORE INSERT ON manuscript_writing_call_admissions FOR EACH ROW EXECUTE FUNCTION reject_live_admission()')
    try:
        with pytest.raises(Exception): reserve(args)
        with database_connection() as db:
            assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']==0
            assert db.execute('SELECT count(*) AS n FROM budget_reservations').fetchone()['n']==0
    finally:
        with migration_connection(write=True) as db:
            db.execute('DROP TRIGGER reject_live_admission ON manuscript_writing_call_admissions');db.execute('DROP FUNCTION reject_live_admission()')

def test_six_posts_four_tasks_and_two_corrections_last_seat_concurrent(client):
    root,bundle,path,auth,task=create_live(client)
    reserve(prepare(client,bundle,task))
    for i,logical in enumerate(('task-0','task-1','task-1','task-2')):
        reserve(prepare(client,bundle,next_task(client,root,bundle,auth,i,logical)))
    contenders=[prepare(client,bundle,next_task(client,root,bundle,auth,i,'task-3')) for i in (10,11)]
    barrier=Barrier(2)
    def attempt(args):
        barrier.wait()
        try: reserve(args);return 'reserved'
        except StorageError as exc: return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(attempt,contenders))
    assert sorted(results)==['model_budget_exceeded','reserved']
    assert client.get(path+'/'+auth['id']).json()['occupied_posts']==6

def settled_call(args,output_tokens):
    service,request,lease=args;call=reserve(args)
    service.begin_submission(call['id'],execution_lease=lease,expected_task_revision=request.expected_task_revision)
    service.record_response(call['id'],event_key='oversized-fixture-usage',response_id='resp_fixture_usage',request_id='fixture',model=MODEL,status='completed',
        usage=dict(input_tokens=0,output_tokens=output_tokens,input_tokens_details=dict(cached_tokens=0,cache_write_tokens=0)))
    return call

def test_logical_task_actual_cost_accumulates_across_new_tasks_and_parallel_last_budget(client):
    root,bundle,path,auth,task=create_live(client)
    settled_call(prepare(client,bundle,task),175000)
    contenders=[prepare(client,bundle,next_task(client,root,bundle,auth,i)) for i in (1,2)]
    barrier=Barrier(2)
    def attempt(args):
        barrier.wait()
        try: reserve(args);return 'reserved'
        except StorageError as exc: return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(attempt,contenders))
    assert sorted(results)==['model_budget_exceeded','reserved']
    view=client.get(path+'/'+auth['id']).json()
    assert view['occupied_micro_usd']==2625000+bundle['reserved_micro_usd']

def test_actual_over_logical_cap_is_preserved_and_blocks_next_task(client):
    root,bundle,path,auth,task=create_live(client)
    settled_call(prepare(client,bundle,task),210000)
    assert client.get(path+'/'+auth['id']).json()['occupied_micro_usd']==3150000
    with pytest.raises(StorageError) as error:
        reserve(prepare(client,bundle,next_task(client,root,bundle,auth,1)))
    assert error.value.code=='model_budget_exceeded'

def test_model_call_composite_fk_blocks_cross_project_admission_rebinding(client):
    from tests.api.test_manuscript_writing_live import preview,authorize
    root,bundle,path,auth,task=create_live(client);call=reserve(prepare(client,bundle,task))
    other_root,other_bundle=preview(client);other_path,other_auth=authorize(client,other_root,other_bundle)
    with pytest.raises(Exception):
        with database_connection(write=True) as db:
            db.execute('UPDATE manuscript_writing_call_admissions SET project_id=%s,bundle_id=%s,authorization_id=%s WHERE model_call_id=%s',
                (other_bundle['project_id'],other_bundle['id'],other_auth['id'],call['id']))
    with database_connection() as db:
        assert db.execute('SELECT project_id FROM manuscript_writing_call_admissions WHERE model_call_id=%s',(call['id'],)).fetchone()['project_id']==task['project_id']
