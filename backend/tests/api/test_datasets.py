"""Dedicated raw versions never mutate the historical preview."""
from datetime import datetime, timedelta, timezone

from tests.api.test_projects import client, create_project  # noqa: F401
from tests.domain.test_file_parse_execution import queued, deterministic
from app.domain.tasks.file_parse_execution import run_parse_file_task
from app.db.database import database_connection
from app.core.config import ExcelSettings
from app.core.exceptions import StorageError
import pytest


def structure_parser(content, filename, settings):
    from app.adapters.excel_structure import extract_excel_structure
    return extract_excel_structure(content, filename, ExcelSettings(**settings['excel']))


def generate(client, base, latest, key):
    response = client.post(base+'/structure-versions',headers={'Idempotency-Key':key},json={'expected_latest_version':latest})
    assert response.status_code == 202,response.text
    return response.json()


def prepared(client):
    project, item, content = queued(client)
    run_parse_file_task(item['task']['id'], 1, parser=deterministic)
    return project, item, content, f"/api/v1/projects/{project['id']}/files/{item['file_id']}"


def test_empty_read_and_explicit_idempotent_creation(client):
    _, item, _, base = prepared(client)
    with database_connection() as db:
        before = dict(db.execute('SELECT * FROM files WHERE id=%s', (item['file_id'],)).fetchone())
    empty = client.get(base + '/structure-versions')
    assert empty.status_code == 200
    assert empty.json() == dict(items=[], total=0, page=1, page_size=5, latest_version=0)
    first = client.post(base + '/structure-versions', headers={'Idempotency-Key': 'one'}, json={'expected_latest_version': 0})
    assert first.status_code == 202, first.text
    view = first.json()
    assert view['version'] == 1 and view['parent_id'] is None and view['datasets'] == []
    assert view['task']['input_version']['kind'] == 'excel_structure'
    assert client.post(base + '/structure-versions', headers={'Idempotency-Key': 'one'}, json={'expected_latest_version': 0}).status_code == 200
    assert client.post(base + '/structure-versions', headers={'Idempotency-Key': 'one'}, json={'expected_latest_version': 1}).status_code == 409
    assert client.post(base + '/structure-versions', headers={'Idempotency-Key': 'two'}, json={'expected_latest_version': 0}).status_code == 409
    assert client.post(base + '/structure-versions', headers={'Idempotency-Key': 'two'}, json={'expected_latest_version': 1}).json()['detail']['code'] == 'structure_task_pending'
    workspace = client.get('/api/v1/tasks/' + view['task']['id'] + '/workspace')
    assert workspace.status_code == 200, workspace.text
    assert workspace.json()['source']['analysis_run_id'] is None
    with database_connection() as db:
        assert dict(db.execute('SELECT * FROM files WHERE id=%s', (item['file_id'],)).fetchone()) == before


def test_complete_two_versions_and_failed_third_preserve_original(client):
    from app.domain.tasks.dataset_execution import run_dataset_task
    _, item, _, base = prepared(client)
    with database_connection() as db:
        before = dict(db.execute('SELECT * FROM files WHERE id=%s',(item['file_id'],)).fetchone())
    first = generate(client,base,0,'one')
    done = run_dataset_task(first['task']['id'],1,parser=structure_parser)
    assert done['status'] == 'succeeded'
    assert run_dataset_task(first['task']['id'],1,parser=structure_parser) is None
    first = client.get(base+'/structure-versions/'+first['id']).json()
    second = generate(client,base,1,'two')
    assert second['parent_id'] == first['id']
    assert run_dataset_task(second['task']['id'],1,parser=structure_parser)['status'] == 'succeeded'
    second = client.get(base+'/structure-versions/'+second['id']).json()
    assert second['datasets'][0]['parent_id'] == first['datasets'][0]['id']
    dataset = first['datasets'][0]
    url = base+'/dataset-versions/'+dataset['id']
    downloaded = client.get(url+'/download')
    assert downloaded.status_code == 200,downloaded.text
    assert downloaded.json()['epoch'] == dataset['epoch']
    cells = downloaded.json()['sheet']['cells']
    assert cells and downloaded.json()['sheet']['row_count'] == dataset['row_count']
    page = client.get(url+'/rows').json()
    assert page['rows'][0]['row']==1
    assert client.get(url+'/rows?limit=21').status_code==422
    assert client.get(url+'/rows?start_row=100000').json()['rows']==[]
    third = generate(client,base,2,'three')
    def bad(*args):
        raise StorageError('parse_output_invalid','bad',422)
    assert run_dataset_task(third['task']['id'],1,parser=bad)['status']=='failed'
    third = client.get(base+'/structure-versions/'+third['id']).json()
    assert third['datasets']==[]
    assert client.get(url+'/download').content==downloaded.content
    with database_connection() as db:
        assert dict(db.execute('SELECT * FROM files WHERE id=%s',(item['file_id'],)).fetchone())==before


@pytest.mark.parametrize('session_timezone,project_is_newer', [
    ('Asia/Shanghai', False), ('Asia/Shanghai', True), ('UTC', False),
])
def test_dataset_publication_keeps_project_timestamp_utc_and_monotonic(client, monkeypatch, session_timezone, project_is_newer):
    from app.adapters.dataset_store import DatasetStore
    from app.adapters.task_execution_store import TaskExecutionStore
    project, _, _, base = prepared(client)
    view = generate(client, base, 0, 'timestamp')
    repository = TaskExecutionStore()
    lease = repository.claim(view['task']['id'], 1, task_type='extract_dataset')
    store = DatasetStore(repository)
    snapshot, content = store.load(lease)
    prior = datetime.now(timezone.utc) + timedelta(hours=1 if project_is_newer else -1)
    with database_connection(write=True) as db:
        db.execute('UPDATE projects SET updated_at=%s WHERE id=%s', (prior.isoformat(), project['id']))
    original_now = repository.now

    def session_now(db):
        db.execute("SELECT set_config('TimeZone', %s, true)", (session_timezone,))
        value = original_now(db)
        assert value.utcoffset() == timedelta(hours=8 if session_timezone == 'Asia/Shanghai' else 0)
        return value

    monkeypatch.setattr(repository, 'now', session_now)
    assert store.complete(lease, snapshot, structure_parser(content, snapshot['file']['filename'], snapshot['settings']))['status'] == 'succeeded'
    with database_connection() as db:
        completed = db.execute('SELECT completed_at FROM file_structure_versions WHERE id=%s', (view['id'],)).fetchone()['completed_at']
        saved = db.execute('SELECT updated_at FROM projects WHERE id=%s', (project['id'],)).fetchone()['updated_at']
    assert saved == max(prior, completed).astimezone(timezone.utc).isoformat()


@pytest.mark.parametrize('change',['lease','source','owner'])
def test_invalid_publication_guard(client,change):
    from app.adapters.dataset_store import DatasetStore
    from app.adapters.task_execution_store import TaskExecutionStore,LeaseLost
    _,_,content,base=prepared(client)
    view=generate(client,base,0,'guard')
    repo=TaskExecutionStore()
    lease=repo.claim(view['task']['id'],1,task_type='extract_dataset')
    assert lease is not None
    store=DatasetStore(repo)
    snapshot,_=store.load(lease)
    with database_connection(write=True) as db:
        if change=='lease': db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second'")
        elif change=='source': db.execute("UPDATE files SET sha256=%s",('b'*64,))
        else: db.execute('UPDATE users SET active=false')
    with pytest.raises((LeaseLost,StorageError)):
        store.complete(lease,snapshot,structure_parser(content,snapshot['file']['filename'],snapshot['settings']))
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM dataset_versions').fetchone()['n']==0
        assert db.execute('SELECT manifest_json FROM file_structure_versions').fetchone()['manifest_json'] is None


def test_technical_retry_uses_frozen_input(client):
    from app.domain.tasks.dataset_execution import run_dataset_task
    _,_,_,base=prepared(client)
    view=generate(client,base,0,'retry')
    def timeout(*args): raise StorageError('parse_timeout','timeout',422)
    failed=run_dataset_task(view['task']['id'],1,parser=timeout)
    url='/api/v1/tasks/'+failed['id']
    assert client.get(url+'/workspace').json()['allowed_actions']==['retry']
    response=client.post(url+'/resume',headers={'Idempotency-Key':'recover'},json={
        'operation':'retry','wait_id':None,'expected_task_revision':failed['revision'],'input_version':failed['input_version']})
    assert response.status_code==202,response.text
    assert run_dataset_task(failed['id'],response.json()['revision'],parser=structure_parser)['status']=='succeeded'


def test_full_31_rows_empty_sheet_and_hash_download(client):
    from io import BytesIO
    from openpyxl import Workbook
    from tests.api.test_file_batches import register
    from app.domain.tasks.dataset_execution import run_dataset_task
    from app.core.config import get_data_dir
    project=create_project(client)
    workbook=Workbook()
    sheet=workbook.active
    for row in range(1,32): sheet.append([str(row),'  '])
    workbook.create_sheet('Empty')
    stream=BytesIO();workbook.save(stream)
    batchbase,batch,item,content=register(client,project,content=stream.getvalue())
    result=client.post(batchbase+'/'+batch['id']+'/items/'+item['client_id'],files={'file':(item['filename'],content)}).json()
    run_parse_file_task(result['task']['id'],1,parser=deterministic)
    base=f"/api/v1/projects/{project['id']}/files/{result['file_id']}"
    first=generate(client,base,0,'full')
    assert run_dataset_task(first['task']['id'],1,parser=structure_parser)['status']=='succeeded'
    first=client.get(base+'/structure-versions/'+first['id']).json()
    assert len(first['datasets'])==2 and first['datasets'][1]['row_count']==0
    url=base+'/dataset-versions/'+first['datasets'][0]['id']
    page=client.get(url+'/rows?start_row=21').json()
    assert page['rows'][-1]['row']==31 and page['rows'][-1]['cells'][0]['value']=='31'
    assert len(client.get(url+'/download').json()['sheet']['cells'])==62
    with database_connection() as db:
        record=db.execute('SELECT * FROM dataset_versions WHERE id=%s',(first['datasets'][0]['id'],)).fetchone()
    (get_data_dir()/record['object_key']).write_bytes(b'broken')
    assert client.get(url+'/download').json()['detail']['code']=='dataset_changed'


def test_database_publication_failure_and_recovery(client):
    from app.adapters.dataset_store import DatasetStore
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.db.database import migration_connection
    _,_,_,base=prepared(client)
    view=generate(client,base,0,'rollback')
    repo=TaskExecutionStore(); lease=repo.claim(view['task']['id'],1,task_type='extract_dataset')
    store=DatasetStore(repo);snapshot,content=store.load(lease)
    result=structure_parser(content,snapshot['file']['filename'],snapshot['settings'])
    with migration_connection() as db:
        db.execute("CREATE FUNCTION reject_dataset_test() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'test failure'; END $$")
        db.execute('CREATE TRIGGER reject_dataset_test BEFORE INSERT ON dataset_versions FOR EACH ROW EXECUTE FUNCTION reject_dataset_test()')
    try:
        with pytest.raises(StorageError): store.complete(lease,snapshot,result)
        with database_connection() as db:
            assert db.execute('SELECT count(*) AS n FROM dataset_versions').fetchone()['n']==0
            assert db.execute('SELECT manifest_json FROM file_structure_versions').fetchone()['manifest_json'] is None
    finally:
        with migration_connection() as db:
            db.execute('DROP TRIGGER reject_dataset_test ON dataset_versions')
            db.execute('DROP FUNCTION reject_dataset_test()')
    # Unknown durable bytes are recovered only through the explicit business
    # retry action, retaining this task and its immutable structure version.
    from app.domain.tasks.dataset_execution import run_dataset_task
    failed=repo.fail(lease,'storage_unavailable')
    retried=client.post('/api/v1/tasks/'+lease.task_id+'/retry',json={'expected_revision':failed['revision']})
    assert retried.status_code==202,retried.text
    assert run_dataset_task(lease.task_id,retried.json()['revision'],parser=structure_parser)['status']=='succeeded'


def test_concurrent_creations_register_single_attempt(client):
    from concurrent.futures import ThreadPoolExecutor
    from app.adapters.storage import get_project_store
    from app.domain.datasets.service import DatasetService,StructureCreateRequest
    project,item,_,base=prepared(client)
    # Reuse the authenticated owner, avoiding shared TestClient session mutation.
    with database_connection() as db:
        owner=db.execute('SELECT owner_id FROM projects WHERE id=%s',(project['id'],)).fetchone()['owner_id']
    from app.adapters.storage import ProjectStore
    from app.core.config import get_data_dir
    service=DatasetService(ProjectStore(directory=get_data_dir(),owner_id=owner))
    def request(key):
        try:return service.create(project['id'],item['file_id'],StructureCreateRequest(expected_latest_version=0),key)[1]
        except StorageError as exc:return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(request,['a','b']))
    assert sorted(results,key=str)==sorted([202,'structure_version_conflict'],key=str)
    assert client.get(base+'/structure-versions').json()['total']==1


def test_legacy_null_locator_and_cross_account_scope(client):
    from tests.api.test_projects import upload
    from app.domain.tasks.dataset_execution import run_dataset_task
    from app.auth.service import create_user
    project=create_project(client)
    saved=upload(client,project['id']).json()['file']
    file_id=saved['id']
    base=f"/api/v1/projects/{project['id']}/files/{file_id}"
    with database_connection(write=True) as db:
        db.execute('UPDATE files SET object_key=NULL WHERE id=%s',(file_id,))
    with database_connection() as db:
        assert db.execute('SELECT object_key FROM files WHERE id=%s',(file_id,)).fetchone()['object_key'] is None
    assert client.get(base+'/structure-versions').json()['items']==[]
    view=generate(client,base,0,'legacy')
    assert run_dataset_task(view['task']['id'],1,parser=structure_parser)['status']=='succeeded'
    view=client.get(base+'/structure-versions/'+view['id']).json()
    dataset_id=view['datasets'][0]['id']
    create_user('other-dataset@paperassist.local','isolated-other-password-2026')
    login=client.post('/api/v1/auth/login',json={'email':'other-dataset@paperassist.local','password':'isolated-other-password-2026'})
    assert login.status_code==200
    client.headers['X-CSRF-Token']=login.json()['csrf_token']
    for endpoint in ('/structure-versions','/structure-versions/'+view['id'],
                     '/dataset-versions/'+dataset_id+'/rows','/dataset-versions/'+dataset_id+'/download'):
        response=client.get(base+endpoint)
        assert response.status_code==404 and response.json()['detail']['code']=='project_not_found'
    assert client.post(base+'/structure-versions',headers={'Idempotency-Key':'other'},json={'expected_latest_version':1}).status_code==404


def test_oversized_result_publishes_no_sheet(client):
    from app.domain.tasks.dataset_execution import run_dataset_task
    _,_,_,base=prepared(client)
    view=generate(client,base,0,'oversized')
    def oversized(content,filename,settings):
        result=structure_parser(content,filename,settings).model_dump()
        result['sheets'][0]['cells'][0]['value']='x'*4194305
        return result
    result=run_dataset_task(view['task']['id'],1,parser=oversized)
    assert result['status']=='failed' and result['error_code']=='parse_output_invalid'
    assert client.get(base+'/structure-versions/'+view['id']).json()['datasets']==[]
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM dataset_versions').fetchone()['n']==0


def test_object_locator_cannot_be_rebound_to_another_dataset(client):
    from app.domain.tasks.dataset_execution import run_dataset_task
    from app.core.config import get_data_dir
    _,_,_,base=prepared(client)
    view=generate(client,base,0,'locator')
    run_dataset_task(view['task']['id'],1,parser=structure_parser)
    dataset=client.get(base+'/structure-versions/'+view['id']).json()['datasets'][0]
    with database_connection() as db:
        row=db.execute('SELECT * FROM dataset_versions WHERE id=%s',(dataset['id'],)).fetchone()
    wrong='datasets/11111111-1111-1111-1111-111111111111/'+row['sha256']+'.json'
    path=get_data_dir()/wrong;path.parent.mkdir(parents=True);path.write_bytes((get_data_dir()/row['object_key']).read_bytes())
    with database_connection(write=True) as db:
        db.execute('UPDATE dataset_versions SET object_key=%s WHERE id=%s',(wrong,dataset['id']))
    response=client.get(base+'/dataset-versions/'+dataset['id']+'/download')
    assert response.status_code==409
    assert response.json()['detail']['code']=='dataset_changed'


def test_newer_registered_version_disables_old_failed_retry(client):
    from app.domain.tasks.dataset_execution import run_dataset_task
    _,_,_,base=prepared(client)
    old=generate(client,base,0,'older')
    def timeout(*args):raise StorageError('parse_timeout','timeout',422)
    failed=run_dataset_task(old['task']['id'],1,parser=timeout)
    generate(client,base,1,'newer')
    url='/api/v1/tasks/'+failed['id']
    assert client.get(url+'/workspace').json()['allowed_actions']==[]
    assert client.post(url+'/retry',json={'expected_revision':failed['revision']}).status_code==409
