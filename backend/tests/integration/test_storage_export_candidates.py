"""Actual A2d business boundaries; synthetic isolated fixtures, no remote calls."""
from contextlib import contextmanager
from datetime import datetime
from hashlib import sha256
import json

import pytest

from app.adapters.storage import get_project_store
from app.core.exceptions import StorageError
from app.domain.storage_governance.service import reconcile_intents, set_policy, usage
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_boxplot import cloud  # noqa: F401
from tests.integration.test_explanations import writer  # noqa: F401


def test_generate_report_first_precommit_recovers_original_without_render(client, cloud, writer, monkeypatch):
    from tests.integration.test_reports import report_ready
    from app.domain import reports
    from app.adapters.report_store import ReportStore
    base, file, result, figure, explanation, _ = report_ready(client)
    project = base.split('/')[4]
    assets = get_project_store()
    request = reports.ReportRequest(expected_revision=result['setup_revision'], figure_id=figure['id'], explanation_id=explanation['id'])
    connection = assets.connection
    captured = {}
    metadata = ReportStore.metadata

    def remember(snapshot):
        captured.update(metadata(snapshot))
        return dict(captured)

    @contextmanager
    def interrupted(write=False):
        with connection(write=write) as db:
            yield db
            if write and db.execute('SELECT 1 FROM reports WHERE id=%s', (captured.get('id'),)).fetchone():
                raise StorageError('storage_unavailable', 'Synthetic true precommit rollback')

    monkeypatch.setattr(ReportStore, 'metadata', staticmethod(remember))
    monkeypatch.setattr(assets, 'connection', interrupted)
    with pytest.raises(StorageError):
        reports.generate_report(project, file['id'], result['id'], request, assets)
    monkeypatch.setattr(assets, 'connection', connection)
    target = assets.directory/'reports'/(captured['id']+'.docx')
    raw = target.read_bytes()
    with connection(write=True) as db:
        assert not db.execute('SELECT 1 FROM reports WHERE id=%s', (captured['id'],)).fetchone()
        assert reconcile_intents(db, assets.directory) == 0
        set_policy(db, 'project', project, 0, 'enforced')
    def forbidden(*args, **kwargs):
        pytest.fail('Complete original candidate must bypass new identity and rendering')
    monkeypatch.setattr(ReportStore, 'metadata', staticmethod(forbidden))
    monkeypatch.setattr(reports, 'build_report', forbidden)
    with pytest.raises(StorageError) as error:
        reports.generate_report(project, file['id'], result['id'], request, assets)
    assert error.value.code == 'storage_quota_exceeded'
    with connection(write=True) as db:
        set_policy(db, 'project', project, 10**8, 'enforced')
    restored, code = reports.generate_report(project, file['id'], result['id'], request, assets)
    report = restored['report']
    assert code == 201 and all(report[k] == v for k, v in captured.items())
    assert report['sha256'] == sha256(raw).hexdigest() and target.read_bytes() == raw
    with connection(write=True) as db:
        set_policy(db, 'project', project, 0, 'enforced')
    assert reports.generate_report(project, file['id'], result['id'], request, assets)[0]['report'] == report


@pytest.mark.parametrize('source_kind',['original','replacement','document_version','local_boxplot'])
def test_language_http_first_precommit_preserves_key_identity_and_read_replay(client, monkeypatch, source_kind):
    from tests.api.test_manuscript_figure_language import setup
    from tests.api.test_literature_evidence import post
    from app.adapters.task_store import TaskStore
    project, _, url, body = language_source(client,source_kind)
    assets = get_project_store()
    connection = TaskStore.connection
    captured = {}

    @contextmanager
    def interrupted(self, write=False):
        with connection(self, write=write) as db:
            yield db
            if write:
                row = db.execute('SELECT * FROM manuscript_figure_language_versions WHERE project_id=%s', (project,)).fetchone()
                if row:
                    captured.update(dict(row))
                    raise StorageError('storage_unavailable', 'Synthetic true precommit rollback')

    monkeypatch.setattr(TaskStore, 'connection', interrupted)
    interrupted_response=post(client,url,body,'a2d-original')
    assert interrupted_response.status_code>=400 and captured,interrupted_response.text
    monkeypatch.setattr(TaskStore, 'connection', connection)
    target = assets.directory/'manuscript_figure_language_versions'/(captured['id']+'.png')
    raw = target.read_bytes()
    with assets.connection(write=True) as db:
        assert not db.execute('SELECT 1 FROM manuscript_figure_language_versions WHERE id=%s', (captured['id'],)).fetchone()
        assert reconcile_intents(db, assets.directory) == 0
        set_policy(db, 'project', project, 0, 'enforced')
    conflict = post(client, url, body|{'reason':'A different explicitly inspected request'}, 'a2d-original')
    assert conflict.status_code == 409 and conflict.json()['detail']['code'] == 'task_idempotency_conflict'
    failed = post(client, url, body, 'a2d-original')
    assert failed.status_code == 409 and failed.json()['detail']['code'] == 'storage_quota_exceeded'
    with assets.connection(write=True) as db:
        set_policy(db, 'project', project, 10**8, 'enforced')
    restored = post(client, url, body, 'a2d-original')
    assert restored.status_code == 201, restored.text
    saved = restored.json()
    assert saved['id'] == captured['id'] and datetime.fromisoformat(saved['created_at']) == captured['created_at']
    assert saved['snapshot_sha256'] == captured['snapshot_sha256']
    assert client.get(saved['download_url']).content == raw == target.read_bytes()
    with assets.connection(write=True) as db:
        set_policy(db, 'project', project, 0, 'enforced')
    replay = post(client, url, body, 'a2d-original')
    assert replay.status_code == 200 and replay.json() == saved


@pytest.mark.parametrize('kind', ['pdf', 'layout'])
def test_conversion_precommit_candidate_survives_cleanup_and_retries_original(client, monkeypatch, kind):
    from types import SimpleNamespace
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.domain.tasks.execution import run_task
    from tests.api.test_layout_exports import prepared
    from tests.api.test_pdf_exports import successful_docx
    for module in ('pdf_exports', 'layout_exports'):
        monkeypatch.setattr('app.domain.'+module+'.service.renderer_identity', lambda: {'contract':'test-v1'})
        monkeypatch.setattr('app.domain.'+module+'.execution.renderer_identity', lambda: {'contract':'test-v1'})
    if kind == 'layout':
        url, source, request = prepared(client)
    else:
        url, source = successful_docx(client)
        request = dict(source_kind='manuscript_export', source_id=source['id'], request_key='storage-pdf')
    saved = client.post(url, json=request).json()
    assets = get_project_store()
    original_source = (assets.directory/'manuscript_exports'/(source['id']+'.docx')).read_bytes()
    calls = []
    def render(raw, *args, **kwargs):
        calls.append(raw)
        return raw if kind == 'layout' else SimpleNamespace(content=b'%PDF-1.7\nsynthetic-control-only', manifest={'contract':'test-v1'})
    monkeypatch.setattr('app.domain.'+kind+'_exports.execution.'+('prepare_layout_docx' if kind == 'layout' else 'render_pdf'), render)
    connection = TaskExecutionStore.connection
    captured = {}
    @contextmanager
    def interrupted(self, write=False):
        with connection(self, write=write) as db:
            yield db
            if write and not captured:
                row = db.execute('SELECT metadata_json FROM '+kind+'_exports WHERE id=%s', (saved['id'],)).fetchone()
                if row and row['metadata_json']:
                    captured.update(row['metadata_json'])
                    raise StorageError('storage_unavailable', 'Synthetic true precommit rollback')
    monkeypatch.setattr(TaskExecutionStore, 'connection', interrupted)
    run_task(saved['task_id'], 1)
    monkeypatch.setattr(TaskExecutionStore, 'connection', connection)
    target = assets.directory/(kind+'_exports')/captured['object_name']
    assert target.exists(), 'Complete candidate must survive actual except/finally cleanup'
    raw = target.read_bytes()
    with assets.connection(write=True) as db:
        reconcile_intents(db, assets.directory)
        task = dict(db.execute('SELECT * FROM tasks WHERE id=%s', (saved['task_id'],)).fetchone())
        assert task['status'] == 'failed'
        from importlib import import_module
        import_module('app.domain.'+kind+'_exports.execution').clean_expired_attempt(TaskExecutionStore(), db, task)
        set_policy(db, 'project', task['project_id'], 0, 'enforced')
    rejected = client.post(url+'/'+saved['id']+'/retry', json={'request_key':'restore-original'})
    assert rejected.status_code == 409 and rejected.json()['detail']['code'] == 'storage_quota_exceeded'
    with assets.connection(write=True) as db:
        set_policy(db, 'project', task['project_id'], 10**8, 'enforced')
    response = client.post(url+'/'+saved['id']+'/retry', json={'request_key':'restore-original'})
    assert response.status_code == 202, response.text
    restored = response.json()
    assert restored['id'] == saved['id'] and restored['task_id'] == saved['task_id']
    assert restored['recovery_mode'] == 'local_candidate' and restored['recovery_request_key'] == 'restore-original'
    task = client.get('/api/v1/tasks/'+saved['task_id']).json()
    assert run_task(saved['task_id'], task['revision'])['status'] == 'succeeded'
    assert len(calls) == 1
    complete = client.get(url+'/'+saved['id']).json()
    assert complete['sha256'] == sha256(raw).hexdigest()
    assert client.get(complete['download_url']).content == raw
    assert target.read_bytes() == raw
    assert (assets.directory/'manuscript_exports'/(source['id']+'.docx')).read_bytes() == original_source
    replay = client.post(url+'/'+saved['id']+'/retry', json={'request_key':'restore-original'})
    assert replay.status_code == 200 and replay.json()['id'] == saved['id']


@pytest.mark.parametrize('kind', ['word_report', 'manuscript_docx', 'review_document_export'])
def test_actual_local_export_admission_blocks_unmetered_bytes(client, cloud, writer, kind):
    from app.domain.tasks.execution import run_task
    if kind == 'word_report':
        from tests.integration.test_reports import report_ready
        base, _, _, figure, explanation, url = report_ready(client)
        result = client.post(url, json=dict(expected_revision=figure['setup_revision'], figure_id=figure['id'], explanation_id=explanation['id'])).json()
        task_id = result['task']['id']; directory = 'reports'
    elif kind == 'manuscript_docx':
        from tests.api.test_manuscripts import setup, body
        from tests.api.test_literature_evidence import post
        path, _, _ = setup(client)
        root = post(client, path, body(), 'storage-draft').json()
        run_task(root['versions'][0]['task_id'], 1)
        result = post(client,path+'/'+root['id']+'/versions/1/exports',{},'storage-docx').json()
        task_id = result['task_id']; directory = 'manuscript_exports'
    else:
        from tests.api.test_review_documents import completed_revision, create_document
        url, run = completed_revision(client); doc = create_document(client,url,run)
        result = client.post(url+'/documents/'+doc['id']+'/exports',json={},headers={'Idempotency-Key':'storage-review'}).json()
        task_id = result['task_id']; directory = 'review_document_exports'
    assets = get_project_store()
    with assets.connection(write=True) as db:
        task = db.execute('SELECT * FROM tasks WHERE id=%s',(task_id,)).fetchone()
        set_policy(db,'project',task['project_id'],0,'enforced')
    before = {p: p.read_bytes() for p in (assets.directory/directory).glob('*') if p.is_file()}
    result = run_task(task_id,1)
    assert result['status'] == 'failed' and result['error_code'] == 'storage_quota_exceeded', result
    assert {p:p.read_bytes() for p in (assets.directory/directory).glob('*') if p.is_file()} == before


from tests.integration.test_batch05_collection_persistence import collection_case  # noqa: F401


def test_collection_admission_blocks_unmetered_bytes(collection_case):
    from tests.integration.test_batch05_collection_persistence import body
    from app.domain.report_collections.execution import run_collection_word_task
    repository, project, sample, explanation = collection_case
    request = body(sample); request.items[0].explanation_id = explanation['id']
    saved = repository.create(project,request,'storage-collection')
    task = saved['versions'][0]['requests'][0]
    with repository.store.connection(write=True) as db:
        set_policy(db,'project',project,0,'enforced')
    result = run_collection_word_task(task['task_id'],1,config=repository.store.db_config,directory=repository.store.directory)
    assert result['status']=='failed' and result['error_code']=='storage_quota_exceeded', result
    assert not list(repository.directory.glob('*.docx'))


@pytest.mark.parametrize('operation',['literature','pmc'])
def test_actual_literature_admits_before_request_and_accounts_reused_bytes(client,tmp_path,operation):
    from tests.api.test_literature import project,create
    from tests.helpers.literature import SyntheticNcbi
    from tests.integration.test_literature_workflow import execute
    assets=get_project_store()
    if operation=='pmc':
        from tests.integration.test_literature_pmc import prepare
        pid,_,ref,service,adapter,calls,_=prepare(client,tmp_path)
        produce=lambda: service.acquire(pid,ref['id'],'PMC123','storage-pmc',adapter=adapter)
    else:
        pid=project(client);task=create(client,pid).json();provider=SyntheticNcbi(2);calls=provider.calls
        produce=lambda: execute(task,provider)
    with assets.connection(write=True) as db:
        set_policy(db,'project',pid,0,'enforced')
    if operation=='pmc':
        with pytest.raises(StorageError) as error: produce()
        assert error.value.code=='storage_quota_exceeded'
    else:
        failed=produce()
        assert failed['status']=='failed' and failed['error_code']=='storage_quota_exceeded'
    assert calls==[], 'Storage admission must precede the external read'
    with assets.connection(write=True) as db:
        set_policy(db,'project',pid,10**8,'enforced')
    if operation=='literature':
        # Enable only the public retry configuration gate; the provider remains synthetic.
        from app.domain.literature import service as literature_service
        from unittest.mock import patch
        with patch.object(literature_service,'configuration',return_value={'available':True}):
            response=client.post('/api/v1/tasks/'+task['id']+'/retry',json={'expected_revision':failed['revision']})
        assert response.status_code==202,response.text
        task=response.json()
    assert produce()
    with assets.connection() as db:
        rows=db.execute("SELECT o.* FROM storage_objects o JOIN storage_references r ON r.object_id=o.id WHERE r.project_id=%s AND o.object_key LIKE 'literature/%%'",(pid,)).fetchall()
        actual=list((assets.directory/'literature').rglob('*.xml'))+list((assets.directory/'literature').rglob('*.json'))
        assert rows and {r['object_key'] for r in rows}=={p.relative_to(assets.directory).as_posix() for p in actual}
        for row in rows: assert sha256((assets.directory/row['object_key']).read_bytes()).hexdigest()==row['sha256']
        before=usage(db,project_id=pid)['usage_bytes']
    calls_before=len(calls)
    if operation=='pmc':
        with assets.connection(write=True) as db: set_policy(db,'project',pid,0,'enforced')
        assert produce()[1]==200
    else:
        cached=create(client,pid,key='storage-cache').json()
        assert execute(cached,provider)['status']=='succeeded'
    assert len(calls)==calls_before
    with assets.connection() as db: assert usage(db,project_id=pid)['usage_bytes']==before


@pytest.mark.parametrize('kind',['word_report','manuscript_docx','review_document_export'])
def test_local_docx_first_precommit_retries_original_without_render(client,cloud,writer,monkeypatch,kind):
    from app.domain.tasks.execution import run_task
    from app.adapters.task_execution_store import TaskExecutionStore
    if kind=='word_report':
        from tests.integration.test_reports import report_ready
        _,_,_,figure,explanation,url=report_ready(client)
        task=client.post(url,json=dict(expected_revision=figure['setup_revision'],figure_id=figure['id'],explanation_id=explanation['id'])).json()['task']
        table,column='reports','report_json';render='app.domain.tasks.execution.build_report'
    elif kind=='manuscript_docx':
        from tests.api.test_manuscripts import setup,body
        from tests.api.test_literature_evidence import post
        path,_,_=setup(client);root=post(client,path,body(),'rollback-draft').json()
        run_task(root['versions'][0]['task_id'],1)
        export=post(client,path+'/'+root['id']+'/versions/1/exports',{},'rollback-docx').json()
        task={'id':export['task_id']};table,column='manuscript_exports','metadata_json';render='app.adapters.manuscript_docx.build_manuscript_docx'
    else:
        from tests.api.test_review_documents import completed_revision,create_document
        url,run=completed_revision(client);doc=create_document(client,url,run)
        export=client.post(url+'/documents/'+doc['id']+'/exports',json={},headers={'Idempotency-Key':'rollback-review'}).json()
        task={'id':export['task_id']};table,column='review_document_exports','artifact_json';render='app.domain.review_rounds.document_execution.render_review_document'
    assets=get_project_store();connection=TaskExecutionStore.connection;captured={}
    @contextmanager
    def interrupted(self,write=False):
        with connection(self,write=write) as db:
            yield db
            current=db.execute('SELECT * FROM tasks WHERE id=%s',(task['id'],)).fetchone()
            if write and not captured and current and current['status']=='succeeded':
                row=db.execute('SELECT '+column+' FROM '+table+' WHERE '+('id=%s' if kind=='word_report' else 'task_id=%s'),
                    (current['result_report_id'] if kind=='word_report' else task['id'],)).fetchone()
                captured.update(json.loads(row[column]) if isinstance(row[column],str) else row[column])
                raise StorageError('storage_unavailable','Synthetic true precommit rollback')
    monkeypatch.setattr(TaskExecutionStore,'connection',interrupted)
    run_task(task['id'],1)
    monkeypatch.setattr(TaskExecutionStore,'connection',connection)
    with assets.connection(write=True) as db:
        reconcile_intents(db,assets.directory)
        hold=db.execute("SELECT * FROM storage_reservations WHERE task_id=%s AND operation_key=%s",(task['id'],'export-task:'+task['id'])).fetchone()
        current=dict(db.execute('SELECT * FROM tasks WHERE id=%s',(task['id'],)).fetchone())
        assert current['status']=='failed' and hold
    target=assets.directory/hold['object_key'];raw=target.read_bytes()
    assert sha256(raw).hexdigest()==captured['sha256']
    def forbidden(*args,**kwargs):pytest.fail('Retained DOCX must not be rendered again')
    monkeypatch.setattr(render,forbidden)
    response=client.post('/api/v1/tasks/'+task['id']+'/retry',json={'expected_revision':current['revision']})
    assert response.status_code==202,response.text
    assert response.json()['id']==task['id']
    assert run_task(task['id'],response.json()['revision'])['status']=='succeeded'
    with assets.connection() as db:
        current=db.execute('SELECT * FROM tasks WHERE id=%s',(task['id'],)).fetchone()
        row=db.execute('SELECT '+column+' FROM '+table+' WHERE '+('id=%s' if kind=='word_report' else 'task_id=%s'),
            (current['result_report_id'] if kind=='word_report' else task['id'],)).fetchone()
        assert (json.loads(row[column]) if isinstance(row[column],str) else row[column])==captured
    assert target.read_bytes()==raw


def test_collection_precommit_restores_original_without_render(collection_case,client,monkeypatch):
    from tests.integration.test_batch05_collection_persistence import body
    from app.domain.report_collections.execution import run_collection_word_task
    from app.adapters.task_execution_store import TaskExecutionStore
    repository,project,sample,explanation=collection_case
    request=body(sample);request.items[0].explanation_id=explanation['id']
    root=repository.create(project,request,'rollback-collection');intent=root['versions'][0]['requests'][0]
    connection=TaskExecutionStore.connection;captured={}
    @contextmanager
    def interrupted(self,write=False):
        with connection(self,write=write) as db:
            yield db
            if write and not captured:
                row=db.execute('SELECT report_json FROM collection_reports WHERE build_request_id=%s',(intent['id'],)).fetchone()
                if row:
                    captured.update(row['report_json'])
                    raise StorageError('storage_unavailable','Synthetic collection precommit rollback')
    monkeypatch.setattr(TaskExecutionStore,'connection',interrupted)
    run_collection_word_task(intent['task_id'],1)
    monkeypatch.setattr(TaskExecutionStore,'connection',connection)
    task=client.get('/api/v1/tasks/'+intent['task_id']).json();assert task['status']=='failed'
    target=repository.directory/(captured['id']+'.docx');raw=target.read_bytes()
    def forbidden(*args,**kwargs):pytest.fail('Retained collection must not be rendered again')
    monkeypatch.setattr('app.domain.report_collections.execution.build_collection_report',forbidden)
    retry=client.post('/api/v1/tasks/'+intent['task_id']+'/retry',json={'expected_revision':task['revision']})
    assert retry.status_code==202,retry.text
    assert run_collection_word_task(intent['task_id'],retry.json()['revision'])['status']=='succeeded'
    metadata,download=repository.download(project,root['id'],captured['id'])
    assert metadata==captured and download==raw==target.read_bytes()


def test_literature_precommit_retains_original_response_without_refetch(client,monkeypatch):
    from tests.api.test_literature import project,create
    from tests.helpers.literature import SyntheticNcbi
    from tests.integration.test_literature_workflow import execute
    from app.domain.literature.execution import Retrieval
    from app.domain.literature import service
    pid=project(client);task=create(client,pid).json();provider=SyntheticNcbi(1)
    receipt=Retrieval.receipt;once=[]
    def fail(self,db,current,operation,request,**kwargs):
        result=receipt(self,db,current,operation,request,**kwargs)
        if operation=='esearch' and not once:
            once.append(result)
            raise StorageError('storage_unavailable','Synthetic receipt precommit rollback')
        return result
    monkeypatch.setattr(Retrieval,'receipt',fail)
    failed=execute(task,provider)
    assert failed['status']=='failed' and [c[0] for c in provider.calls]==['esearch']
    monkeypatch.setattr(Retrieval,'receipt',receipt)
    monkeypatch.setattr(service,'configuration',lambda *a,**k:{'available':True})
    retry=client.post('/api/v1/tasks/'+task['id']+'/retry',json={'expected_revision':failed['revision']})
    assert retry.status_code==202,retry.text
    assert execute(retry.json(),provider)['status']=='succeeded'
    assert [c[0] for c in provider.calls]==['esearch','efetch']


def test_pmc_precommit_restores_original_receipt_without_adapter(client,tmp_path,monkeypatch):
    from tests.integration.test_literature_pmc import prepare
    pid,_,ref,service,adapter,calls,_=prepare(client,tmp_path)
    connection=service.store.connection;captured={}
    @contextmanager
    def interrupted(write=False):
        with connection(write=write) as db:
            yield db
            if write:
                row=db.execute('SELECT * FROM literature_pmc_receipts WHERE project_id=%s',(pid,)).fetchone()
                if row:
                    captured.update(dict(row))
                    raise StorageError('storage_unavailable','Synthetic PMC precommit rollback')
    monkeypatch.setattr(service.store,'connection',interrupted)
    with pytest.raises(StorageError):service.acquire(pid,ref['id'],'PMC123','pmc-rollback',adapter=adapter)
    monkeypatch.setattr(service.store,'connection',connection)
    assert len(calls)==2
    with connection(write=True) as db:set_policy(db,'project',pid,0,'enforced')
    with pytest.raises(StorageError) as error:service.acquire(pid,ref['id'],'PMC123','pmc-rollback')
    assert error.value.code=='storage_quota_exceeded'
    with connection(write=True) as db:set_policy(db,'project',pid,10**8,'enforced')
    restored,status=service.acquire(pid,ref['id'],'PMC123','pmc-rollback')
    assert status==201 and restored['id']==captured['id']
    assert datetime.fromisoformat(restored['created_at'])==captured['created_at'] and len(calls)==2
    with connection() as db:
        row=db.execute('SELECT * FROM literature_pmc_receipts WHERE id=%s',(captured['id'],)).fetchone()
        assert row['snapshot_sha256']==captured['snapshot_sha256'] and row['snapshot_json']==captured['snapshot_json']


def language_source(client,kind):
    from tests.api.test_manuscript_figure_language import setup,uploaded
    if kind in ('original','replacement'):
        project,file,url,body=setup(client)
        if kind=='replacement':
            replacement=uploaded(client,project,'blue')
            body=body|dict(mode='uploaded_replacement',replacement_file_id=replacement['id'],text_items=[dict(location='axis',text='Value')])
        return project,file,url,body
    if kind=='document_version':
        from tests.api.test_document_versions import uploaded_docx
        from app.domain.tasks.file_parse_execution import run_parse_file_task
        from app.adapters.docx_parser import parse_docx
        project,_,_,item,_=uploaded_docx(client)
        assert run_parse_file_task(item['task']['id'],1,parser=parse_docx)['status']=='succeeded'
        base=f"/api/v1/projects/{project['id']}/files/{item['file_id']}/document-versions"
        version=client.get(base).json()['items'][0];image=client.get(base+'/'+version['id']).json()['images'][0]
        raw=client.get(image['download_url']).content
        request=dict(source=dict(kind='document_version',id=version['id'],file_id=item['file_id'],image_id=image['id']),
            original_sha256=sha256(raw).hexdigest(),output_language='en',mode='no_text_confirmation',title='Synthetic image',
            caption='Local synthetic sample.',reason='Inspected exact document image with no text.')
        return project['id'],None,f"/api/v1/projects/{project['id']}/manuscript-figure-language-versions",request
    from uuid import uuid4
    from io import BytesIO
    from PIL import Image
    from tests.api.test_analysis import add_file
    from tests.domain.test_figure_language_renderer import frozen,labels
    base,file=add_file(client);project=base.split('/')[4]
    assets=get_project_store();analysis_id=str(uuid4());figure_id=str(uuid4())
    output=BytesIO();Image.new('RGB',(1600,1000),'white').save(output,format='PNG');raw=output.getvalue()
    figure=frozen()|dict(id=figure_id,analysis_run_id=analysis_id,title='原图',caption='原图说明',language='zh-CN',size_bytes=len(raw),sha256=sha256(raw).hexdigest())
    with assets.connection(write=True) as db:
        db.execute('INSERT INTO analysis_runs(id,file_id,setup_revision,engine_version,completed_at,result_json) VALUES (%s,%s,1,%s,%s,%s)',(analysis_id,file['id'],'synthetic_fixture','2026-10-21T00:00:00Z','{}'))
        db.execute('INSERT INTO figures(id,analysis_run_id,renderer_version,figure_json) VALUES (%s,%s,%s,%s)',(figure_id,analysis_id,'openai_boxplot_v1',json.dumps(figure)))
    assets.figures_dir.mkdir(parents=True,exist_ok=True);(assets.figures_dir/(figure_id+'.png')).write_bytes(raw)
    request=dict(source=dict(kind='figure',id=figure_id,file_id=file['id']),original_sha256=figure['sha256'],output_language='en',mode='local_boxplot',texts=labels(),reason='Translate frozen labels without changing geometry.')
    return project,file,f'/api/v1/projects/{project}/manuscript-figure-language-versions',request


@pytest.mark.parametrize('damage',['missing','changed'])
def test_complete_sync_companion_damage_blocks_without_overwriting_candidate(client,monkeypatch,damage):
    from tests.integration.test_storage_transactional_producers import sync_candidate
    project,store,produce,_=sync_candidate(client,'language')
    connection=store.connection;assets=get_project_store()
    @contextmanager
    def interrupted(write=False):
        with connection(write=write) as db:
            yield db
            if write:raise StorageError('storage_unavailable','Synthetic rollback before first commit')
    monkeypatch.setattr(store,'connection',interrupted)
    with pytest.raises(StorageError):produce()
    monkeypatch.setattr(store,'connection',connection)
    with connection(write=True) as db:
        reconcile_intents(db,assets.directory)
        row=db.execute("SELECT * FROM storage_reservations WHERE project_id=%s AND kind='figure_language'",(project,)).fetchone()
    target=assets.directory/row['object_key'];raw=target.read_bytes()
    companion=assets.directory/row['candidate_json']['descriptor']['object_key']
    if damage=='missing':companion.unlink()  # Only this test's newly-created synthetic fixture.
    else:companion.write_bytes(b'corrupt synthetic companion')
    with pytest.raises(StorageError) as error:produce()
    assert error.value.code=='storage_accounting_unknown' and target.read_bytes()==raw
    assert (not companion.exists()) if damage=='missing' else companion.read_bytes()==b'corrupt synthetic companion'
    with connection() as db:assert not db.execute('SELECT id FROM manuscript_figure_language_versions').fetchall()


def test_expired_staged_report_requires_manual_event_before_original_recovery(client,cloud,writer,monkeypatch):
    from tests.integration.test_reports import report_ready
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.domain.tasks.execution import run_word_task
    from app.adapters.report_docx import build_report
    _,_,_,figure,explanation,url=report_ready(client)
    task=client.post(url,json=dict(expected_revision=figure['setup_revision'],figure_id=figure['id'],explanation_id=explanation['id'])).json()['task']
    execution=TaskExecutionStore();lease=execution.claim(task['id'],1,task_type='word_report')
    snapshot,metadata,png=execution.load(lease);content=build_report(snapshot,metadata,png)
    staged=execution.stage(lease,content,snapshot,metadata)
    with execution.connection(write=True) as db:
        db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s",(task['id'],))
    assert execution.recover_expired()==1 and staged.read_bytes()==content
    failed=client.get('/api/v1/tasks/'+task['id']).json()
    assert failed['status']=='failed' and failed['error_code']=='storage_accounting_unknown'
    with execution.connection() as db:
        hold=db.execute('SELECT candidate_json FROM storage_reservations WHERE task_id=%s',(task['id'],)).fetchone()
        assert 'recovery_revision' not in hold['candidate_json']
        assert not db.execute("SELECT 1 FROM task_events WHERE task_id=%s AND retry_reason='worker_interrupted'",(task['id'],)).fetchone()
    def forbidden(*a,**k):pytest.fail('Expiry must preserve the captured report')
    monkeypatch.setattr('app.domain.tasks.execution.build_report',forbidden)
    retry=client.post('/api/v1/tasks/'+task['id']+'/retry',json={'expected_revision':failed['revision']})
    assert retry.status_code==202,retry.text
    assert run_word_task(task['id'],retry.json()['revision'])['status']=='succeeded'
    assert client.get(url+'/'+metadata['id']+'/download').content==content


def test_trusted_original_report_metadata_can_recover_legacy_v1_hold(client,cloud,writer):
    from tests.integration.test_reports import report_ready
    from app.domain.reports import context
    from app.adapters.report_store import ReportStore
    from app.domain.storage_governance.service import publication
    base,file,result,_,_,_=report_ready(client);assets=get_project_store();project=base.split('/')[4]
    snapshot,_=context(assets,project,file['id'],result['id']);repository=ReportStore(assets);metadata=repository.metadata(snapshot)
    target=repository.directory/(metadata['id']+'.docx');raw=b'original synthetic legacy report bytes'
    with pytest.raises(StorageError):
        with assets.connection(write=True) as db:
            with publication(db,assets.directory,project,'report:'+metadata['id'],target,raw,kind='report'):
                target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
            raise StorageError('storage_unavailable','Synthetic historical v1 precommit rollback')
    saved,created=repository.save(snapshot,metadata,raw)
    assert created and saved['id']==metadata['id'] and target.read_bytes()==raw
    with assets.connection() as db:assert usage(db,project_id=project)['reserved_bytes']==0


def test_pmc_receipt_envelope_failure_preserves_already_received_bounded_bodies(client,tmp_path,monkeypatch):
    from tests.integration.test_literature_pmc import prepare
    from app.domain.storage_governance import local_candidates
    pid,_,ref,service,adapter,calls,_=prepare(client,tmp_path)
    before={p for p in (service.assets.directory/'literature').rglob('*.xml')}
    encode=local_candidates.encode
    def bounded(value):
        if isinstance(value,dict) and 'snapshot_json' in value:
            raise StorageError('storage_accounting_unknown','Synthetic bounded envelope failure')
        return encode(value)
    monkeypatch.setattr(local_candidates,'encode',bounded)
    with pytest.raises(StorageError):service.acquire(pid,ref['id'],'PMC123','pmc-envelope-bound',adapter=adapter)
    assert len(calls)==2
    after={p for p in (service.assets.directory/'literature').rglob('*.xml')}-before
    assert len(after)==2 and all(p.read_bytes() for p in after)
    with service.store.connection(write=True) as db:
        reconcile_intents(db,service.assets.directory)
        rows=db.execute("SELECT * FROM storage_reservations WHERE project_id=%s AND kind='literature_pmc' AND sha256 IS NOT NULL",(pid,)).fetchall()
        assert len(rows)==2 and all(r['state']=='unknown' for r in rows)
    monkeypatch.setattr(local_candidates,'encode',encode)
    with pytest.raises(StorageError):service.acquire(pid,ref['id'],'PMC123','pmc-envelope-bound',adapter=adapter)
    assert len(calls)==2


def test_pmc_recovery_releases_only_proven_unwritten_slot_before_actual_quota_check(client,tmp_path,monkeypatch):
    import httpx
    from tests.integration.test_literature_pmc import prepare
    pid,_,ref,service,adapter,_,_=prepare(client,tmp_path)
    adapter.client.close()
    adapter.client=httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(503,content=b'')))
    connection=service.store.connection;captured={}
    with connection() as db:before=usage(db,project_id=pid)['usage_bytes']
    @contextmanager
    def interrupted(write=False):
        with connection(write=write) as db:
            yield db
            if write:
                row=db.execute('SELECT * FROM literature_pmc_receipts WHERE project_id=%s',(pid,)).fetchone()
                if row:
                    captured.update(dict(row))
                    raise StorageError('storage_unavailable','Synthetic incomplete-response receipt rollback')
    monkeypatch.setattr(service.store,'connection',interrupted)
    with pytest.raises(StorageError):service.acquire(pid,ref['id'],'PMC123','pmc-single-response',adapter=adapter)
    monkeypatch.setattr(service.store,'connection',connection)
    with connection(write=True) as db:
        reconcile_intents(db,service.assets.directory)
        rows=db.execute("SELECT * FROM storage_reservations WHERE project_id=%s AND kind='literature_pmc'",(pid,)).fetchall()
        assert len(rows)==3 and sum(r['sha256'] is None for r in rows)==1
        actual=sum(r['size_bytes'] for r in rows)
        set_policy(db,'project',pid,before+actual,'enforced')
    result,status=service.acquire(pid,ref['id'],'PMC123','pmc-single-response')
    assert status==201 and result['id']==captured['id'] and result['status']=='pmc_http_failed'
    assert service.raw(pid,result['id'],0)==b''
    with connection() as db:
        measured=usage(db,project_id=pid)
        assert measured['usage_bytes']==before+actual and measured['reserved_bytes']==0
