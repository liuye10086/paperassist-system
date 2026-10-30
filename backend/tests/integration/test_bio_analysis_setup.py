"""Real owner-scoped SQL/CAS/storage checks; numerical engine is not involved."""
import pytest
from tests.api.test_projects import client, create_project
from tests.integration.test_bio_import_publication import create_import, run, read, confirm


def raw_source(client):
    base, created, _, _ = create_import(client)
    waiting = run(created['task'])
    assert waiting['status'] == 'waiting_confirmation', waiting
    view = read(client, base, created)
    queued = confirm(client, base, created, view)
    assert queued.status_code == 202, queued.text
    done = run(queued.json())
    assert done['status'] == 'succeeded', done
    return base, read(client, base, created)['result_source']


def test_setup_recipe_idempotency_cas_and_cross_project_source(client):
    base, source = raw_source(client)
    body = dict(name='small Visium configuration',raw_source=source,expected_revision=0,params={})
    headers = {'Idempotency-Key':'setup-create'}
    response = client.post(base+'/bio-analysis-setups',json=body,headers=headers)
    assert response.status_code == 201, response.text
    recipe = response.json()
    assert recipe['version'] == 1 and recipe['revision'] == 1
    assert recipe['raw_source'] == source
    assert client.post(base+'/bio-analysis-setups',json=body,headers=headers).json() == recipe
    changed = {**body,'name':'different body'}
    assert client.post(base+'/bio-analysis-setups',json=changed,headers=headers).status_code == 409
    lookup = client.get(base+'/bio-requests/setup-create?kind=recipe')
    assert lookup.status_code == 200 and lookup.json()['id'] == recipe['id']
    newer = client.post(base+f"/bio-analysis-setups/{recipe['setup_id']}/recipes",
        json={**body,'expected_revision':1,'params':{'min_spots':1}},headers={'Idempotency-Key':'setup-next'})
    assert newer.status_code == 201, newer.text
    assert newer.json()['version'] == 2
    stale = client.post(base+f"/bio-analysis-setups/{recipe['setup_id']}/recipes",
        json={**body,'expected_revision':1},headers={'Idempotency-Key':'setup-stale'})
    assert stale.status_code == 409
    other = create_project(client)
    crossed = client.post(f"/api/v1/projects/{other['id']}/bio-analysis-setups",json=body,headers=headers)
    assert crossed.status_code in (404,409), crossed.text
    saved = client.get(base+f"/bio-analysis-setups/{recipe['setup_id']}/recipes/{recipe['id']}")
    assert saved.status_code == 200 and saved.json()['params']['min_spots'] == 3


def test_mapping_bad_barcode_duplicate_and_unknown_values_are_not_published(client):
    from app.db.database import database_connection
    base, source = raw_source(client)
    body = dict(name='unknowns retained',raw_source=source,expected_revision=0,rows=[])
    response = client.post(base+'/bio-observation-maps',json=body,headers={'Idempotency-Key':'map-create'})
    assert response.status_code == 201, response.text
    assert response.json()['counts'] == {'mapped':0,'unmapped':2,'total':2}
    original=response.json()
    newer=client.post(base+f"/bio-observation-maps/{original['set_id']}/versions",json={**body,'name':'renamed','expected_revision':1},headers={'Idempotency-Key':'map-renamed'})
    assert newer.status_code==201,newer.text
    assert client.get(base+f"/bio-observation-maps/{original['set_id']}/versions/{original['id']}").json()['name']==original['name']
    invalid = client.post(base+'/bio-observation-maps',json={**body,'rows':[{'barcode':'not-real'}]},
        headers={'Idempotency-Key':'map-invalid'})
    assert invalid.status_code == 422, invalid.text
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM bio_observation_map_versions').fetchone()['n'] == 2


def test_annotation_geometry_is_canonical_and_normalized_evidence_is_scoped(client):
    base, source = raw_source(client)
    body = dict(name='exploratory region',raw_source=source,expected_revision=0,
        labels=[dict(id='label1',name='region enriched',status='proposed')],
        regions=[dict(id='r1',label_id='label1',points=[[1.0,1.0],[3.0,1.0],[3.0,3.0],[1.0,3.0]])])
    response = client.post(base+'/bio-annotation-sets',json=body,headers={'Idempotency-Key':'annotation-create'})
    assert response.status_code == 201, response.text
    result = response.json()
    rows = {row['barcode']:row for row in result['assignments']}
    assert rows['AA-1']['label_id'] == 'label1' and rows['BB-1']['status'] == 'unknown'
    assert 'CC-1' not in rows, 'Non-matrix positioning spots cannot become observations'
    readback = client.get(base+f"/bio-annotation-sets/{result['set_id']}/versions/{result['id']}")
    assert readback.status_code == 200 and readback.json() == result
    invalid = {**body,'evidence':[dict(label_id='label1',kind='file',file_id='missing')],
               'expected_revision':1}
    response = client.post(base+f"/bio-annotation-sets/{result['set_id']}/versions",json=invalid,
        headers={'Idempotency-Key':'annotation-missing-evidence'})
    assert response.status_code in (404,422), response.text


@pytest.mark.parametrize('kind',['map','recipe'])
def test_version_writer_locks_root_before_reading_revision(client,monkeypatch,kind):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event,get_ident
    from app.db.database import database_connection,DatabaseConnection
    from app.adapters.bio_analysis_store import BioAnalysisStore
    base,source=raw_source(client)
    path='/bio-observation-maps' if kind=='map' else '/bio-analysis-setups'
    body=dict(name='concurrent root',raw_source=source,expected_revision=0,**({'rows':[]} if kind=='map' else {'params':{}}))
    created=client.post(base+path,json=body,headers={'Idempotency-Key':'lock-root'})
    assert created.status_code==201,created.text
    root=created.json()['set_id' if kind=='map' else 'setup_id']
    table='bio_observation_map_sets' if kind=='map' else 'bio_analysis_setups'
    reached=Event();locked=Event();observed=[];main_thread=get_ident();original=BioAnalysisStore.require
    execute=DatabaseConnection.execute
    def traced(self,sql,*args,**kwargs):
        result=execute(self,sql,*args,**kwargs)
        if get_ident()!=main_thread and ('FROM '+table) in sql and 'FOR UPDATE' in sql:locked.set()
        return result
    monkeypatch.setattr(DatabaseConnection,'execute',traced)
    def require(self,db,t,project,identifier):
        value=original(self,db,t,project,identifier)
        if t==table:observed.append(locked.is_set());reached.set()
        return value
    monkeypatch.setattr(BioAnalysisStore,'require',require)
    pool=ThreadPoolExecutor(1)
    with database_connection(write=True) as db:
        db.execute(f'SELECT id FROM {table} WHERE id=%s FOR UPDATE',(root,))
        future=pool.submit(client.post,base+path+'/'+root+('/versions' if kind=='map' else '/recipes'),
            json={**body,'expected_revision':1},headers={'Idempotency-Key':'lock-next'})
        unsafe_read=reached.wait(3.0)
    response=future.result(timeout=10);pool.shutdown()
    assert not unsafe_read,'Root revision was read without obtaining its row lock'
    assert observed and all(observed),'Version CAS must hold the root lock before reading its revision'
    assert response.status_code==201,response.text
