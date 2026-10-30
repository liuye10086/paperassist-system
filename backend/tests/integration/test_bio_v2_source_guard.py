"""Same-GSM v2 imports retain the published root; v1 behavior stays unchanged."""
from tests.api.test_projects import client
from tests.integration.test_bio_import_publication import create_import,run,read,confirm,pure_registered_parser
from app.db.database import database_connection


def v2_parser(manifest,output,settings):
    result=pure_registered_parser(manifest,output,settings)
    result['parser_version']=manifest['parser_version']
    result['manifest']['parser_version']=manifest['parser_version']
    member=next(m for m in result['outputs'] if 'matrix.mtx' in m['source_member_name'])
    result['manifest']['representation']=dict(selected='mtx',matrix_representation='mtx',compare_alternate=False,
        comparison={'status':'not_comparable'},chosen_source={k:member[k] for k in ('source_file_id','source_member_name','sha256')})
    return result


def test_v2_duplicate_published_gsm_requires_existing_root(client,monkeypatch,tmp_path):
    monkeypatch.setenv('PAPERASSIST_BIO_STAGING_DIR',str(tmp_path/'bio-staging'))
    monkeypatch.setattr('app.domain.bioinformatics.analysis_settings.runtime_identity',lambda:dict(available=True,
        engine_version='visium_explore_v1.0.0',environment_digest='a'*64,code_digest='b'*64))
    base,legacy,file_id,_=create_import(client)
    assert run(legacy['task'])['status']=='waiting_confirmation'
    queued=confirm(client,base,legacy,read(client,base,legacy));assert queued.status_code==202
    assert run(queued.json())['status']=='succeeded'
    request=dict(file_ids=[file_id],assay='visium',name='same GSM representation',expected_dataset_revision=0,
        matrix_representation='mtx',compare_alternate=False)
    created=client.post(base+'/bio-imports',json=request,headers={'Idempotency-Key':'v2-other-root'})
    assert created.status_code==202,created.text
    failed=run(created.json()['task'],v2_parser)
    assert failed['status']=='failed' and failed['error_code']=='bio_source_conflict',failed
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM bio_dataset_versions').fetchone()['n']==1
        root=db.execute('SELECT * FROM bio_datasets WHERE id=%s',(legacy['dataset_id'],)).fetchone()
        assert db.execute('SELECT * FROM bio_datasets WHERE id=%s',(created.json()['dataset_id'],)).fetchone(), 'Preserve the empty root for audit'
    existing=client.post(base+'/bio-imports',json={**request,'dataset_id':legacy['dataset_id'],'expected_dataset_revision':root['revision']},headers={'Idempotency-Key':'v2-existing-root'})
    assert existing.status_code==202,existing.text
    waiting=run(existing.json()['task'],v2_parser)
    assert waiting['status']=='waiting_confirmation',waiting
    queued=confirm(client,base,existing.json(),read(client,base,existing.json()),'v2-confirm')
    assert queued.status_code==202,queued.text
    assert run(queued.json())['status']=='succeeded'
