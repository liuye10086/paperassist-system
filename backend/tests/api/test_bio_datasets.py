"""CR-B01 API behavior: stored originals and bounded authenticated imports."""
import io
import tarfile
from uuid import uuid4

from tests.api.test_projects import client, create_project


def tiny_archive():
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w') as archive:
        value = b'original data\n'
        entry = tarfile.TarInfo('GSM9999999_note.txt')
        entry.size = len(value)
        archive.addfile(entry, io.BytesIO(value))
    return output.getvalue()


def test_bio_upload_is_stored_without_a_fake_parse_task(client):
    project = create_project(client)
    content = tiny_archive()
    item = str(uuid4())
    path = f"/api/v1/projects/{project['id']}/bio-upload-batches"
    batch = client.post(path, json={'items': [dict(client_id=item, filename='GSE_TEST_RAW.tar',
        size_bytes=len(content))]}, headers={'Idempotency-Key': 'bio-upload-test-1'})
    assert batch.status_code == 201, batch.text
    assert batch.json()['profile'] == 'bioinformatics_v1'
    uploaded = client.post(f"{path}/{batch.json()['id']}/items/{item}",
        files={'file': ('GSE_TEST_RAW.tar', content)})
    assert uploaded.status_code == 202, uploaded.text
    assert uploaded.json()['status'] == 'stored'
    assert uploaded.json()['task'] is None
    file_id = uploaded.json()['file_id']
    downloaded = client.get(f"/api/v1/projects/{project['id']}/files/{file_id}/download")
    assert downloaded.status_code == 200
    assert downloaded.content == content
    reread = client.get(f"{path}/{batch.json()['id']}")
    assert reread.json()['items'][0]['file_id'] == file_id
    replay = client.post(f"{path}/{batch.json()['id']}/items/{item}",
        files={'file': ('GSE_TEST_RAW.tar', content)})
    assert replay.json()['file_id'] == file_id


def test_bio_batch_does_not_accept_documents_profile_upload(client):
    project = create_project(client)
    content = tiny_archive()
    item = str(uuid4())
    base = f"/api/v1/projects/{project['id']}"
    batch = client.post(f'{base}/bio-upload-batches', json={'items': [dict(
        client_id=item, filename='GSE_TEST_RAW.tar', size_bytes=len(content))]},
        headers={'Idempotency-Key': 'bio-profile-test'})
    assert batch.status_code == 201, batch.text
    wrong = client.post(f"{base}/file-batches/{batch.json()['id']}/items/{item}",
        files={'file': ('GSE_TEST_RAW.tar', content)})
    assert wrong.status_code in (404, 409, 422)


def test_new_project_bio_dataset_list_starts_empty(client):
    project = create_project(client)
    response = client.get(f"/api/v1/projects/{project['id']}/bio-datasets")
    assert response.status_code == 200, response.text
    assert response.json() == {'items': [], 'total': 0, 'page': 1, 'page_size': 5}
    assert client.get(f"/api/v1/projects/{project['id']}/bio-datasets?page=1&page_size=5").status_code==200


def register_import(client):
    from tests.helpers.bio_fixtures import visium_bundle_bytes
    project=create_project(client)
    content=visium_bundle_bytes()
    item=str(uuid4())
    base=f"/api/v1/projects/{project['id']}"
    batch=client.post(base+'/bio-upload-batches',json={'items':[dict(client_id=item,filename='fixture.tar',size_bytes=len(content))]},headers={'Idempotency-Key':str(uuid4())})
    assert batch.status_code==201,batch.text
    file=client.post(f"{base}/bio-upload-batches/{batch.json()['id']}/items/{item}",files={'file':('fixture.tar',content)})
    assert file.status_code==202,file.text
    body=dict(file_ids=[file.json()['file_id']],assay='visium',name='synthetic Visium',dataset_id=None,expected_dataset_revision=0)
    response=client.post(base+'/bio-imports',json=body,headers={'Idempotency-Key':'bio-import-create'})
    assert response.status_code==202,response.text
    return project,body,response.json()


def test_import_is_frozen_idempotent_and_visible_in_task_center(client):
    project,body,result=register_import(client)
    base=f"/api/v1/projects/{project['id']}"
    assert result['task']['task_type']=='bio_import'
    assert result['task']['input_version']['source_file_ids']==body['file_ids']
    replay=client.post(base+'/bio-imports',json=body,headers={'Idempotency-Key':'bio-import-create'})
    assert replay.json()['id']==result['id']
    changed=client.post(base+'/bio-imports',json={**body,'name':'changed'},headers={'Idempotency-Key':'bio-import-create'})
    assert changed.status_code==409
    detail=client.get(base+'/bio-imports/'+result['id'])
    assert detail.status_code==200,detail.text
    assert detail.json()['candidate'] is None
    workspace=client.get('/api/v1/tasks/'+result['task']['id']+'/workspace')
    assert workspace.status_code==200,workspace.text
    assert workspace.json()['source']['file_id']==body['file_ids'][0]
    invalid=client.post(base+'/bio-imports/'+result['id']+'/confirm',json=dict(task_revision=1,
        checkpoint_id=detail.json()['checkpoint_id'],wait_id=str(uuid4()),candidate_sha256='0'*64,
        expected_dataset_revision=1),headers={'Idempotency-Key':'too-early'})
    assert invalid.status_code==409
    from app.workers.dispatcher import dispatch_once
    messages=[]
    assert dispatch_once(publish=messages.append)==1
    assert messages[0]['task_id']==result['task']['id']


def test_research_delivery_registration_keeps_legacy_writing_gated(client):
    response=client.post('/api/v1/projects',json=dict(name='pure research',research_topic='biology',project_type='research',
        default_output_language='zh-CN',delivery_kinds=['analysis']),headers={'Idempotency-Key':'pure-research-create'})
    assert response.status_code==201,response.text
    base='/api/v1/projects/'+response.json()['id']
    for suffix in ('/manuscripts','/school-templates','/journals/profiles','/reviews/rounds'):
        blocked=client.get(base+suffix)
        assert blocked.status_code==409,(suffix,blocked.text)
        assert blocked.json()['detail']['code']=='research_writing_unavailable'
    assert client.get(base+'/layout-exports/config').status_code==200
    for kind in ('report','collection_report','layout_export'):
        allowed=client.post(base+'/pdf-exports',json=dict(source_kind=kind,source_id='missing',request_key='research-'+kind))
        assert allowed.status_code==404,(kind,allowed.text)
    blocked=client.post(base+'/pdf-exports',json=dict(source_kind='manuscript_export',source_id='missing',request_key='research-manuscript'))
    assert blocked.status_code==409,blocked.text


def test_new_json_routes_bound_chunked_body_before_decoding(client):
    project=create_project(client)
    base='/api/v1/projects/'+project['id']
    bio=client.post(base+'/bio-imports',content=iter([b'x'*40000,b'x'*40000]),headers={
        'Content-Type':'application/json','Idempotency-Key':'oversize-bio'})
    assert bio.status_code==413,bio.text
    assert bio.json()['detail']['code']=='bio_input_limit'
    intake=client.post(base+'/requirements',content=iter([b'x'*(3*1024*1024),b'x'*(2*1024*1024)]),headers={
        'Content-Type':'application/json','Idempotency-Key':'oversize-requirement'})
    assert intake.status_code==413,intake.text
