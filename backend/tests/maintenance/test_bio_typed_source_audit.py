"""Bio source audits stay distinct from Excel sources and reject real drift."""
from copy import deepcopy
from psycopg.types.json import Jsonb
from app.db.database import database_connection
from app.maintenance.database_audit import audit_database
from tests.api.test_projects import client


def test_v2_import_is_audited_as_bio_and_corrupt_original_is_still_rejected(client,monkeypatch):
    from tests.integration.test_bio_import_publication import create_import
    from app.core.config import get_data_dir
    monkeypatch.setattr('app.domain.bioinformatics.analysis_settings.runtime_identity',lambda:dict(available=True,
        engine_version='visium_explore_v1.0.0',environment_digest='a'*64,code_digest='b'*64))
    base,_,file_id,_=create_import(client)
    created=client.post(base+'/bio-imports',json=dict(file_ids=[file_id],assay='visium',name='v2 audit',
        expected_dataset_revision=0,matrix_representation='mtx',compare_alternate=False),headers={'Idempotency-Key':'v2-audit'})
    assert created.status_code==202,created.text
    with database_connection() as db:
        db.execute('SET TRANSACTION READ ONLY')
        before=list(db.execute('SELECT id,input_digest,input_snapshot FROM tasks ORDER BY id'))
        result=audit_database(db)
        assert result['ok'],[c for c in result['data_checks'] if c['invalid']]
        assert list(db.execute('SELECT id,input_digest,input_snapshot FROM tasks ORDER BY id'))==before
        file=db.execute('SELECT object_key,size_bytes FROM files WHERE id=%s',(file_id,)).fetchone()
    # Only the new isolated fixture original is deliberately damaged.
    (get_data_dir()/file['object_key']).write_bytes(b'x'*file['size_bytes'])
    with database_connection() as db:
        db.execute('SET TRANSACTION READ ONLY')
        result=audit_database(db)
    assert not result['ok']
    assert next(c for c in result['data_checks'] if c['table']=='bio_imports' and c['column']=='frozen_inputs_task_candidate')['invalid']==2


def test_raw_and_processed_task_sources_are_audited_even_before_publication(client,monkeypatch,tmp_path):
    from tests.integration.test_bio_analysis_wait import create,run,confirm
    from app.domain.bioinformatics.analysis_contracts import digest
    from app.maintenance.bio_task_source_audit import audit_bio_task_sources
    base,created,staging,_=create(client,monkeypatch,tmp_path)
    assert run(created['task'],staging)['status']=='waiting_confirmation'
    queued=confirm(client,base,created,client.get(base+'/bio-analysis-runs/'+created['id']).json())
    done=run(queued.json(),staging);assert done['status']=='succeeded'
    result=client.get(base+'/bio-processed-datasets/'+done['result_bio_processed_dataset_version_id']).json()
    figure=client.post(base+'/bio-figures',json=dict(processed_source=result['source'],expected_version=0,
        config={'kind':'qc'}),headers={'Idempotency-Key':'audit-figure'})
    assert figure.status_code==202,figure.text
    def forbidden(*args,**kwargs):raise AssertionError('Relational task audit must not inspect assets or current runtime')
    monkeypatch.setattr('app.adapters.bio_objects.BioObjects.read',forbidden)
    monkeypatch.setattr('app.domain.bioinformatics.analysis_service.runtime_identity',forbidden)
    def check():
        with database_connection() as db:
            db.execute('SET TRANSACTION READ ONLY')
            checks=audit_bio_task_sources(db)
        return next(c for c in checks if c['table']=='tasks' and c['column']=='bio_typed_sources')
    assert check()['rows']==2 and check()['invalid']==0
    # Failed historical work keeps its frozen source valid without needing its
    # worker image to be installed or treating failure as source corruption.
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET status='failed',error_code='bio_environment_unavailable' WHERE id=%s",(figure.json()['task']['id'],))
    assert check()['invalid']==0
    for task_id,key in ((created['task']['id'],'raw_source'),(figure.json()['task']['id'],'processed_source')):
        with database_connection() as db:
            original=dict(db.execute('SELECT * FROM tasks WHERE id=%s',(task_id,)).fetchone())
        snapshot=deepcopy(original['input_snapshot']);snapshot[key]['manifest_sha256']='0'*64
        with database_connection(write=True) as db:
            db.execute('UPDATE tasks SET input_snapshot=%s,input_digest=%s WHERE id=%s',(Jsonb(snapshot),digest(snapshot),task_id))
        # A bad raw producer also invalidates its dependent figure source.
        assert check()['invalid']==(2 if key=='raw_source' else 1),key
        with database_connection(write=True) as db:
            db.execute('UPDATE tasks SET input_snapshot=%s,input_digest=%s WHERE id=%s',
                (Jsonb(original['input_snapshot']),original['input_digest'],task_id))
    assert check()['invalid']==0
