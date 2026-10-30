"""Equivalent member names retain distinct original-file provenance."""
from uuid import uuid4

from app.db.database import database_connection
from tests.api.test_projects import client, create_project
from tests.helpers.bio_fixtures import visium_bundle_bytes
from tests.integration.test_bio_import_publication import run, read, confirm


def test_equivalent_soft_files_with_same_name_publish_as_distinct_sources(client):
    project=create_project(client)
    base=f"/api/v1/projects/{project['id']}"
    metadata=b'^SERIES = GSE9999999\n^SAMPLE = GSM9999999\n!Sample_title = synthetic\n'
    sources=[('RAW.tar',visium_bundle_bytes()),('family.soft',metadata),('family.soft',metadata)]
    items=[str(uuid4()) for _ in sources]
    batch=client.post(base+'/bio-upload-batches',headers={'Idempotency-Key':'same-names-batch'},json={
        'items':[{'client_id':item,'filename':name,'size_bytes':len(content)}
                 for item,(name,content) in zip(items,sources)]})
    assert batch.status_code==201,batch.text
    files=[]
    for item,(name,content) in zip(items,sources):
        response=client.post(base+f"/bio-upload-batches/{batch.json()['id']}/items/{item}",files={'file':(name,content)})
        assert response.status_code==202,response.text
        files.append(response.json()['file_id'])
    assert len(set(files))==3
    created=client.post(base+'/bio-imports',headers={'Idempotency-Key':'same-names-import'},json={
        'file_ids':files,'assay':'visium','name':'equivalent SOFT sources','expected_dataset_revision':0})
    assert created.status_code==202,created.text
    created=created.json()
    waiting=run(created['task'])
    assert waiting['status']=='waiting_confirmation',waiting
    view=read(client,base,created)
    soft=[m for m in view['candidate']['members'] if m['role']=='geo_metadata' and m['source_member_name']=='family.soft']
    assert len(soft)==2
    assert {m['source_file_id'] for m in soft}==set(files[1:])
    assert len({m['sha256'] for m in soft})==1
    queued=confirm(client,base,created,view,key='same-names-confirm')
    assert queued.status_code==202,queued.text
    done=run(queued.json())
    assert done['status']=='succeeded',done
    with database_connection() as db:
        persisted=db.execute('''SELECT source_file_id,source_member_name,sha256 FROM bio_dataset_members
            WHERE dataset_version_id=%s AND role='geo_metadata' AND source_member_name='family.soft' ''',
            (done['result_bio_dataset_version_id'],)).fetchall()
    assert len(persisted)==2
    assert {m['source_file_id'] for m in persisted}==set(files[1:])
