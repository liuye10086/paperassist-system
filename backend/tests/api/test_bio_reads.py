"""Scope, bounds and fixed member identity at public read boundaries."""
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import get_data_dir
from app.db.database import database_connection
from tests.api.test_projects import client,create_project
from tests.integration.test_bio_import_publication import create_import,run,read,confirm


def test_published_reads_preserve_coordinates_scope_bounds_and_hashes(client):
    from app.auth.service import create_user
    base,created,_,_=create_import(client)
    run(created['task'])
    view=read(client,base,created)
    assert view['candidate']['images']
    accepted=confirm(client,base,created,view)
    assert accepted.status_code==202,accepted.text
    done=run(accepted.json())
    assert done['status']=='succeeded',done
    source=read(client,base,created)['result_source']
    assert source['schema_version']==1 and source['version']==1 and len(source['source_file_ids'])==1
    path=base+f"/bio-datasets/{source['dataset_id']}/versions/{source['dataset_version_id']}"
    detail=client.get(path)
    assert detail.status_code==200,detail.text
    assert 'object_key' not in detail.text
    assert detail.json()['source']==source
    matrix=next(m for m in detail.json()['members'] if m['role']=='matrix_data')
    assert matrix['filename']=='matrix_data.npy'
    matrix_bytes=client.get(matrix['download_url'])
    assert matrix_bytes.content.startswith(b'\x93NUMPY')
    assert 'matrix_data.npy' in matrix_bytes.headers['content-disposition']
    assert client.get(matrix['download_url']+'/download').content==matrix_bytes.content
    preview=client.get(path+'/matrix-preview').json()
    assert [f['id'] for f in preview['features']]==['ENSG_TEST_1','ENSG_TEST_2','ENSG_TEST_3']
    assert [f['symbol'] for f in preview['features']]==['G1','SAME','SAME']
    assert preview['values']==[[5,2,0],[1,0,4]]
    image=next(m for m in detail.json()['members'] if m['role']=='tissue_image')
    assert not image['filename'].endswith('.gz')
    coordinates=client.get(path+'/coordinate-preview',params={'image_member_id':image['id']})
    assert coordinates.status_code==200,coordinates.text
    points={p['barcode']:(p['x'],p['y'],p['in_tissue']) for p in coordinates.json()['points']}
    assert points=={'AA-1':(2,2,1),'BB-1':(4,4,1),'CC-1':(6,6,0)}
    assert coordinates.json()['truncated'] is False
    assert client.get(path+'/matrix-preview?features_page=0').status_code==422
    assert client.get(path+'/matrix-preview?features_page=2').json()['values']==[]
    other_project=create_project(client)
    foreign=path.replace(base,'/api/v1/projects/'+other_project['id'])
    assert client.get(foreign).status_code==404
    for role in ('user','admin'):
        email='bio-foreign-'+role+'@example.invalid'
        create_user(email,'isolated-password-2026',role=role)
        with TestClient(app) as other:
            other.headers.update({'X-PaperAssist-Client':'web','Origin':'http://testserver'})
            logged=other.post('/api/v1/auth/login',json=dict(email=email,password='isolated-password-2026'))
            assert logged.status_code==200
            other.headers['X-CSRF-Token']=logged.json()['csrf_token']
            for target in (base+'/bio-imports/'+created['id'],path,path+'/manifest',path+'/members/'+image['id'],path+'/coordinate-preview'):
                assert other.get(target).status_code==404,target
    with database_connection() as db:
        record=db.execute('SELECT o.object_key FROM storage_objects o JOIN bio_dataset_members m ON m.object_id=o.id WHERE m.id=%s',(image['id'],)).fetchone()
    obj=get_data_dir()/record['object_key']
    original=obj.read_bytes()
    obj.write_bytes(b'x'*len(original))
    assert client.get(path).status_code==409
    assert client.get(path+'/members/'+image['id']).status_code==409
