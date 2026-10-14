"""OCR upload and immutable version integration against disposable schemas."""
import pytest

from tests.api.test_projects import client, create_project  # noqa: F401
from tests.api.test_file_batches import register
from tests.api.test_document_versions import uploaded_pdf


@pytest.mark.parametrize('filename,kind,mime', [('scan.png','png','image/png'),('scan.JPG','jpeg','image/jpeg'),('scan.jpeg','jpeg','image/jpeg')])
def test_image_upload_normalizes_type_and_queues_ocr(client, filename, kind, mime):
    from app.db.database import database_connection
    project=create_project(client)
    base,batch,item,content=register(client,project,b'pending image bytes',filename)
    assert batch['items'][0]['status']=='pending'
    response=client.post(base+'/'+batch['id']+'/items/'+item['client_id'],files={'file':(filename,content)})
    assert response.status_code==202,response.text
    saved=response.json();url=f"/api/v1/projects/{project['id']}/files/{saved['file_id']}"
    assert client.get(url+'/download').headers['content-type']==mime
    assert client.get(url+'/download').content==content
    details=client.get(url+'/details').json()
    assert details['file_type']==kind and details['filename']==filename
    assert details['source']['kind']=='ocr_parse'
    assert client.put(url+'/purposes',json={'expected_revision':1,'purposes':['figure','paper']}).status_code==200
    assert client.get(url+'/analysis-profile?sheet=Sheet1').status_code==422
    assert client.get(url+'/document-versions').json()['items'][0]['kind']=='ocr_document'
    with database_connection() as db:
        task=db.execute('SELECT * FROM tasks WHERE id=%s',(saved['task']['id'],)).fetchone()
        assert task['workflow_version']=='ocr_document_v1'
        assert task['input_snapshot']['page_numbers']==[1]


@pytest.mark.parametrize('pages', [[],[0],[True],[1,1],list(range(1,12)),[101],['1']])
def test_ocr_page_selection_is_strict(client,pages):
    project,item,_=uploaded_pdf(client)
    url=f"/api/v1/projects/{project['id']}/files/{item['file_id']}/document-versions/ocr"
    response=client.post(url,headers={'Idempotency-Key':'selection'},json={'expected_latest_version':1,'page_numbers':pages})
    assert response.status_code==422,response.text


def test_pdf_ocr_uses_original_and_freezes_selected_pages(client):
    from app.adapters.pdf_parser import parse_pdf
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    from app.db.database import database_connection
    project,item,content=uploaded_pdf(client)
    assert run_parse_file_task(item['task']['id'],1,parser=parse_pdf)['status']=='succeeded'
    url=f"/api/v1/projects/{project['id']}/files/{item['file_id']}/document-versions"
    previous=client.get(url).json()['items'][0]
    raw=client.get(previous['download_url']).content
    body={'expected_latest_version':1,'page_numbers':[2]}
    response=client.post(url+'/ocr',headers={'Idempotency-Key':'ocr'},json=body)
    assert response.status_code==202,response.text
    version=response.json()
    assert version['kind']=='ocr_document' and version['version']==2
    assert client.post(url+'/ocr',headers={'Idempotency-Key':'ocr'},json=body).json()==version
    assert client.post(url+'/ocr',headers={'Idempotency-Key':'ocr'},json={**body,'page_numbers':[1]}).status_code==409
    with database_connection() as db:
        task=db.execute('SELECT * FROM tasks WHERE id=%s',(version['task_id'],)).fetchone()
        assert task['input_snapshot']['page_numbers']==[2]
        assert task['input_snapshot']['file']['sha256']==item['task']['input_version']['source_sha256']
    assert client.get(previous['download_url']).content==raw
    assert client.get(url.removesuffix('/document-versions')+'/download').content==content


def uploaded_image(client):
    project=create_project(client)
    base,batch,item,content=register(client,project,b'pending image bytes','scan.png')
    response=client.post(base+'/'+batch['id']+'/items/'+item['client_id'],files={'file':('scan.png',content)})
    assert response.status_code==202,response.text
    return project,base,batch,response.json(),content


def test_ocr_result_read_original_permissions_failed_reparse_and_batch(client):
    from tests.helpers.ocr_samples import ocr_result
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    from app.core.exceptions import StorageError
    from app.db.database import database_connection
    from app.maintenance.database_audit import audit_database
    from tests.integration.test_project_ownership import account_client
    project,base,batch,item,content=uploaded_image(client)
    first=run_parse_file_task(item['task']['id'],1,parser=ocr_result)
    assert first['status']=='succeeded',first
    file_url=f"/api/v1/projects/{project['id']}/files/{item['file_id']}";url=file_url+'/document-versions'
    version=client.get(url).json()['items'][0]
    raw=client.get(version['download_url']).content
    detail=client.get(url+'/'+version['id']).json()
    assert detail['source_type']=='png' and detail['selected_pages']==[1] and detail['source_pages']==1
    page=client.get(version['pages_url']).json()
    assert page['items'][0]['text_blocks'][0]['review_status']=='unreviewed'
    image=client.get(detail['images'][0]['download_url'])
    assert image.status_code==200 and image.headers['content-type']=='image/jpeg'
    assert client.get(url+'/'+version['id']+'/blocks').status_code==422
    with account_client('ocr-other@example.test')[0] as other:
        assert other.get(detail['images'][0]['download_url']).status_code==404
    second=client.post(url,headers={'Idempotency-Key':'again'},json={'expected_latest_version':1})
    assert second.status_code==202,second.text
    assert second.json()['kind']=='ocr_document'
    def timeout(*args,**kwargs):raise StorageError('parse_timeout','timeout',422)
    failed=run_parse_file_task(second.json()['task_id'],1,parser=timeout)
    assert failed['status']=='failed' and failed['error_code']=='parse_timeout'
    assert client.get(url+'/'+second.json()['id']).json()['completed_at'] is not None
    assert client.get(version['download_url']).content==raw
    assert client.get(file_url+'/details').json()['source']['preview_available'] is True
    assert client.get(file_url+'/download').content==content
    assert client.get(base+'/'+batch['id']).json()['items'][0]['status']=='parsed'
    with database_connection() as db:assert audit_database(db)['ok']


def test_pdf_selected_ocr_pages_remain_physical_and_text_reparse_stays_text(client):
    from app.adapters.pdf_parser import parse_pdf
    from tests.helpers.ocr_samples import ocr_result
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    project,item,_=uploaded_pdf(client)
    run_parse_file_task(item['task']['id'],1,parser=parse_pdf)
    url=f"/api/v1/projects/{project['id']}/files/{item['file_id']}/document-versions"
    second=client.post(url+'/ocr',headers={'Idempotency-Key':'page-two'},json={'expected_latest_version':1,'page_numbers':[2]})
    assert run_parse_file_task(second.json()['task_id'],1,parser=ocr_result)['status']=='succeeded'
    version=client.get(url).json()['items'][0]
    page=client.get(version['pages_url']+'?page=1').json()
    assert page['total']==1 and page['items'][0]['page_number']==2
    assert client.get(version['pages_url']+'?page=2').json()['items']==[]
    third=client.post(url,headers={'Idempotency-Key':'text'},json={'expected_latest_version':2})
    assert third.status_code==202 and third.json()['kind']=='pdf_document'


@pytest.mark.parametrize('mutation',['filename','selected_pages','counts','page_source','preview','source_type'])
def test_ocr_rejects_wrong_output_source(client,mutation):
    from tests.helpers.ocr_samples import ocr_result
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    project,_,_,item,_=uploaded_image(client)
    def wrong(*args,**kwargs):
        result=ocr_result(*args,**kwargs).model_dump();doc=result['document']
        if mutation=='filename':doc['filename']='other.png'
        elif mutation=='selected_pages':doc['selected_pages']=[2]
        elif mutation=='counts':doc['counts']['text_blocks']=10
        elif mutation=='page_source':doc['pages'][0]['text_blocks'][0]['source']['page_number']=2
        elif mutation=='preview':doc['pages'][0]['preview_image_id']='missing'
        elif mutation=='source_type':doc['source_type']='pdf'
        return result
    result=run_parse_file_task(item['task']['id'],1,parser=wrong)
    assert result['error_code']=='parse_output_invalid',result


def test_ocr_read_checks_original_bytes_and_exact_settings(client):
    from tests.helpers.ocr_samples import ocr_result
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    from app.db.database import database_connection
    from app.core.config import get_data_dir
    project,_,_,item,_=uploaded_image(client)
    assert run_parse_file_task(item['task']['id'],1,parser=ocr_result)['status']=='succeeded'
    url=f"/api/v1/projects/{project['id']}/files/{item['file_id']}/document-versions"
    version=client.get(url).json()['items'][0]
    with database_connection() as db:
        key=db.execute('SELECT object_key FROM files WHERE id=%s',(item['file_id'],)).fetchone()['object_key']
    target=get_data_dir()/key;original=target.read_bytes();target.write_bytes(b'changed')
    assert client.get(version['download_url']).status_code==409
    target.write_bytes(original)
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET input_snapshot=input_snapshot #- '{settings,ocr,max_pages}' WHERE id=%s",(item['task']['id'],))
    assert client.get(version['download_url']).status_code==409


def test_image_ocr_requires_single_page_and_latest_version(client):
    from tests.helpers.ocr_samples import ocr_result
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    project,_,_,item,_=uploaded_image(client)
    run_parse_file_task(item['task']['id'],1,parser=ocr_result)
    url=f"/api/v1/projects/{project['id']}/files/{item['file_id']}/document-versions/ocr"
    assert client.post(url,headers={'Idempotency-Key':'bad-page'},json={'expected_latest_version':1,'page_numbers':[2]}).status_code==422
    response=client.post(url,headers={'Idempotency-Key':'new'},json={'expected_latest_version':1,'page_numbers':[1]})
    assert response.status_code==202,response.text
    assert client.post(url,headers={'Idempotency-Key':'stale'},json={'expected_latest_version':1,'page_numbers':[1]}).status_code==409
