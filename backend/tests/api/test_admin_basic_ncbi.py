"""B integration: isolated database, synthetic bytes, zero real transports."""
from copy import deepcopy

import pytest

from app.db.database import database_connection
from tests.api.test_admin_operations import accounts, admin
from tests.api.test_admin_configurations import baseline, saved, validated, switch, ROOT
from tests.api.test_excel import workbook_bytes
from tests.api.test_projects import create_project
from tests.api.test_file_batches import register


def activate(client, version, revision=0, key='first', operation='activate'):
    validated(client, version)
    response = switch(client, version, revision, key, operation)
    assert response.status_code == 200, response.text


def test_uploads_use_current_version_and_rollback_without_restart(admin):
    one = baseline(admin); activate(admin, one)
    project = create_project(admin)
    content = workbook_bytes()
    base, batch, item, _ = register(admin, project, content)
    pdf_base, pdf_batch, pdf_item, _ = register(admin, project, b'x'*200, 'synthetic.pdf', 'pdf')
    two = saved(admin, one, 'basic', 'max_upload_bytes', 100)
    activate(admin, two, 1, 'tighten')
    assert admin.get('/api/v1/excel/config').json()['max_upload_bytes'] == 100
    for url, name, data in [('/api/v1/excel/preview', 'data.xlsx', content),
            (f"/api/v1/projects/{project['id']}/files", 'data.xlsx', content),
            (base+'/'+batch['id']+'/items/'+item['client_id'], 'data.xlsx', content),
            (pdf_base+'/'+pdf_batch['id']+'/items/'+pdf_item['client_id'], 'synthetic.pdf', b'x'*200)]:
        response = admin.post(url, files={'file': (name, data)})
        assert response.status_code == 413, response.text
        assert response.json()['detail']['params']['max_bytes'] == 100
    # Multipart allowance is not a file-content limit; test the middleware separately.
    response = admin.post('/api/v1/excel/preview', content=iter([b'x'*66000]))
    assert response.status_code == 413
    rejected = register(admin, project, content, key='rejected')[1]
    assert rejected['items'][0]['error']['code'] == 'file_too_large'
    activate(admin, one, 2, 'rollback', 'rollback')
    assert admin.get('/api/v1/excel/config').json()['max_upload_bytes'] == one['bundle']['basic']['max_upload_bytes']
    response = admin.post(base+'/'+batch['id']+'/items/'+item['client_id'], files={'file': ('data.xlsx', content)})
    assert response.status_code == 202, response.text


def test_parse_freezes_binding_settings_and_retry_across_configuration_change(admin):
    from app.core.exceptions import StorageError
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    from tests.domain.test_file_parse_execution import deterministic
    one = baseline(admin); activate(admin, one)
    project = create_project(admin)
    def upload(key):
        base, batch, item, content = register(admin, project, key=key)
        response = admin.post(base+'/'+batch['id']+'/items/'+item['client_id'], files={'file': ('data.xlsx', content)})
        assert response.status_code == 202, response.text
        return response.json()
    old = upload('old')
    with database_connection() as db:
        before = dict(db.execute('SELECT input_snapshot,input_digest FROM tasks WHERE id=%s', (old['task']['id'],)).fetchone())
        binding = db.execute("SELECT version_id FROM admin_configuration_bindings WHERE object_id=%s", (old['task']['id'],)).fetchone()
        assert binding and binding['version_id'] == one['id']
    two = saved(admin, one, 'basic', 'max_rows', 10); activate(admin, two, 1, 'rows')
    def timeout(*args, **kwargs):
        raise StorageError('parse_timeout', 'synthetic timeout', 422)
    failed = run_parse_file_task(old['task']['id'], 1, parser=timeout)
    assert failed['status'] == 'failed'
    retry = admin.post('/api/v1/tasks/'+failed['id']+'/resume', headers={'Idempotency-Key': 'retry'}, json={
        'operation': 'retry', 'wait_id': None, 'expected_task_revision': failed['revision'], 'input_version': failed['input_version']})
    assert retry.status_code == 202, retry.text
    seen = []
    def parser(content, filename, settings, **kwargs):
        seen.append(settings['excel']['max_rows'])
        return deterministic(content, filename, settings, **kwargs)
    assert run_parse_file_task(old['task']['id'], retry.json()['revision'], parser=parser)['status'] == 'succeeded'
    new = upload('new')
    assert run_parse_file_task(new['task']['id'], 1, parser=parser)['status'] == 'failed'
    assert seen == [100000, 10]
    with database_connection() as db:
        assert dict(db.execute('SELECT input_snapshot,input_digest FROM tasks WHERE id=%s', (old['task']['id'],)).fetchone()) == before
        assert db.execute("SELECT version_id FROM admin_configuration_bindings WHERE object_id=%s", (new['task']['id'],)).fetchone()['version_id'] == two['id']


def test_legacy_complete_parse_preserves_contract_but_missing_settings_blocks(admin):
    # Create the old task before the first explicit active version.
    project = create_project(admin)
    base, batch, item, content = register(admin, project)
    response = admin.post(base+'/'+batch['id']+'/items/'+item['client_id'], files={'file': ('data.xlsx', content)})
    assert response.status_code == 202, response.text
    one = baseline(admin); activate(admin, one)
    two = saved(admin, one, 'basic', 'max_rows', 10)
    activate(admin, two, 1, 'safe-legacy')
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET input_snapshot=input_snapshot-'settings' WHERE id=%s", (response.json()['task']['id'],))
    three = saved(admin, two, 'basic', 'max_rows', 15); validated(admin, three)
    blocked = switch(admin, three, 2, 'missing-settings')
    assert blocked.status_code == 409
    assert blocked.json()['detail']['code'] == 'configuration_legacy_inflight'


def test_deployment_ceiling_and_catalog_are_independent_of_active(admin, monkeypatch):
    monkeypatch.setenv('EXCEL_MAX_ROWS', '100')
    one = baseline(admin)
    assert one['bundle']['basic']['max_rows'] == 100
    activate(admin, one)
    two = saved(admin, one, 'basic', 'max_rows', 20); activate(admin, two, 1, 'rows')
    activate(admin, one, 2, 'rollback', 'rollback')
    too_high = saved(admin, one, 'basic', 'max_rows', 101)
    result = admin.post(ROOT+'/'+too_high['id']+'/validate', json={}).json()
    assert result['status'] == 'failed'
    from app.core.config import get_request_excel_settings, get_excel_settings
    monkeypatch.setenv('EXCEL_MAX_ROWS', '50')
    assert get_request_excel_settings().max_rows == 50
    assert get_excel_settings().max_rows == 50  # Existing analysis getter remains deployment-only.
    catalog = admin.get(ROOT+'/catalog').json()
    assert catalog['field_effects']['basic.max_upload_bytes'] == 'new_request'
    assert catalog['restart_required']['basic.max_rows'] is False
    assert catalog['effective_ranges']['basic.max_rows'] == {'minimum':1,'maximum':50,'unit':'rows'}
    assert catalog['field_readonly']['basic.worker_concurrency'] is False
    assert catalog['restart_required']['basic.worker_concurrency'] is True
    assert catalog['field_readonly']['ncbi.enabled'] is True


def test_ncbi_version_is_bound_cache_ttl_consumed_and_retry_keeps_old(admin, monkeypatch):
    from app.domain.literature import execution
    from tests.api.test_literature import create
    from tests.helpers.literature import SyntheticNcbi
    one = baseline(admin); activate(admin, one)
    pid = create_project(admin)['id']
    old = create(admin, pid, key='old').json()
    provider = SyntheticNcbi(1, fail_fetches=1)
    seen = []
    original = execution.Retrieval.obtain
    def obtain(self, operation, request):
        seen.append((self.parameters['interval_seconds'], self.parameters['cache_ttl_seconds'], self.parameters['timeout_seconds']))
        return original(self, operation, request)
    monkeypatch.setattr(execution.Retrieval, 'obtain', obtain)
    first = execution.run_literature_task(old['id'], old['revision'], client=provider)
    assert first['status'] == 'running' and first['retry_count'] == 1
    two = saved(admin, one, 'ncbi', 'cache_ttl_seconds', 0)
    two = saved(admin, two, 'ncbi', 'interval_seconds', 2.0)
    two = saved(admin, two, 'ncbi', 'timeout_seconds', 3)
    activate(admin, two, 1, 'ncbi')
    assert execution.run_literature_task(old['id'], first['revision'], client=provider)['status'] == 'succeeded'
    assert seen == [(0.5,86400,30),(0.5,86400,30),(0.5,86400,30)]
    # Same project + owner + digest hits cached originals with the old TTL.
    activate(admin, one, 2, 'restore', 'rollback')
    cached = create(admin, pid, key='cached').json()
    assert execution.run_literature_task(cached['id'],1,client=provider)['status'] == 'succeeded'
    assert len(provider.calls) == 3
    other = create(admin, create_project(admin)['id'], key='other').json()
    assert execution.run_literature_task(other['id'],1,client=provider)['status'] == 'succeeded'
    assert len(provider.calls) == 5  # A different project never hits the first cache.
    activate(admin, two, 3, 'zero-ttl')
    uncached = create(admin, pid, key='no-cache').json()
    assert execution.run_literature_task(uncached['id'],1,client=provider)['status'] == 'succeeded'
    assert len(provider.calls) == 7
    assert seen[-2:] == [(2.0,0,3),(2.0,0,3)]
    with database_connection() as db:
        for task, version in [(old,one),(cached,one),(uncached,two)]:
            assert db.execute("SELECT version_id FROM admin_configuration_bindings WHERE object_id=%s", (task['id'],)).fetchone()['version_id'] == version['id']
        assert len(db.execute("SELECT 1 FROM literature_fetch_receipts WHERE cached_from_id IS NOT NULL").fetchall()) == 2


def test_two_versions_share_one_database_limiter(admin):
    from concurrent.futures import ThreadPoolExecutor
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.domain.literature.execution import reserve_request
    from tests.api.test_literature import create
    one = baseline(admin); activate(admin, one)
    pid = create_project(admin)['id']
    old = create(admin,pid,key='old').json()
    two = saved(admin,one,'ncbi','interval_seconds',2.0); activate(admin,two,1,'slower')
    new = create(admin,pid,key='new').json()
    repository = TaskExecutionStore()
    leases = [repository.claim(task['id'],1,task_type='literature_search') for task in (old,new)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        delays = sorted(pool.map(lambda lease: reserve_request(repository,lease),leases))
    assert delays[0] == 0 and delays[1] > 0.4
    with database_connection() as db:
        rows = db.execute('SELECT scope,next_allowed_at-clock_timestamp() AS remaining FROM ncbi_rate_limits').fetchall()
        assert len(rows) == 1 and rows[0]['scope'] == 'ncbi-eutilities'
        assert rows[0]['remaining'].total_seconds() > 2.0


def test_ncbi_worker_constructs_bound_timeout_but_never_opens_disabled_gate(admin,monkeypatch):
    from app.adapters import ncbi
    from app.domain.literature import execution
    from tests.api.test_literature import create
    from tests.adapters.test_ncbi import Session, Response, search_data
    monkeypatch.setenv('PAPERASSIST_NCBI_EMAIL','synthetic@example.invalid')
    one = baseline(admin)
    one = saved(admin,one,'ncbi','timeout_seconds',3)
    activate(admin,one)
    monkeypatch.setenv('PAPERASSIST_NCBI_ENABLED','1')
    pid = create_project(admin)['id']
    task = create(admin,pid).json()
    session = Session(Response(search_data()))
    constructed = []
    def factory(settings=None, **kwargs):
        client = ncbi.NcbiClient(settings,session=session,**kwargs)
        constructed.append(client)
        return client
    monkeypatch.setattr(execution,'NcbiClient',factory)
    result = execution.run_literature_task(task['id'],1)
    assert result['status'] == 'waiting_confirmation'
    assert len(constructed) == 1 and constructed[0].timeout == (3,3)
    assert session.calls == []
    assert admin.get('/api/v1/tasks/'+task['id']+'/workspace').json()['allowed_actions'] == []
    assert admin.get(ROOT+'/catalog').json()['real_connectivity'] == 'not_tested'


def test_ncbi_and_basic_reject_out_of_contract_values(admin):
    one = baseline(admin)
    for domain,field,value in [('ncbi','interval_seconds',0.49),('ncbi','interval_seconds',True),
            ('ncbi','cache_ttl_seconds',86401),('ncbi','cache_ttl_seconds',True),
            ('ncbi','timeout_seconds',31),('ncbi','enabled',True),
            ('basic','max_upload_bytes',10485761),('basic','max_rows',True),('basic','worker_concurrency',3)]:
        bundle = deepcopy(one['bundle']); bundle[domain][field] = value
        assert admin.post(ROOT+'/'+one['id']+'/save',json={'bundle':bundle}).status_code == 422
    for identity in [{'alias':'openai-default','revision':'deployment-v1'}, {'alias':'ncbi-default','revision':'unknown'}]:
        bundle = deepcopy(one['bundle']); bundle['ncbi']['identity'] = identity
        response = admin.post(ROOT+'/'+one['id']+'/save',json={'bundle':bundle})
        if response.status_code == 201:
            evidence = admin.post(ROOT+'/'+response.json()['id']+'/validate',json={}).json()
            assert evidence['status'] == 'failed' and 'identity_not_registered' in evidence['domains']['ncbi']['errors']
        else:
            assert response.status_code == 422


def test_structure_tasks_freeze_current_settings_and_binding(admin):
    from tests.api.test_datasets import prepared, generate, structure_parser
    from app.domain.tasks.dataset_execution import run_dataset_task
    one = baseline(admin); activate(admin,one)
    _, _, _, base = prepared(admin)
    old = generate(admin,base,0,'old')['task']
    two = saved(admin,one,'basic','max_rows',10); activate(admin,two,1,'rows')
    seen = []
    def parser(content,filename,settings):
        seen.append(settings['excel']['max_rows'])
        return structure_parser(content,filename,settings)
    assert run_dataset_task(old['id'],1,parser=parser)['status'] == 'succeeded'
    new = generate(admin,base,1,'new')['task']
    assert run_dataset_task(new['id'],1,parser=parser)['status'] == 'failed'
    assert seen == [100000,10]
    with database_connection() as db:
        for task,version in [(old,one),(new,two)]:
            assert db.execute("SELECT version_id FROM admin_configuration_bindings WHERE object_id=%s", (task['id'],)).fetchone()['version_id'] == version['id']


@pytest.mark.parametrize('kind',['parse_file','literature_search'])
def test_business_task_binding_and_outbox_are_one_transaction(admin,kind):
    from app.db.database import migration_connection
    from tests.api.test_literature import create
    one = baseline(admin); activate(admin,one)
    project = create_project(admin)
    if kind == 'parse_file':
        base,batch,item,content = register(admin,project)
    with migration_connection(write=True) as db:
        db.execute("CREATE FUNCTION reject_b_ready() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic outbox failure'; END $$")
        db.execute('CREATE TRIGGER reject_b_ready BEFORE INSERT ON task_outbox FOR EACH ROW EXECUTE FUNCTION reject_b_ready()')
    if kind == 'parse_file':
        response = admin.post(base+'/'+batch['id']+'/items/'+item['client_id'],files={'file':('data.xlsx',content)})
    else:
        response = create(admin,project['id'])
    assert response.status_code == 503, response.text
    with database_connection() as db:
        for table in ('tasks','admin_configuration_bindings','task_outbox','file_parse_results','literature_searches'):
            assert db.execute('SELECT count(*) AS n FROM '+table).fetchone()['n'] == 0


def test_legacy_fixed_document_contracts_are_not_blocked_by_excel_dimensions(admin):
    project = create_project(admin)
    for extension in ('docx','pdf','png'):
        base,batch,item,content = register(admin,project,b'synthetic original bytes','synthetic.'+extension,extension)
        response = admin.post(base+'/'+batch['id']+'/items/'+item['client_id'],files={'file':(item['filename'],content)})
        assert response.status_code == 202, response.text
    one = baseline(admin); activate(admin,one)
    two = saved(admin,one,'basic','max_rows',10); activate(admin,two,1,'rows')
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM admin_configuration_bindings').fetchone()['n'] == 0
