import copy
import pytest
from psycopg.types.json import Jsonb
from app.db.database import database_connection
from tests.api.test_analysis import client,add_file
from tests.domain.test_batch09_evidence_contracts import request


def saved(client):
    base,file=add_file(client);project=base.split('/')[4]
    body=request();body['file_id']=file['id']
    response=client.post(f'/api/v1/projects/{project}/external-evidence',json=body,headers={'Idempotency-Key':'evidence'})
    assert response.status_code==201,response.text
    return base,project,file,body,response.json()


def test_external_original_is_versioned_without_any_computation(client):
    base,project,file,body,first=saved(client);url=f'/api/v1/projects/{project}/external-evidence'
    original=client.get(base+'/download').content
    assert first['verification_status']=='external_not_recomputed'
    assert first['computed_by_system'] is False and first['included_in_reports'] is False
    assert first['source']['original_download_url']==base+'/download'
    replay=client.post(url,json=body,headers={'Idempotency-Key':'evidence'})
    assert replay.status_code==200 and replay.json()==first
    revised={**body,'previous_version_id':first['id'],'user_note':'User supplied P=0.04; not independently verified'}
    second=client.post(url,json=revised,headers={'Idempotency-Key':'revision'})
    assert second.status_code==201,second.text
    assert second.json()['version']==2 and second.json()['evidence_id']==first['id']
    assert client.get(url+'/'+first['id']).json()==first
    assert client.get(url).json()['total']==2
    assert client.get(base+'/download').content==original
    with database_connection() as db:
        for table in ('analysis_runs','figures','explanations','reports','model_calls'):
            assert db.execute('SELECT count(*) AS n FROM '+table).fetchone()['n']==0


def test_material_revision_and_project_scope_cannot_be_replayed_elsewhere(client):
    base,project,file,body,first=saved(client);url=f'/api/v1/projects/{project}/external-evidence'
    second_base,other_file=add_file(client);other=second_base.split('/')[4]
    assert client.get(f'/api/v1/projects/{other}/external-evidence/'+first['id']).status_code==404
    assert client.post(f'/api/v1/projects/{other}/external-evidence',json=body,headers={'Idempotency-Key':'bad-scope'}).status_code==404
    changed={**body,'title':'changed'}
    assert client.post(url,json=changed,headers={'Idempotency-Key':'evidence'}).status_code==409
    revision={**body,'previous_version_id':first['id'],'title':'v2'}
    assert client.post(url,json=revision,headers={'Idempotency-Key':'v2'}).status_code==201
    assert client.post(url,json={**revision,'title':'stale'},headers={'Idempotency-Key':'stale'}).status_code==409


def test_unbound_fragments_and_forged_source_are_rejected(client):
    base,project,file,body,first=saved(client)
    assert client.post(f'/api/v1/projects/{project}/external-evidence',json={**body,'item_ids':['pretend']},headers={'Idempotency-Key':'unbound'}).status_code==422
    with database_connection(write=True) as db:
        snapshot=copy.deepcopy(first);snapshot.pop('sha256');snapshot['computed_by_system']=True
        db.execute('UPDATE external_evidence_versions SET snapshot_json=%s WHERE id=%s',(Jsonb(snapshot),first['id']))
    assert client.get(f'/api/v1/projects/{project}/external-evidence/'+first['id']).status_code==409


def test_new_schema_tables_and_metadata_are_additive(postgres_schema):
    from app.db.schema import metadata
    with database_connection() as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()['version_num']=='0029_statistics_execution'
        for table in ('prepared_dataset_derivations','prepared_dataset_derivations_v3','external_evidence_versions'):
            assert table in metadata.tables
            assert db.execute('SELECT count(*) AS n FROM '+table).fetchone()['n']==0
