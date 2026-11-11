"""CR-B01 API behavior: stored originals and bounded authenticated imports."""
import io
import tarfile
from tempfile import SpooledTemporaryFile
from uuid import uuid4

import anyio
import httpx
import pytest

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


def register_csv(client, size):
    project = create_project(client)
    item = str(uuid4())
    base = f"/api/v1/projects/{project['id']}"
    response = client.post(base + '/bio-upload-batches', json={'items': [dict(
        client_id=item, filename='counts.csv', size_bytes=size)]},
        headers={'Idempotency-Key': 'bio-stream-register'})
    assert response.status_code == 201, response.text
    batch = base + '/bio-upload-batches/' + response.json()['id']
    return base, batch, batch + '/items/' + item


def post_csv_chunks(client, url, chunks, *, disconnect=False):
    async def post():
        async def body():
            for chunk in chunks:
                yield chunk

        async def app(scope, receive, send):
            async def receive_upload():
                message = await receive()
                if disconnect and message['type'] == 'http.request' and not message.get('more_body'):
                    return {'type': 'http.disconnect'}
                return message
            await client.app(scope, receive_upload, send)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='http://testserver',
            headers=dict(client.headers), cookies={'paperassist_session': client.cookies.get('paperassist_session')},
        ) as streaming:
            return await streaming.post(url, content=body(),
                                        headers={'Content-Type': 'multipart/form-data; boundary=testing'})
    return anyio.run(post)


CSV_FILE_HEADER = b'--testing\r\nContent-Disposition: form-data; name="file"; filename="counts.csv"\r\n\r\n'
CSV_FORM_END = b'\r\n--testing--\r\n'


def test_bio_upload_uses_bounded_spool_and_replays_without_loading_original(client, monkeypatch):
    from starlette import formparsers
    from app.adapters.object_storage import LocalObjectStorage

    files, reads, writes = [], [], []

    class ObservedSpool(SpooledTemporaryFile):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            files.append(self)

        def write(self, data):
            writes.append(len(data))
            return super().write(data)

        def read(self, size=-1):
            assert 0 < size <= 65536
            reads.append(size)
            return super().read(size)

    def no_byte_read(*args):
        raise AssertionError('upload and integrity replay must stream the stored original')

    monkeypatch.setattr(formparsers, 'SpooledTemporaryFile', ObservedSpool)
    monkeypatch.setattr(LocalObjectStorage, 'read', no_byte_read)
    content = b'x' * (1024 * 1024 + 17)
    _, _, url = register_csv(client, len(content))
    for expected_byte, status in [(b'x', 202), (b'x', 202), (b'y', 409)]:
        chunks = [CSV_FILE_HEADER, expected_byte * len(content), CSV_FORM_END]
        response = post_csv_chunks(client, url, chunks)
        assert response.status_code == status, response.text
        if expected_byte == b'x':
            assert response.json()['status'] == 'stored'
        else:
            assert response.json()['detail']['code'] == 'file_batch_item_conflict'
    assert reads and writes and max(writes) <= 65536
    assert len(files) == 3 and all(file._rolled and file.closed for file in files)


def test_bio_upload_rejects_truncated_form_after_file_without_publishing(client):
    from app.core.config import get_data_dir

    _, batch, url = register_csv(client, 4)
    incomplete = b'\r\n--testing\r\nContent-Disposition: form-data; name="extra"\r\n\r\nunfinished'
    response = post_csv_chunks(client, url, [CSV_FILE_HEADER, b'x,y\n', incomplete])
    assert response.status_code == 400, response.text
    assert client.get(batch).json()['items'][0]['status'] == 'pending'
    assert not list((get_data_dir() / 'files').glob('upload-*'))


def test_bio_upload_closes_spool_after_receive_disconnect(client, monkeypatch):
    from starlette import formparsers
    from app.core.config import get_data_dir

    spools = []

    def observe_spool(*args, **kwargs):
        spool = SpooledTemporaryFile(*args, **kwargs)
        spools.append(spool)
        return spool

    monkeypatch.setattr(formparsers, 'SpooledTemporaryFile', observe_spool)
    size = 1024 * 1024 + 100
    _, batch, url = register_csv(client, size)
    post_csv_chunks(client, url, [CSV_FILE_HEADER, b'x' * size], disconnect=True)
    assert len(spools) == 1 and spools[0]._rolled and spools[0].closed
    assert client.get(batch).json()['items'][0]['status'] == 'pending'
    assert not list((get_data_dir() / 'files').glob('upload-*'))


def test_bio_stream_upload_reuses_governed_original_after_database_rollback(client, reject_database_write):
    from hashlib import sha256
    from uuid import UUID, uuid5

    from app.core.config import get_data_dir
    from app.db.database import database_connection

    content = b'x,y\n'
    base, batch, url = register_csv(client, len(content))
    item_id = url.rsplit('/', 1)[-1]
    project_id = base.rsplit('/', 1)[-1]
    batch_id = batch.rsplit('/', 1)[-1]
    digest = sha256(content).hexdigest()
    key = f'files/upload-{project_id}-{batch_id}-{item_id}-{digest}.bio_component'
    expected_id = str(uuid5(UUID(batch_id), f'{project_id}:{item_id}:bio_component:{digest}'))

    with reject_database_write('files'):
        response = post_csv_chunks(client, url, [CSV_FILE_HEADER, content, CSV_FORM_END])
    assert response.status_code == 503, response.text
    assert client.get(batch).json()['items'][0]['status'] == 'pending'
    target = get_data_dir() / key
    assert target.read_bytes() == content
    assert not list(target.parent.glob('*.part'))

    response = post_csv_chunks(client, url, [CSV_FILE_HEADER, content, CSV_FORM_END])
    assert response.status_code == 202, response.text
    assert response.json()['file_id'] == expected_id
    assert list(target.parent.glob('upload-*')) == [target]
    with database_connection() as db:
        reservation = db.execute('SELECT size_bytes,sha256,state FROM storage_reservations WHERE object_key=%s',
                                 (key,)).fetchone()
        assert reservation == {'size_bytes': len(content), 'sha256': digest, 'state': 'settled'}


@pytest.mark.parametrize('overage', [1, 65537])
def test_bio_upload_rejects_oversized_file_and_chunked_body(client, monkeypatch, overage):
    from types import SimpleNamespace
    from app.api import bio_datasets
    from app.domain.bioinformatics import settings

    maximum = 128 * 1024
    def limits():
        return SimpleNamespace(max_upload_bytes=maximum)

    monkeypatch.setattr(settings, 'BioLimits', limits)
    monkeypatch.setattr(bio_datasets, 'BioLimits', limits)
    _, batch, url = register_csv(client, maximum)
    response = post_csv_chunks(client, url, [
        CSV_FILE_HEADER, b'x' * maximum, b'x' * overage, CSV_FORM_END,
    ])
    assert response.status_code == 413, response.text
    assert response.json()['detail']['code'] == 'file_too_large'
    assert response.json()['detail']['params'] == {'max_bytes': maximum}
    assert client.get(batch).json()['items'][0]['status'] == 'pending'
    assert post_csv_chunks(client, url, [CSV_FILE_HEADER, b'x' * maximum, CSV_FORM_END]).status_code == 202


def test_bio_import_creation_verifies_bytes_without_loading_original(client, monkeypatch):
    from app.adapters.object_storage import LocalObjectStorage

    def no_byte_read(*args):
        raise AssertionError('import validation must stream the stored original')

    monkeypatch.setattr(LocalObjectStorage, 'read', no_byte_read)
    _, _, result = register_import(client)
    assert result['task']['status'] == 'queued'


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
    listed=client.get(base+'/manuscripts')
    assert listed.status_code==200 and listed.json()=={'items':[]}
    blocked=client.post(base+'/manuscripts',json={'title':'legacy draft','output_language':'zh-CN'},
                        headers={'Idempotency-Key':'pure-research-legacy-draft'})
    assert blocked.status_code==409,blocked.text
    assert blocked.json()['detail']['code']=='research_writing_unavailable'
    for suffix in ('/school-templates','/journals/profiles','/reviews/rounds'):
        blocked=client.get(base+suffix)
        assert blocked.status_code==409,(suffix,blocked.text)
        assert blocked.json()['detail']['code']=='research_writing_unavailable'
    assert client.get(base+'/layout-exports/config').status_code==200
    for kind in ('report','collection_report','layout_export'):
        allowed=client.post(base+'/pdf-exports',json=dict(source_kind=kind,source_id='missing',request_key='research-'+kind))
        assert allowed.status_code==405,(kind,allowed.text)
    blocked=client.post(base+'/pdf-exports',json=dict(source_kind='manuscript_export',source_id='missing',request_key='research-manuscript'))
    assert blocked.status_code==405,blocked.text


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
