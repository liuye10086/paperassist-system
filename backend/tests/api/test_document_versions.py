from uuid import uuid4
from tests.api.test_projects import client, create_project
from tests.api.test_file_batches import register


def test_docx_upload_creates_word_snapshot_and_mime(client):
    project = create_project(client)
    base, batch, item, content = register(client, project, b'pending worker bytes', 'paper.docx')
    assert batch['items'][0]['status'] == 'pending'
    saved = client.post(base + '/' + batch['id'] + '/items/' + item['client_id'], files={'file': (item['filename'], content)})
    assert saved.status_code == 202, saved.text
    file_url = f"/api/v1/projects/{project['id']}/files/{saved.json()['file_id']}"
    assert client.get(file_url + '/download').headers['content-type'] == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    assert client.get(file_url + '/preview').status_code == 422
    versions = client.get(file_url + '/document-versions')
    assert versions.status_code == 200, versions.text
    assert versions.json()['items'][0]['version'] == 1
    assert versions.json()['items'][0]['status'] == 'queued'


def test_word_reparse_active_conflict(client):
    project = create_project(client)
    base, batch, item, content = register(client, project, b'pending worker bytes', 'paper.docx')
    saved = client.post(base + '/' + batch['id'] + '/items/' + item['client_id'], files={'file': (item['filename'], content)}).json()
    url = f"/api/v1/projects/{project['id']}/files/{saved['file_id']}/document-versions"
    assert client.post(url, headers={'Idempotency-Key': 'new'}, json={'expected_latest_version': 1}).status_code == 409

def uploaded_docx(client):
    from tests.helpers.document_samples import document_bytes
    project = create_project(client)
    base,batch,item,content = register(client,project,document_bytes(),'paper.docx')
    result = client.post(base+'/'+batch['id']+'/items/'+item['client_id'],files={'file':(item['filename'],content)})
    assert result.status_code == 202,result.text
    return project,base,batch,result.json(),content


def test_versions_remain_available_after_failed_reparse_and_batch_stable(client):
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    from app.adapters.docx_parser import parse_docx
    from app.core.exceptions import StorageError
    from app.db.database import database_connection
    project,base,batch,item,content = uploaded_docx(client)
    first = run_parse_file_task(item['task']['id'],1,parser=parse_docx)
    assert first['status']=='succeeded',first
    url=f"/api/v1/projects/{project['id']}/files/{item['file_id']}"
    versions=client.get(url+'/document-versions').json()
    version1=versions['items'][0]
    raw=client.get(version1['download_url'])
    assert raw.status_code==200,raw.text
    detail=client.get(url+'/document-versions/'+version1['id'])
    assert detail.status_code==200,detail.text
    assert detail.json()['summary']['counts']['images']==2
    image=detail.json()['images'][0]
    image_response=client.get(image['download_url'])
    assert image_response.status_code==200 and image_response.headers['content-type']=='image/png'
    assert client.get(version1['blocks_url']).json()['items'][0]['kind']=='paragraph'
    second=client.post(url+'/document-versions',headers={'Idempotency-Key':'second'},json={'expected_latest_version':1})
    assert second.status_code==202,second.text
    replay=client.post(url+'/document-versions',headers={'Idempotency-Key':'second'},json={'expected_latest_version':1})
    assert replay.status_code==200 and replay.json()==second.json()
    assert client.post(url+'/document-versions',headers={'Idempotency-Key':'second'},json={'expected_latest_version':2}).status_code==409
    def timeout(*args): raise StorageError('parse_timeout','timeout',422)
    failed=run_parse_file_task(second.json()['task_id'],1,parser=timeout)
    assert failed['status']=='failed'
    assert client.get(url+'/document-versions/'+second.json()['id']).json()['completed_at'] is not None
    assert client.get(version1['download_url']).content==raw.content
    details=client.get(url+'/details').json()
    assert details['source']['kind']=='docx_parse' and details['source']['preview_available'] is True
    assert details['parse_status']=='failed'
    historical=client.get(base+'/'+batch['id']).json()['items'][0]
    assert historical['task']['id']==first['id'] and historical['status']=='parsed'
    assert client.get(url+'/download').content==content
    third=client.post(url+'/document-versions',headers={'Idempotency-Key':'third'},json={'expected_latest_version':2})
    assert third.status_code==202,third.text
    old_workspace=client.get('/api/v1/tasks/'+failed['id']+'/workspace')
    assert old_workspace.json()['allowed_actions']==[]
    assert client.post('/api/v1/tasks/'+failed['id']+'/retry',json={'expected_revision':failed['revision']}).status_code==409
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM file_parse_results').fetchone()['n']==3


def test_docx_analysis_is_explicitly_rejected(client):
    project,_,_,item,_=uploaded_docx(client)
    url=f"/api/v1/projects/{project['id']}/files/{item['file_id']}/analysis-profile?sheet=Sheet1"
    response=client.get(url)
    assert response.status_code==422
    assert response.json()['detail']['code']=='unsupported_file_type'

def test_docx_history_permissions_and_immutable_manifest_audit(client):
    from app.adapters.docx_parser import parse_docx
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    from app.db.database import database_connection
    from app.maintenance.database_audit import audit_database
    from tests.integration.test_project_ownership import account_client
    project,_,_,item,_=uploaded_docx(client)
    assert run_parse_file_task(item['task']['id'],1,parser=parse_docx)['status']=='succeeded'
    url=f"/api/v1/projects/{project['id']}/files/{item['file_id']}/document-versions"
    version=client.get(url).json()['items'][0]
    with account_client('word-other@example.test')[0] as other:
        assert other.get(url).status_code==404
        assert other.get(version['download_url']).status_code==404
    with database_connection() as db:
        audit=audit_database(db)
        assert audit['ok'],audit
        assert any(c['column']=='document_manifest' for c in audit['data_checks'])
    with database_connection(write=True) as db:
        db.execute("UPDATE file_parse_results SET result_json=jsonb_set(result_json,'{object,object_key}',to_jsonb(%s::text))",('documents/'+str(uuid4())+'/'+'a'*64+'.json',))
    with database_connection() as db:
        assert not audit_database(db)['ok']
    assert client.get(version['download_url']).status_code==409

def test_word_frozen_input_rejects_omitted_limit(client):
    from app.db.database import database_connection
    project,_,_,item,_=uploaded_docx(client)
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET input_snapshot=input_snapshot #- '{settings,docx,max_depth}' WHERE id=%s",(item['task']['id'],))
    url=f"/api/v1/projects/{project['id']}/files/{item['file_id']}/document-versions"
    assert client.get(url).status_code==409

def test_word_lease_recovery_and_version_pagination(client):
    import pytest
    from app.adapters.task_execution_store import TaskExecutionStore, LeaseLost
    from app.adapters.document_parse_store import DocumentParseStore
    from app.adapters.docx_parser import parse_docx
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    from app.core.exceptions import StorageError
    from app.db.database import database_connection
    project,_,_,item,content=uploaded_docx(client)
    repo=TaskExecutionStore();lease=repo.claim(item['task']['id'],1,task_type='parse_file')
    store=DocumentParseStore(repo);snapshot,_=store.load(lease)
    with database_connection(write=True) as db:
        db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second'")
    with pytest.raises(LeaseLost):
        store.complete(lease,snapshot,parse_docx(content,'paper.docx',snapshot['settings']))
    assert repo.recover_expired()==1
    with database_connection() as db:
        recovered=db.execute('SELECT revision FROM tasks WHERE id=%s',(item['task']['id'],)).fetchone()['revision']
    url=f"/api/v1/projects/{project['id']}/files/{item['file_id']}/document-versions"
    queued_version=client.get(url).json()['items'][0]
    assert queued_version['status']=='queued' and queued_version['completed_at'] is None
    recovered_lease=repo.claim(item['task']['id'],recovered,task_type='parse_file')
    running_version=client.get(url).json()['items'][0]
    assert running_version['status']=='running' and running_version['completed_at'] is None
    recovered_snapshot,_=store.load(recovered_lease)
    assert store.complete(recovered_lease,recovered_snapshot,parse_docx(content,'paper.docx',recovered_snapshot['settings']))['status']=='succeeded'
    url=f"/api/v1/projects/{project['id']}/files/{item['file_id']}/document-versions"
    first=client.get(url).json()['items'][0]
    for n in range(1,6):
        version=client.post(url,headers={'Idempotency-Key':str(n)},json={'expected_latest_version':n})
        assert version.status_code==202,version.text
        def failed(*args): raise StorageError('invalid_document','invalid',422)
        result=run_parse_file_task(version.json()['task_id'],1,parser=failed)
        assert result['error_code']=='invalid_document'
    assert [v['version'] for v in client.get(url).json()['items']]==[6,5,4,3,2]
    assert [v['version'] for v in client.get(url+'?page=2').json()['items']]==[1]
    assert client.get(first['download_url']).status_code==200
    assert client.get(url+'?page=1.0').status_code==422
    assert client.get(url+'/'+first['id']+'/images/missing').status_code==404

def test_concurrent_reparse_allocates_one_version_and_latest_guard(client):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.adapters.docx_parser import parse_docx
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    from app.domain.file_parsing import sync_file_status
    from app.db.database import database_connection
    project,_,_,item,_=uploaded_docx(client)
    run_parse_file_task(item['task']['id'],1,parser=parse_docx)
    url=f"/api/v1/projects/{project['id']}/files/{item['file_id']}/document-versions"
    barrier=Barrier(2)
    def submit(key):
        barrier.wait()
        return client.post(url,headers={'Idempotency-Key':key},json={'expected_latest_version':1})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(submit,['a','b']))
    assert sorted(r.status_code for r in results)==[202,409]
    assert client.get(url).json()['total']==2
    with database_connection(write=True) as db:
        old=dict(db.execute('SELECT * FROM tasks WHERE id=%s',(item['task']['id'],)).fetchone())
        sync_file_status(db,old,'failed','parse_timeout')
    with database_connection() as db:
        assert db.execute('SELECT parse_status,error_json FROM files').fetchone()=={'parse_status':'queued','error_json':None}

def test_word_publication_updates_project_utc_monotonically(client):
    from datetime import datetime,timedelta,timezone
    from app.adapters.docx_parser import parse_docx
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    from app.db.database import database_connection
    project,_,_,item,_=uploaded_docx(client)
    prior=datetime.now(timezone.utc)-timedelta(hours=1)
    with database_connection(write=True) as db:
        db.execute('UPDATE projects SET updated_at=%s WHERE id=%s',(prior.isoformat(),project['id']))
    run_parse_file_task(item['task']['id'],1,parser=parse_docx)
    with database_connection() as db:
        completed=db.execute('SELECT completed_at FROM file_parse_results').fetchone()['completed_at']
        actual=db.execute('SELECT updated_at FROM projects WHERE id=%s',(project['id'],)).fetchone()['updated_at']
    assert actual==completed.astimezone(timezone.utc).isoformat()

def test_same_batch_excel_word_and_damaged_word_fail_independently(client):
    from tests.api.test_excel import workbook_bytes
    from tests.helpers.document_samples import document_bytes
    from tests.domain.test_file_parse_execution import deterministic
    from app.adapters.docx_parser import parse_docx
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    project=create_project(client)
    contents=[('data.xlsx',workbook_bytes()),('paper.docx',document_bytes()),('bad.docx',b'damaged')]
    items=[dict(client_id=str(uuid4()),filename=name,size_bytes=len(content)) for name,content in contents]
    base=f"/api/v1/projects/{project['id']}/file-batches"
    registered=client.post(base,headers={'Idempotency-Key':'mixed'},json={'items':items})
    assert registered.status_code==201
    batch=registered.json()
    assert all(item['status']=='pending' for item in batch['items'])
    for registered_item,(name,content) in zip(items,contents):
        saved=client.post(base+'/'+batch['id']+'/items/'+registered_item['client_id'],files={'file':(name,content)})
        assert saved.status_code==202,saved.text
        run_parse_file_task(saved.json()['task']['id'],1,parser=deterministic if name.endswith('xlsx') else parse_docx)
    read=client.get(base+'/'+batch['id']).json()
    assert [item['status'] for item in read['items']]==['parsed','parsed','failed']
    assert read['items'][2]['error']['code']=='invalid_document'


def test_pdf_registration_and_queued_version_contract(client):
    project = create_project(client)
    base,batch,item,content = register(client,project,b'%PDF-pending','paper.pdf')
    assert batch['items'][0]['status'] == 'pending'
    saved = client.post(base+'/'+batch['id']+'/items/'+item['client_id'],files={'file':(item['filename'],content)})
    assert saved.status_code == 202, saved.text
    url=f"/api/v1/projects/{project['id']}/files/{saved.json()['file_id']}"
    assert client.get(url+'/download').headers['content-type'] == 'application/pdf'
    version=client.get(url+'/document-versions').json()['items'][0]
    assert version['kind'] == 'pdf_document'
    assert version['pages_url'] is None
    assert 'blocks_url' not in version

def uploaded_pdf(client):
    from tests.helpers.pdf_samples import pdf_bytes, TEXT
    project=create_project(client)
    content=pdf_bytes([TEXT,b''])
    base,batch,item,content=register(client,project,content,'paper.pdf')
    saved=client.post(base+'/'+batch['id']+'/items/'+item['client_id'],files={'file':('paper.pdf',content)})
    assert saved.status_code==202,saved.text
    return project,saved.json(),content


def test_pdf_pages_history_permissions_and_failed_reparse(client):
    from app.adapters.pdf_parser import parse_pdf
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    from app.core.exceptions import StorageError
    from app.db.database import database_connection
    from app.maintenance.database_audit import audit_database
    from tests.integration.test_project_ownership import account_client
    project,item,content=uploaded_pdf(client)
    first=run_parse_file_task(item['task']['id'],1,parser=parse_pdf)
    assert first['status']=='succeeded',first
    url=f"/api/v1/projects/{project['id']}/files/{item['file_id']}/document-versions"
    version=client.get(url).json()['items'][0]
    raw=client.get(version['download_url']).content
    detail=client.get(url+'/'+version['id']).json()
    assert detail['kind']=='pdf_document' and 'styles' not in detail and 'images' not in detail
    page=client.get(version['pages_url']+'?page=2').json()
    assert page['items'][0]['page_number']==2 and page['total']==2 and page['page_size']==1
    assert page['items'][0]['text_status']=='no_extractable_text'
    assert client.get(version['pages_url']+'?page=3').json()['items']==[]
    for suffix in ('/blocks','/images/missing'):
        response=client.get(url+'/'+version['id']+suffix)
        assert response.status_code==422 and response.json()['detail']['code']=='unsupported_file_type'
    second=client.post(url,headers={'Idempotency-Key':'second'},json={'expected_latest_version':1})
    assert second.status_code==202,second.text
    assert client.post(url,headers={'Idempotency-Key':'second'},json={'expected_latest_version':1}).json()==second.json()
    assert client.post(url,headers={'Idempotency-Key':'second'},json={'expected_latest_version':2}).status_code==409
    def failed(*args):raise StorageError('invalid_document','bad',422)
    assert run_parse_file_task(second.json()['task_id'],1,parser=failed)['status']=='failed'
    assert client.get(version['download_url']).content==raw
    assert client.get(url+'/'+second.json()['id']).json()['completed_at'] is not None
    assert client.get(url.removesuffix('/document-versions')+'/download').content==content
    details=client.get(url.removesuffix('/document-versions')+'/details').json()
    assert details['source']['kind']=='pdf_parse' and details['source']['preview_available'] is True
    assert client.get(url.removesuffix('/document-versions')+'/analysis-profile?sheet=Sheet1').status_code==422
    with account_client('pdf-other@example.test')[0] as other:
        assert other.get(url).status_code==404
        assert other.get(version['pages_url']).status_code==404
    with database_connection() as db:
        assert audit_database(db)['ok']

def test_pdf_frozen_input_rejects_omitted_limit(client):
    from app.db.database import database_connection
    project,item,_=uploaded_pdf(client)
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET input_snapshot=input_snapshot #- '{settings,pdf,max_pages}' WHERE id=%s",(item['task']['id'],))
    url=f"/api/v1/projects/{project['id']}/files/{item['file_id']}/document-versions"
    assert client.get(url).status_code==409


def test_same_batch_excel_word_pdf_and_damaged_pdf_fail_independently(client):
    from tests.api.test_excel import workbook_bytes
    from tests.helpers.document_samples import document_bytes
    from tests.helpers.pdf_samples import pdf_bytes,TEXT
    from tests.domain.test_file_parse_execution import deterministic
    from app.adapters.docx_parser import parse_docx
    from app.adapters.pdf_parser import parse_pdf
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    project=create_project(client)
    contents=[('data.xlsx',workbook_bytes()),('paper.docx',document_bytes()),('paper.pdf',pdf_bytes([TEXT])),('bad.pdf',b'damaged')]
    items=[dict(client_id=str(uuid4()),filename=name,size_bytes=len(content)) for name,content in contents]
    base=f"/api/v1/projects/{project['id']}/file-batches"
    registered=client.post(base,headers={'Idempotency-Key':'mixed-pdf'},json={'items':items})
    assert registered.status_code==201,registered.text
    batch=registered.json()
    assert all(item['status']=='pending' for item in batch['items'])
    for item,(name,content) in zip(items,contents):
        saved=client.post(base+'/'+batch['id']+'/items/'+item['client_id'],files={'file':(name,content)})
        assert saved.status_code==202,saved.text
        parser=deterministic if name.endswith('xlsx') else parse_docx if name.endswith('docx') else parse_pdf
        run_parse_file_task(saved.json()['task']['id'],1,parser=parser)
    read=client.get(base+'/'+batch['id']).json()
    assert [item['status'] for item in read['items']]==['parsed','parsed','parsed','failed']
    assert read['items'][3]['error']['code']=='invalid_document'

def test_word_version_rejects_pdf_pages(client):
    from app.adapters.docx_parser import parse_docx
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    project,_,_,item,_=uploaded_docx(client)
    run_parse_file_task(item['task']['id'],1,parser=parse_docx)
    url=f"/api/v1/projects/{project['id']}/files/{item['file_id']}/document-versions"
    version=client.get(url).json()['items'][0]
    response=client.get(url+'/'+version['id']+'/pages')
    assert response.status_code==422 and response.json()['detail']['code']=='unsupported_file_type'
