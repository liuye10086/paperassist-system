import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from app.db.database import database_connection, migration_connection
from app.db.schema import metadata
from tests.api.test_projects import client


def test_bio_frozen_import_and_dataset_pointer_constraints(client):
    from tests.integration.test_bio_import_publication import create_import,run,read,confirm
    base,created,file_id,_=create_import(client)
    waiting=run(created['task'])
    assert waiting['status']=='waiting_confirmation',waiting
    view=read(client,base,created)
    queued=confirm(client,base,created,view)
    assert queued.status_code==202,queued.text
    done=run(queued.json())
    assert done['status']=='succeeded',done
    other=client.post(base+'/bio-imports',json={
        'file_ids':[file_id],'assay':'visium','name':'other dataset','expected_dataset_revision':0},headers={'Idempotency-Key':'second-dataset'})
    assert other.status_code==202,other.text
    with pytest.raises(IntegrityError) as error:
        with database_connection(write=True) as db:
            db.execute('UPDATE bio_datasets SET current_version_id=%s WHERE id=%s',
                       (done['result_bio_dataset_version_id'],other.json()['dataset_id']))
    assert error.value.orig.diag.constraint_name=='cr_bd_current_fk'
    with pytest.raises(SQLAlchemyError) as error:
        with migration_connection() as db:
            db.execute('UPDATE bio_imports SET request_digest=%s WHERE id=%s',('b'*64,created['id']))
    assert 'Immutable bio import source' in str(error.value)
    with database_connection() as db:
        original=dict(db.execute('SELECT * FROM tasks WHERE id=%s',(done['id'],)).fetchone())
    original.update(id='invalid-bio-snapshot',idempotency_key='invalid-bio-snapshot',input_snapshot={})
    with pytest.raises(IntegrityError) as error:
        with database_connection(write=True) as db:
            db.raw_connection.execute(metadata.tables['tasks'].insert(),original)
    assert error.value.orig.diag.constraint_name=='tasks_bio_snapshot_check'
