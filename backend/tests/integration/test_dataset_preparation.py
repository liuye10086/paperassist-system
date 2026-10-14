"""Real persisted preparation decisions and recovery, isolated PostgreSQL schemas."""
import copy
import pytest

from app.adapters.task_execution_store import TaskExecutionStore
from app.adapters.task_store import TaskStore
from app.db.database import database_connection, migration_connection
from tests.api.test_analysis import client, add_file
from tests.api.test_dataset_analysis import version, forbid_original
from tests.helpers.tasks import task_owner


def create_preparation(client, *, rows=None, key='prepare'):
    base, file = add_file(client, rows)
    raw = version(client, base)
    defaults = client.get(base+'/dataset-versions/'+raw['id']+'/preparation-defaults')
    assert defaults.status_code == 200, defaults.text
    request = dict(dataset_id=raw['id'], recipe=defaults.json()['recipe'])
    response = client.post(base+'/dataset-preparations', json=request, headers={'Idempotency-Key':key})
    assert response.status_code == 202, response.text
    return base, file, raw, request, response.json()


def run(task):
    from app.domain.tasks.dataset_preparation_execution import run_preparation_task
    return run_preparation_task(task['id'], task['revision'])


def review(client, task):
    response = client.get('/api/v1/tasks/'+task['id']+'/dataset-preparation')
    assert response.status_code == 200, response.text
    return response.json()


def decision(view, operation='approve', recipe=None):
    return dict(operation=operation, wait_id=view['wait']['id'], checkpoint_id=view['checkpoint_id'],
        expected_task_revision=view['task']['revision'], input_version=copy.deepcopy(view['task']['input_version']), recipe=recipe)


def decide(client, task, body, key='decision'):
    return client.post('/api/v1/tasks/'+task['id']+'/dataset-preparation/decision',
        json=body, headers={'Idempotency-Key':key})


def test_defaults_read_and_creation_replay_do_not_advance_tasks(client):
    base, _, raw, request, task = create_preparation(client)
    with database_connection() as db:
        before = db.execute('SELECT count(*) AS n FROM tasks').fetchone()['n']
    assert client.get(base+'/dataset-versions/'+raw['id']+'/preparation-defaults').status_code == 200
    replay = client.post(base+'/dataset-preparations', json=request, headers={'Idempotency-Key':'prepare'})
    assert replay.status_code == 200 and replay.json()['id'] == task['id']
    altered = copy.deepcopy(request); altered['recipe']['fields'][0]['name'] = '另一个名称'
    assert client.post(base+'/dataset-preparations', json=altered, headers={'Idempotency-Key':'prepare'}).status_code == 409
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM tasks').fetchone()['n'] == before
        assert db.execute('SELECT count(*) AS n FROM dataset_preparation_decisions').fetchone()['n'] == 0
    pending = review(client, task)
    assert pending['preview'] is None and pending['changes'] == [] and pending['wait'] is None


def test_preview_wait_releases_lease_and_approval_publishes_exact_candidate(client, monkeypatch):
    base, file, raw, _, task = create_preparation(client)
    monkeypatch.setattr('app.adapters.storage.ProjectStore.original', forbid_original)
    waiting = run(task)
    assert waiting['status'] == 'waiting_confirmation' and waiting['reason_code'] == 'confirmation_required'
    with database_connection() as db:
        attempt = db.execute('SELECT * FROM task_attempts WHERE task_id=%s', (task['id'],)).fetchone()
        assert attempt['finished_at'] and attempt['lease_owner'] is None and attempt['lease_expires_at'] is None
    view = review(client, task)
    assert view['wait']['kind'] == 'dataset_preparation_confirmation'
    workspace = client.get('/api/v1/tasks/'+task['id']+'/workspace').json()
    assert workspace['allowed_actions'] == ['approve', 'revise']
    assert workspace['source']['dataset_source'] == view['source'] and workspace['source']['analysis_run_id'] is None
    preview = client.get(view['preview_download_url'])
    assert preview.status_code == 200
    body = decision(view)
    accepted = decide(client, task, body)
    assert accepted.status_code == 202 and accepted.json()['status'] == 'queued'
    assert decide(client, task, body).json() == accepted.json()
    changed = copy.deepcopy(body); changed['checkpoint_id'] = 'stale'
    assert decide(client, task, changed).status_code == 409
    monkeypatch.setattr('app.domain.tasks.dataset_preparation_execution.prepare_dataset',forbid_original)
    succeeded = run(accepted.json())
    assert succeeded['status'] == 'succeeded'
    assert decide(client, task, body).json() == accepted.json()
    result = review(client, task)['result']
    assert result['parent_dataset_id'] == raw['id'] and result['parent_dataset_version'] == 1
    assert result['source']['kind'] == 'prepared_dataset_version'
    assert client.get(result['download_url']).content == preview.content
    listed = client.get(base+'/prepared-dataset-versions').json()
    assert listed == dict(items=[result],total=1,page=1,page_size=5)
    assert client.get(base+'/prepared-dataset-versions/'+result['id']).json() == result
    rows = client.get(base+'/prepared-dataset-versions/'+result['id']+'/rows').json()
    assert rows['start_row'] == 2 and rows['total_rows'] == 5 and rows['limit'] == 20
    assert [r['row'] for r in rows['rows']] == [2,3,4,5,6]
    artifact = client.get('/api/v1/tasks/'+task['id']+'/workspace').json()['artifacts']['dataset']
    assert artifact['download_url'] == result['download_url']
    with database_connection() as db:
        nodes = db.execute('SELECT node FROM task_checkpoints WHERE task_id=%s ORDER BY seq', (task['id'],)).fetchall()
        assert [n['node'] for n in nodes] == ['prepare_preview','await_confirmation','approve','publish','done']
        assert db.execute('SELECT count(*) AS n FROM prepared_dataset_versions WHERE task_id=%s',(task['id'],)).fetchone()['n'] == 1


def test_revision_uses_saved_recipe_rejects_stale_wait_and_keeps_original_snapshot(client):
    base, _, _, _, task = create_preparation(client, rows=[['数值','标签'],[1,' A '],[2,'NA']])
    run(task); first = review(client, task)
    with database_connection() as db:
        frozen = db.execute('SELECT input_snapshot FROM tasks WHERE id=%s',(task['id'],)).fetchone()['input_snapshot']
    recipe = copy.deepcopy(first['recipe'])
    recipe['fields'][1].update(trim_text=True, missing_markers=['NA'])
    revised = decide(client, task, decision(first,'revise',recipe), 'revise')
    assert revised.status_code == 202, revised.text
    run(revised.json()); second = review(client, task)
    assert second['recipe_revision'] == 2 and second['preview']['changed_cell_count'] == 2
    assert second['recipe'] == recipe and second['wait']['id'] != first['wait']['id']
    assert decide(client, task, decision(first), 'old-wait').status_code == 409
    stale_checkpoint = decision(second); stale_checkpoint['checkpoint_id'] = first['checkpoint_id']
    assert decide(client, task, stale_checkpoint, 'old-checkpoint').status_code == 409
    with database_connection() as db:
        assert db.execute('SELECT input_snapshot FROM tasks WHERE id=%s',(task['id'],)).fetchone()['input_snapshot'] == frozen
        prior = db.execute('SELECT status FROM task_waits WHERE id=%s',(first['wait']['id'],)).fetchone()
        assert prior['status'] == 'superseded'
    wrong_source = decision(second)
    wrong_source['input_version']['source']['dataset_sha256'] = 'c'*64
    assert decide(client,task,wrong_source,'wrong-source').status_code == 409
    accepted = decide(client, task, decision(second), 'approve-v2')
    assert run(accepted.json())['status'] == 'succeeded'


def test_fixed_raw_version_and_owner_file_scoping(client):
    base, _, raw, _, task = create_preparation(client)
    version(client,base,1)
    assert run(task)['status'] == 'waiting_confirmation'
    view = review(client,task)
    assert view['source']['dataset_id'] == raw['id'] and view['source']['dataset_version'] == 1
    other_base, _ = add_file(client)
    assert client.post(other_base+'/dataset-preparations',json=dict(dataset_id=raw['id'],recipe=view['recipe']),headers={'Idempotency-Key':'cross-project'}).status_code == 404
    owner = task_owner(client)
    from app.domain.dataset_preparation.service import DatasetPreparationService
    from app.adapters.task_store import DatasetTaskAssets
    from app.db.database import get_database_config
    from app.core.exceptions import StorageError
    # A real different owner cannot fetch or decide the task.
    with pytest.raises(StorageError) as error:
        DatasetPreparationService(DatasetTaskAssets('different-owner',get_database_config())).get_task(task['id'])
    assert error.value.code == 'task_not_found'


@pytest.mark.parametrize('table', ['dataset_preparation_decisions', 'prepared_dataset_versions'])
def test_transaction_failure_preserves_wait_or_publish_checkpoint(client, table):
    _, _, _, _, task = create_preparation(client)
    run(task); view = review(client,task); body = decision(view)
    if table == 'prepared_dataset_versions':
        accepted = decide(client,task,body).json()
    with migration_connection(write=True) as db:
        db.execute("""CREATE FUNCTION reject_preparation_write() RETURNS trigger LANGUAGE plpgsql AS
            $$ BEGIN RAISE EXCEPTION 'test rollback'; END $$""")
        db.execute('CREATE TRIGGER reject_preparation_write BEFORE INSERT ON '+table+' FOR EACH ROW EXECUTE FUNCTION reject_preparation_write()')
    try:
        if table == 'dataset_preparation_decisions':
            assert decide(client,task,body).status_code == 503
            same = review(client,task)
            assert same['wait']['id'] == view['wait']['id'] and same['checkpoint_id'] == view['checkpoint_id']
        else:
            failed = run(accepted)
            assert failed['status'] == 'failed'
            with database_connection() as db:
                assert db.execute('SELECT count(*) AS n FROM prepared_dataset_versions').fetchone()['n'] == 0
                assert db.execute('SELECT next_node FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',(task['id'],)).fetchone()['next_node'] == 'publish'
    finally:
        with migration_connection(write=True) as db:
            db.execute('DROP TRIGGER reject_preparation_write ON '+table)
            db.execute('DROP FUNCTION reject_preparation_write()')
    if table == 'dataset_preparation_decisions':
        accepted = decide(client,task,body).json()
    else:
        retried = client.post('/api/v1/tasks/'+task['id']+'/retry',json={'expected_revision':failed['revision']})
        assert retried.status_code == 202, retried.text
        accepted = retried.json()
    assert run(accepted)['status'] == 'succeeded'
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM prepared_dataset_versions').fetchone()['n'] == 1


def test_crashed_publish_recovery_uses_checkpoint(client):
    _, _, _, _, task = create_preparation(client)
    run(task); view = review(client,task)
    accepted = decide(client,task,decision(view)).json()
    repository = TaskExecutionStore()
    lease = repository.claim(task['id'],accepted['revision'],task_type='prepare_dataset')
    assert lease is not None
    with database_connection(write=True) as db:
        db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s",(task['id'],))
    assert TaskExecutionStore().recover_expired() >= 1
    queued = TaskStore(task_owner(client)).get(task['id'])
    assert queued['status'] == 'queued'
    assert run(queued)['status'] == 'succeeded'


def test_wait_transaction_failure_has_no_half_wait_and_retry_uses_saved_recipe(client):
    _, _, _, _, task = create_preparation(client)
    run(task); view = review(client,task)
    recipe = copy.deepcopy(view['recipe']); recipe['fields'][0]['name'] = '修改后'
    revised = decide(client,task,decision(view,'revise',recipe),'revise').json()
    with migration_connection(write=True) as db:
        db.execute("""CREATE FUNCTION reject_preparation_wait() RETURNS trigger LANGUAGE plpgsql AS
            $$ BEGIN RAISE EXCEPTION 'test rollback'; END $$""")
        db.execute('CREATE TRIGGER reject_preparation_wait BEFORE INSERT ON task_waits FOR EACH ROW EXECUTE FUNCTION reject_preparation_wait()')
    try:
        failed = run(revised)
        assert failed['status'] == 'failed'
        state = review(client,task)
        assert state['wait'] is None and state['preview'] is None and state['recipe'] == recipe
        with database_connection() as db:
            assert db.execute("SELECT count(*) AS n FROM task_waits WHERE task_id=%s AND status='open'",(task['id'],)).fetchone()['n'] == 0
            assert db.execute("SELECT count(*) AS n FROM task_checkpoints WHERE task_id=%s AND node='await_confirmation'",(task['id'],)).fetchone()['n'] == 1
    finally:
        with migration_connection(write=True) as db:
            db.execute('DROP TRIGGER reject_preparation_wait ON task_waits')
            db.execute('DROP FUNCTION reject_preparation_wait()')
    retried = client.post('/api/v1/tasks/'+task['id']+'/retry',json={'expected_revision':failed['revision']})
    assert run(retried.json())['status'] == 'waiting_confirmation'
    new_view = review(client,task)
    assert new_view['recipe'] == recipe and new_view['recipe_revision'] == 2


def test_selected_excel_coordinates_empty_rows_and_parent_ordinals(client):
    base, _, raw, request, task = create_preparation(client,
        rows=[['title'],[None,None,'Value','Group'],[None,None,1,' A '],[],[None,None,2,'B'],['outside selected columns']])
    defaults = client.get(base+'/dataset-versions/'+raw['id']+'/preparation-defaults',params=dict(header_row=2,data_range='C3:D6'))
    assert defaults.status_code == 200,defaults.text
    # Explicit empty terminal rows remain within the selected raw sheet extent.
    recipe = defaults.json()['recipe']
    for key in ('selected-one','selected-two'):
        response = client.post(base+'/dataset-preparations',json=dict(dataset_id=raw['id'],recipe=recipe),headers={'Idempotency-Key':key})
        assert response.status_code == 202,response.text
        created = response.json(); run(created)
        accepted = decide(client,created,decision(review(client,created)),key).json()
        assert run(accepted)['status'] == 'succeeded'
        result = review(client,created)['result']
        rows = client.get(base+'/prepared-dataset-versions/'+result['id']+'/rows').json()
        assert rows['start_row'] == 3 and rows['total_rows'] == 4
        assert [row['row'] for row in rows['rows']] == [3,4,5,6]
        assert rows['rows'][1]['cells'] == [] and rows['rows'][3]['cells'] == []
        assert client.get(base+'/prepared-dataset-versions/'+result['id']+'/rows',params={'start_row':1}).status_code == 422
    assert [item['version'] for item in client.get(base+'/prepared-dataset-versions').json()['items']] == [2,1]
    assert client.get(base+'/prepared-dataset-versions',params={'page_size':10}).status_code == 422


def test_published_boundary_rejects_corrupt_saved_approval(client):
    _, _, _, _, task = create_preparation(client)
    run(task); accepted = decide(client,task,decision(review(client,task))).json()
    assert run(accepted)['status'] == 'succeeded'
    result = review(client,task)['result']
    with database_connection(write=True) as db:
        db.execute("UPDATE dataset_preparation_decisions SET request_json=request_json-'input_version' WHERE task_id=%s",(task['id'],))
    response = client.get(result['download_url'])
    assert response.status_code == 409,response.text


def test_initial_recipe_snapshot_integrity_is_validated_at_task_boundary(client):
    _, _, _, _, task = create_preparation(client)
    from psycopg.types.json import Jsonb
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET input_snapshot=jsonb_set(input_snapshot,'{recipe,fields,0,name}',%s) WHERE id=%s",(Jsonb('changed-in-place'),task['id']))
    response = client.get('/api/v1/tasks/'+task['id']+'/dataset-preparation')
    assert response.status_code == 409,response.text


def test_publication_preserves_project_utc_timestamp_contract(client):
    base, _, _, _, task = create_preparation(client)
    run(task); accepted = decide(client,task,decision(review(client,task))).json()
    assert run(accepted)['status'] == 'succeeded'
    with database_connection() as db:
        timestamp = db.execute('SELECT updated_at FROM projects WHERE id=%s',(task['project_id'],)).fetchone()['updated_at']
    assert timestamp.endswith(('Z','+00:00')),timestamp
