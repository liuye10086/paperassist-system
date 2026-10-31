import hashlib
from tests.api.test_projects import client,create_project


def source_file(client,project,content=b'gene,effect,p\ng1,2,0\ng2,-2,NA\n'):
    response=client.post(f'/api/v1/projects/{project}/bio-resource-files',files={'file':('external.csv',content)},
                         headers={'Idempotency-Key':'original-file'})
    assert response.status_code==201,response.text
    return response.json()


def import_plan(source,decision='draft',revision=0):
    return dict(name='external differential table',kind='result_import',decision=decision,expected_revision=revision,
        sources=[dict(source_kind='original_file',source_id=source['file_id'],sha256=source['sha256'],role='table')],
        config=dict(kind='result_import',file_source_id=source['file_id'],parse_version_id=source['table_reader_identity'],
                    species_taxon_id=9606,namespace='Ensembl',reference_version='declared-v1',
                    columns={'feature_id':'gene','effect':'effect','p_value':'p'},contrast_id='c',numerator='A',denominator='B',
                    original_method='existing tool',original_correction_scope='unknown'))


def test_plan_save_confirmation_cas_request_recovery_and_owner_scope(client):
    project=create_project(client)['id'];source=source_file(client,project)
    base=f'/api/v1/projects/{project}'
    body=import_plan(source)
    response=client.post(base+'/bio-insight-plans',json=body,headers={'Idempotency-Key':'plan-one'})
    assert response.status_code==201,response.text
    draft=response.json();assert draft['decision']=='draft' and draft['revision']==1
    assert client.post(base+'/bio-insight-plans',json=body,headers={'Idempotency-Key':'plan-one'}).status_code==200
    assert client.post(base+'/bio-insight-plans',json={**body,'name':'changed'},headers={'Idempotency-Key':'plan-one'}).status_code==409
    run=dict(plan_version_id=draft['id'],expected_plan_revision=1,source_digest=draft['source_digest'])
    assert client.post(base+'/bio-insight-runs',json=run,headers={'Idempotency-Key':'draft-run'}).status_code==422
    confirmed=client.post(base+'/bio-insight-plans/'+draft['plan_id']+'/versions',json=import_plan(source,'confirmed',1),
                          headers={'Idempotency-Key':'confirmed'})
    assert confirmed.status_code==201,confirmed.text
    value=confirmed.json();assert value['id']!=draft['id'] and value['revision']==2
    assert client.get(base+'/bio-insight-plans/'+draft['plan_id']+'/versions/'+draft['id']).json()['decision']=='draft'
    assert client.post(base+'/bio-insight-plans/'+draft['plan_id']+'/versions',json=import_plan(source,'confirmed',1),
                       headers={'Idempotency-Key':'stale'}).status_code==409
    recovered=client.get(base+'/bio-insight-requests/confirmed?kind=plan')
    assert recovered.status_code==200 and recovered.json()['id']==value['id']
    assert client.get(base+'/bio-insight-requests/confirmed?kind=run').status_code==404
    other=create_project(client)['id']
    assert client.post(f'/api/v1/projects/{other}/bio-insight-plans',json=body,headers={'Idempotency-Key':'cross'}).status_code==404
    assert client.get(f'/api/v1/projects/{other}/bio-insight-plans/{value["plan_id"]}/versions/{value["id"]}').status_code==404


def test_upload_is_original_only_hash_checked_idempotent_and_accepts_raw_resources(client):
    project=create_project(client)['id'];base=f'/api/v1/projects/{project}'
    first=source_file(client,project)
    recovery=client.get(base+'/bio-resource-files/requests/original-file')
    assert recovery.status_code==200 and recovery.json()['file_id']==first['file_id']
    assert client.get(base+'/bio-resource-files/requests/unknown').status_code==404
    assert first['sha256']==hashlib.sha256(b'gene,effect,p\ng1,2,0\ng2,-2,NA\n').hexdigest()
    response=client.post(base+'/bio-resource-files',files={'file':('external.csv',b'changed')},headers={'Idempotency-Key':'original-file'})
    assert response.status_code==409,response.text
    gaf=client.post(base+'/bio-resource-files',files={'file':('go.gaf',b'!gaf-version: 2.2\n')},headers={'Idempotency-Key':'gaf'})
    assert gaf.status_code==201,gaf.text
    assert gaf.json()['parse_status']=='stored'
    assert client.post(base+'/bio-resource-files',files={'file':('script.py',b'print(1)')},headers={'Idempotency-Key':'script'}).status_code==422


def test_literal_table_parse_has_real_persisted_task_attempt_and_result(client):
    from app.db.database import database_connection
    from app.core.config import get_data_dir
    from app.adapters.storage import ProjectStore
    from app.domain.bio_insights.uploads import BioResourceUploadService
    project=create_project(client)['id']
    with database_connection() as db:owner=db.execute('SELECT owner_id FROM projects WHERE id=%s',(project,)).fetchone()['owner_id']
    value,_=BioResourceUploadService(ProjectStore(get_data_dir(),owner_id=owner)).upload(project,'real.tsv',b'feature\teffect\ng1\t0\n','literal-table')
    with database_connection() as db:
        row=db.execute('SELECT p.*,t.status,t.workflow_version FROM file_parse_results p JOIN tasks t ON t.id=p.task_id WHERE p.id=%s',(value['parse_version_id'],)).fetchone()
        assert row['status']=='succeeded' and row['workflow_version']=='bio_insight_table_v1'
        assert row['result_json']['total_rows']==1
        assert db.execute('SELECT count(*) AS n FROM task_attempts WHERE task_id=%s',(row['task_id'],)).fetchone()['n']==1


def test_run_freezes_confirmed_version_and_validates_sources_on_every_read(client,monkeypatch):
    from app.domain.bio_insights.service import BioInsightsService
    from app.db.database import database_connection
    from app.core.config import get_data_dir
    from app.adapters.storage import ProjectStore
    from app.core.exceptions import StorageError
    from pathlib import Path
    import pytest
    runtime=dict(engine_version='bio_insights_v1.0.0',environment_digest='e'*64,code_digest='c'*64,lock_sha256='f'*64)
    monkeypatch.setattr(BioInsightsService,'_runtime',lambda self:runtime)
    project=create_project(client)['id'];source=source_file(client,project);base=f'/api/v1/projects/{project}'
    plan=client.post(base+'/bio-insight-plans',json=import_plan(source,'confirmed'),headers={'Idempotency-Key':'frozen-plan'}).json()
    body=dict(plan_version_id=plan['id'],expected_plan_revision=1,source_digest=plan['source_digest'])
    created=client.post(base+'/bio-insight-runs',json=body,headers={'Idempotency-Key':'run-one'})
    assert created.status_code==202,created.text
    run=created.json();assert run['task']['task_type']=='bio_result_import'
    assert client.post(base+'/bio-insight-runs',json=body,headers={'Idempotency-Key':'run-one'}).status_code==200
    assert client.post(base+'/bio-insight-runs',json={**body,'source_digest':'a'*64},headers={'Idempotency-Key':'run-one'}).status_code==409
    assert client.get(base+'/bio-insight-requests/run-one?kind=run').json()['id']==run['id']
    # A newer plan does not invalidate the already queued frozen version.
    newer=client.post(base+'/bio-insight-plans/'+plan['plan_id']+'/versions',json=import_plan(source,'confirmed',1),headers={'Idempotency-Key':'new-plan'})
    assert newer.status_code==201,newer.text
    with database_connection() as db:
        owner=db.execute('SELECT owner_id FROM projects WHERE id=%s',(project,)).fetchone()['owner_id']
        task=dict(db.execute('SELECT * FROM tasks WHERE id=%s',(run['task_id'],)).fetchone())
    service=BioInsightsService(ProjectStore(get_data_dir(),owner_id=owner))
    with service.store.connection() as db:
        payload=service.require_sources(db,task,runtime=False)
        assert payload['kind']=='bio_result_import' and payload['config']['kind']=='result_import'
        assert payload['identity']['plan_version_id']==plan['id']
        path=Path(payload['sources'][0]['members']['original_file']['path'])
    path.write_bytes(path.read_bytes()+b'tampered')
    with service.store.connection() as db:
        with pytest.raises(StorageError):service.require_sources(db,task,runtime=False)


def test_table_upload_and_preview_reject_bad_columns_parse_identity_and_nonrectangular_values(client):
    project=create_project(client)['id'];base=f'/api/v1/projects/{project}'
    bad=client.post(base+'/bio-resource-files',files={'file':('bad.csv',b'gene,p\ng1,0,extra\n')},headers={'Idempotency-Key':'bad-file'})
    assert bad.status_code==422,bad.text
    source=source_file(client,project);body=import_plan(source)
    body['config']['columns']['p_value']='missing'
    assert client.post(base+'/bio-insight-plans/preview',json=body).status_code==422
    body=import_plan(source);body['config']['parse_version_id']='not-a-real-parse-version'
    assert client.post(base+'/bio-insight-plans/preview',json=body).status_code==409
    body=import_plan(source);body['sources'][0]['locator']={'kind':'row','table':'original_file','row_key':{'gene':'missing'},'field':'p'}
    assert client.post(base+'/bio-insight-plans/preview',json=body).status_code==422
    from app.db.database import database_connection
    with database_connection() as db:
        assert db.execute("SELECT count(*) AS n FROM files WHERE project_id=%s AND filename='bad.csv'",(project,)).fetchone()['n']==0
