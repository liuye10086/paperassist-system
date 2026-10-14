import pytest
from tests.api.test_projects import client  # noqa: F401
from tests.api.test_ocr_versions import uploaded_image
from tests.helpers.ocr_samples import ocr_result


def setup_review(client):
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    project, _, _, item, raw = uploaded_image(client)
    assert run_parse_file_task(item['task']['id'], 1, parser=ocr_result)['status'] == 'succeeded'
    base = f"/api/v1/projects/{project['id']}/files/{item['file_id']}"
    parent = client.get(base+'/document-versions').json()['items'][0]
    response = client.post(base+'/ocr-reviews', json={'parse_id':parent['id']}, headers={'Idempotency-Key':'create'})
    assert response.status_code == 202, response.text
    return project, base, parent, response.json(), raw


def execute(task):
    from app.domain.tasks.ocr_review_execution import run_ocr_review_task
    return run_ocr_review_task(task['id'], task['revision'])


def decide(client, view, operation, key, edits=None):
    body = dict(operation=operation, wait_id=view['wait']['id'], checkpoint_id=view['checkpoint_id'],
        expected_task_revision=view['task']['revision'], input_version=view['task']['input_version'])
    if edits is not None: body['edits'] = edits
    return client.post('/api/v1/tasks/'+view['task']['id']+'/ocr-review/decision', json=body,
        headers={'Idempotency-Key':key})


def test_persisted_progress_approval_publication_and_history(client):
    from app.db.database import database_connection
    from app.maintenance.database_audit import audit_database
    project, base, parent, task, raw = setup_review(client)
    original = client.get(parent['download_url']).content
    url = '/api/v1/tasks/'+task['id']+'/ocr-review'
    assert client.get(url).json()['summary'] is None
    assert execute(task)['status'] == 'waiting_confirmation'
    view = client.get(url).json()
    assert view['summary']['unreviewed_blocks'] == 1
    assert decide(client,view,'approve','premature').status_code == 422
    edits = [dict(block_id='text-1',action='replace_text',text='001.20 mg/mL')]
    response = decide(client,view,'revise','save',edits)
    assert response.status_code == 202,response.text
    assert decide(client,view,'revise','save',edits).json() == response.json()
    assert decide(client,view,'revise','stale',edits).status_code == 409
    assert execute(response.json())['status'] == 'waiting_confirmation'
    view = client.get(url).json()
    assert view['edits'] == edits and view['edit_revision'] == 2
    assert view['summary']['corrected_blocks'] == 1
    with database_connection() as db:
        assert db.execute("SELECT count(*) AS n FROM task_attempts WHERE task_id=%s AND status='running'",(task['id'],)).fetchone()['n'] == 0
        assert db.execute('SELECT lease_owner FROM task_attempts WHERE task_id=%s ORDER BY attempt_no DESC LIMIT 1',(task['id'],)).fetchone()['lease_owner'] is None
    approved = decide(client,view,'approve','approve')
    assert approved.status_code == 202,approved.text
    assert execute(approved.json())['status'] == 'succeeded'
    result = client.get(url).json()['result']
    assert set(result)=={'id','file_id','parent_parse_id','parent_parse_version','version','created_at','task_id','source','summary','download_url'}
    saved = client.get(result['download_url'])
    assert saved.status_code == 200 and saved.json()['blocks'][0]['effective_text'] == '001.20 mg/mL'
    assert client.get(base+'/ocr-review-versions/'+result['id']).json()['edits'] == edits
    assert client.get(base+'/ocr-review-versions?parse_id='+parent['id']).json()['total'] == 1
    assert client.get(base+'/download').content == raw
    assert client.get(parent['download_url']).content == original
    second = client.post(base+'/ocr-reviews',json={'parse_id':parent['id']},headers={'Idempotency-Key':'second'})
    assert second.status_code == 202 and second.json()['id'] != task['id']
    execute(second.json())
    second_url='/api/v1/tasks/'+second.json()['id']+'/ocr-review'
    revised=decide(client,client.get(second_url).json(),'revise','second-save',[dict(block_id='text-1',action='unreadable')])
    assert execute(revised.json())['status']=='waiting_confirmation'
    approved_second=decide(client,client.get(second_url).json(),'approve','second-approve')
    assert execute(approved_second.json())['status']=='succeeded'
    new_result=client.get(second_url).json()['result']
    assert new_result['version']==2
    assert client.get(new_result['download_url']).json()['blocks'][0]['effective_text'] is None
    assert client.get(result['download_url']).content == saved.content
    assert client.get('/api/v1/tasks/'+task['id']+'/workspace').status_code == 200
    with database_connection() as db: assert audit_database(db)['ok']


def test_crashed_publish_recovers_the_approved_candidate(client):
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.db.database import database_connection
    _,_,_,task,_=setup_review(client)
    execute(task)
    url='/api/v1/tasks/'+task['id']+'/ocr-review'
    revised=decide(client,client.get(url).json(),'revise','save',[dict(block_id='text-1',action='accept_original')])
    execute(revised.json())
    view=client.get(url).json()
    preview=client.get(view['preview_download_url']).content
    accepted=decide(client,view,'approve','approve').json()
    repository=TaskExecutionStore()
    assert repository.claim(task['id'],accepted['revision'],task_type='review_ocr') is not None
    with database_connection(write=True) as db:
        db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s AND status='running'",(task['id'],))
    assert TaskExecutionStore().recover_expired() >= 1
    queued=client.get('/api/v1/tasks/'+task['id']).json()
    assert queued['status']=='queued'
    assert execute(queued)['status']=='succeeded'
    result=client.get(url).json()['result']
    assert client.get(result['download_url']).content==preview
    assert decide(client,view,'approve','approve').json()==accepted


@pytest.mark.parametrize('mutation',['checkpoint','decision','version'])
def test_database_audit_detects_review_chain_corruption(client,mutation):
    from app.db.database import database_connection
    from app.maintenance.database_audit import audit_database
    _,_,_,task,_=setup_review(client)
    execute(task)
    url='/api/v1/tasks/'+task['id']+'/ocr-review'
    revised=decide(client,client.get(url).json(),'revise','save',[dict(block_id='text-1',action='accept_original')])
    execute(revised.json())
    approved=decide(client,client.get(url).json(),'approve','approve')
    assert execute(approved.json())['status']=='succeeded'
    result=client.get(url).json()['result']
    with database_connection(write=True) as db:
        if mutation=='checkpoint':
            db.execute("UPDATE task_checkpoints SET state_json=jsonb_set(state_json,'{input_version,source,document_sha256}',to_jsonb(repeat('a',64))) WHERE task_id=%s",(task['id'],))
        elif mutation=='decision':
            db.execute("UPDATE ocr_review_decisions SET request_json=request_json-'input_version' WHERE task_id=%s AND operation='approve'",(task['id'],))
        else:
            db.execute("UPDATE ocr_review_versions SET summary_json=jsonb_set(summary_json,'{accepted_blocks}','0'::jsonb) WHERE task_id=%s",(task['id'],))
    with database_connection() as db: assert audit_database(db)['ok'] is False
    assert client.get(result['download_url']).status_code==409


def test_owner_scope_resume_and_frozen_source(client):
    from tests.integration.test_project_ownership import account_client
    project,base,parent,task,_ = setup_review(client)
    same = client.post(base+'/ocr-reviews',json={'parse_id':parent['id']},headers={'Idempotency-Key':'resume'})
    assert same.status_code == 409 and same.json()['detail']['code']=='ocr_review_active'
    replay=client.post(base+'/ocr-reviews',json={'parse_id':parent['id']},headers={'Idempotency-Key':'create'})
    assert replay.status_code==200 and replay.json()['id']==task['id']
    assert client.get(base+'/ocr-reviews?parse_id='+parent['id']).json()['items'][0]['id'] == task['id']
    execute(task)
    url='/api/v1/tasks/'+task['id']+'/ocr-review'
    view=client.get(url).json()
    with account_client('ocr-review-other@example.test')[0] as other:
        assert other.get(url).status_code == 404
        assert other.get(base+'/ocr-reviews').status_code == 404
        assert decide(other,view,'revise','foreign',[]).status_code == 404
    altered={**view['task']['input_version'],'source':{**view['source'],'parse_version':2}}
    body=dict(operation='revise',wait_id=view['wait']['id'],checkpoint_id=view['checkpoint_id'],
        expected_task_revision=view['task']['revision'],input_version=altered,edits=[])
    assert client.post(url+'/decision',json=body,headers={'Idempotency-Key':'changed'}).status_code == 409


def test_empty_replacement_public_hint_and_approve_rejects_edits(client):
    _,_,_,task,_=setup_review(client)
    execute(task)
    url='/api/v1/tasks/'+task['id']+'/ocr-review'
    view=client.get(url).json()
    response=decide(client,view,'revise','blank',[dict(block_id='text-1',action='replace_text',text=' \t')])
    assert response.status_code==422
    assert '无法辨认' in response.json()['detail']['message']
    assert decide(client,view,'approve','hidden',[]).status_code==422
    assert client.get(url).json()['task']['revision']==view['task']['revision']


def test_zero_blocks_cannot_create_review(client):
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    project,_,_,item,_=uploaded_image(client)
    def no_text(*args,**kwargs):
        result=ocr_result(*args,**kwargs)
        result.document.pages[0].text_blocks=[]
        result.document.pages[0].text_status='no_text'
        result.document.counts.text_blocks=0
        result.document.counts.pages_without_text=1
        return result
    assert run_parse_file_task(item['task']['id'],1,parser=no_text)['status']=='succeeded'
    base=f"/api/v1/projects/{project['id']}/files/{item['file_id']}"
    parent=client.get(base+'/document-versions').json()['items'][0]
    response=client.post(base+'/ocr-reviews',json={'parse_id':parent['id']},headers={'Idempotency-Key':'no-blocks'})
    assert response.status_code==422
    assert client.get(base+'/ocr-reviews').json()['items']==[]


def test_failed_wait_rolls_back_and_retry_restores_saved_progress(client):
    from app.db.database import database_connection, migration_connection
    _,_,_,task,_=setup_review(client)
    execute(task)
    url='/api/v1/tasks/'+task['id']+'/ocr-review'
    edits=[dict(block_id='text-1',action='replace_text',text=' 001 mg ')]
    revised=decide(client,client.get(url).json(),'revise','save',edits).json()
    with migration_connection(write=True) as db:
        db.execute("CREATE FUNCTION reject_ocr_wait() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'test rollback'; END $$")
        db.execute('CREATE TRIGGER reject_ocr_wait BEFORE INSERT ON task_waits FOR EACH ROW EXECUTE FUNCTION reject_ocr_wait()')
    try:
        failed=execute(revised)
        assert failed['status']=='failed' and failed['error_code']=='storage_unavailable'
        view=client.get(url).json()
        assert view['wait'] is None and view['summary'] is None and view['edits']==edits
        with database_connection() as db:
            assert db.execute("SELECT count(*) AS n FROM task_waits WHERE task_id=%s AND status='open'",(task['id'],)).fetchone()['n']==0
    finally:
        with migration_connection(write=True) as db:
            db.execute('DROP TRIGGER reject_ocr_wait ON task_waits')
            db.execute('DROP FUNCTION reject_ocr_wait()')
    retry=client.post('/api/v1/tasks/'+task['id']+'/retry',json={'expected_revision':failed['revision']})
    assert retry.status_code==202,retry.text
    assert execute(retry.json())['status']=='waiting_confirmation'
    assert client.get(url).json()['edits']==edits


def test_worker_interrupt_retries_are_finite(client):
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.db.database import database_connection
    _,_,_,task,_=setup_review(client)
    repository=TaskExecutionStore()
    for number in range(3):
        assert repository.claim(task['id'],task['revision'],task_type='review_ocr') is not None
        with database_connection(write=True) as db:
            db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s AND status='running'",(task['id'],))
        assert repository.recover_expired()>=1
        task=client.get('/api/v1/tasks/'+task['id']).json()
        assert task['status']==('failed' if number==2 else 'queued')
    assert task['retry_count']==2 and task['error_code']=='task_worker_interrupted'


def test_concurrent_create_accepts_one_key_and_preserves_creation_replay(client):
    from concurrent.futures import ThreadPoolExecutor
    _,base,parent,task,_=setup_review(client)
    execute(task)
    url='/api/v1/tasks/'+task['id']+'/ocr-review'
    saved=decide(client,client.get(url).json(),'revise','save',[dict(block_id='text-1',action='accept_original')])
    execute(saved.json())
    accepted=decide(client,client.get(url).json(),'approve','approve')
    execute(accepted.json())
    def create(key):
        return key,client.post(base+'/ocr-reviews',json={'parse_id':parent['id']},headers={'Idempotency-Key':key})
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(create,['race-a','race-b']))
    assert sorted(response.status_code for _,response in responses)==[202,409]
    key,created=next((key,response) for key,response in responses if response.status_code==202)
    losing_key,conflict=next((key,response) for key,response in responses if response.status_code==409)
    assert conflict.json()['detail']['code']=='ocr_review_active'
    assert create(key)[1].json()['id']==created.json()['id']
    assert client.get(base+'/ocr-reviews?parse_id='+parent['id']).json()['items'][0]['id']==created.json()['id']
    assert create('create')[1].json()['id']==task['id']
