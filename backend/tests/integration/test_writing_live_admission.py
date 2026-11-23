from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
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

def prepare(client,bundle,task,lease=None):
    repository=TaskExecutionStore()
    if lease is None:
        lease=repository.claim(task['id'],task['revision'])
    assert lease is not None, task['id']
    with repository.connection() as db: running=repository.require_lease(db,lease)
    request=CallRequest(task_id=task['id'],expected_task_revision=running['revision'],call_key='manuscript-writing-v2',
        input_digest=bundle['gateway_digest'],policy=policy(),input_token_allowance=bundle['input_token_allowance'])
    return ModelUsageService(task_owner(client)),request,lease

def next_task(client,root,bundle,auth,index,logical='task-0'):
    request=request_v2(bundle,auth);request['logical_task_id']=logical
    response=post(client,root+'/writing-requests',request,'next-'+str(index));assert response.status_code==202,response.text
    return response.json()['task']

def reserve(args):
    service,request,lease=args
    return service.reserve_call(request,execution_lease=lease)


def start_and_finish(args):
    """A started call occupies its seat even if the returned manuscript is unusable."""
    service,request,lease=args
    call=reserve(args)
    assert service.begin_submission(call['id'],execution_lease=lease,expected_task_revision=request.expected_task_revision)
    TaskExecutionStore().fail(lease,'model_response_invalid')


def concurrent_last_seat(client,bundle,tasks):
    """Both workers arrive together; queued work retries once the serial head finishes."""
    start=Barrier(2)
    head_finished=Event()

    def attempt(task):
        repository=TaskExecutionStore()
        start.wait(timeout=10)
        lease=repository.claim(task['id'],task['revision'])
        if lease is None:
            assert head_finished.wait(timeout=30)
            lease=repository.claim(task['id'],task['revision'])
        assert lease is not None
        try:
            start_and_finish(prepare(client,bundle,task,lease))
            return 'reserved'
        except StorageError as exc:
            repository.fail(lease,exc.code)
            return exc.code
        finally:
            if task['id']==tasks[0]['id']:
                head_finished.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        return sorted(pool.map(attempt,tasks))

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
    start_and_finish(prepare(client,bundle,task))
    for i,logical in enumerate(('task-0','task-1','task-1','task-2')):
        start_and_finish(prepare(client,bundle,next_task(client,root,bundle,auth,i,logical)))
    contenders=[next_task(client,root,bundle,auth,i,'task-3') for i in (10,11)]
    assert concurrent_last_seat(client,bundle,contenders)==['manuscript_writing_not_authorized','reserved']
    assert client.get(path+'/'+auth['id']).json()['occupied_posts']==6

def settled_call(args,target_micro_usd):
    service,request,lease=args;call=reserve(args)
    rate=request.policy.price.output_micro_usd_per_million
    output_tokens=(target_micro_usd*1_000_000+rate-1)//rate
    charge=(output_tokens*rate+999_999)//1_000_000
    service.begin_submission(call['id'],execution_lease=lease,expected_task_revision=request.expected_task_revision)
    service.record_response(call['id'],event_key='oversized-fixture-usage',response_id='resp_fixture_usage',request_id='fixture',model=MODEL,status='completed',
        usage=dict(input_tokens=0,output_tokens=output_tokens,input_tokens_details=dict(cached_tokens=0,cache_write_tokens=0)))
    TaskExecutionStore().fail(lease,'model_response_invalid')
    return charge

def test_large_actual_usage_does_not_block_other_confirmed_writing_calls(client):
    root,bundle,path,auth,task=create_live(client)
    charge=settled_call(prepare(client,bundle,task),12_000_001)
    contenders=[next_task(client,root,bundle,auth,i) for i in (1,2)]
    assert concurrent_last_seat(client,bundle,contenders)==['reserved','reserved']
    view=client.get(path+'/'+auth['id']).json()
    assert view['occupied_micro_usd']==charge and view['occupied_posts']==3


def test_model_call_composite_fk_blocks_cross_project_admission_rebinding(client):
    from tests.api.test_manuscript_writing_live import preview,authorize
    other_root,other_bundle=preview(client);other_path,other_auth=authorize(client,other_root,other_bundle)
    root,bundle,path,auth,task=create_live(client);call=reserve(prepare(client,bundle,task))
    with pytest.raises(Exception):
        with database_connection(write=True) as db:
            db.execute('UPDATE manuscript_writing_call_admissions SET project_id=%s,bundle_id=%s,authorization_id=%s WHERE model_call_id=%s',
                (other_bundle['project_id'],other_bundle['id'],other_auth['id'],call['id']))
    with database_connection() as db:
        assert db.execute('SELECT project_id FROM manuscript_writing_call_admissions WHERE model_call_id=%s',(call['id'],)).fetchone()['project_id']==task['project_id']
