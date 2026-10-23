"""0043 seals school export intent and preserves nonempty legacy exports."""
import pytest
from alembic import command
from sqlalchemy.exc import SQLAlchemyError
from tests.api.test_analysis import client  # noqa:F401
from tests.api.test_manuscripts import setup,body
from tests.api.test_literature_evidence import post
from app.domain.tasks.execution import run_task
from app.db.database import migration_connection,alembic_config,get_migration_database_config


def test_school_export_migration_preserves_legacy_metadata_hash_and_indexes(client):
    path,_,_=setup(client)
    root=post(client,path,body(),'sci').json()
    run_task(root['versions'][0]['task_id'],1)
    exported=post(client,path+'/'+root['id']+'/versions/1/exports',{},'sci-export').json()
    assert run_task(exported['task_id'],1)['status']=='succeeded'
    download=client.get(path+'/'+root['id']+'/exports/'+exported['id']+'/download').content
    cfg=alembic_config()
    with migration_connection(write=True) as db:
        cfg.attributes.update(connection=db.raw_connection,database_config=get_migration_database_config())
        command.downgrade(cfg,'0042_thesis_manuscripts')
        fields='id,version_id,task_id,idempotency_key,metadata_json,created_at'
        rows=list(db.execute('SELECT '+fields+' FROM manuscript_exports ORDER BY id'))
        snapshots=list(db.execute('SELECT id,snapshot_json,snapshot_sha256,request_json,request_digest FROM manuscript_versions ORDER BY id'))
        tasks=list(db.execute('SELECT id,input_snapshot,input_digest FROM tasks ORDER BY id'))
        indexes=list(db.execute("SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema() ORDER BY indexname"))
        command.upgrade(cfg,'0043_school_exports')
        assert list(db.execute('SELECT '+fields+' FROM manuscript_exports ORDER BY id'))==rows
        assert list(db.execute('SELECT id,snapshot_json,snapshot_sha256,request_json,request_digest FROM manuscript_versions ORDER BY id'))==snapshots
        assert list(db.execute('SELECT id,input_snapshot,input_digest FROM tasks ORDER BY id'))==tasks
        assert list(db.execute("SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema() ORDER BY indexname"))==indexes
        assert db.execute('SELECT school_input_json,school_input_sha256 FROM manuscript_exports').fetchone()==dict(school_input_json=None,school_input_sha256=None)
    assert client.get(path+'/'+root['id']+'/exports/'+exported['id']+'/download').content==download
    with pytest.raises(SQLAlchemyError) as error:
        with migration_connection(write=True) as db:
            db.execute("UPDATE manuscript_exports SET school_input_json='{}'::jsonb WHERE id=%s",(exported['id'],))
    assert error.value.orig.diag.constraint_name=='me_school_input_check'


def test_school_export_downgrade_refuses_sealed_history(client):
    from tests.api.test_school_exports import published
    _,base,_,_=published(client)
    assert post(client,base+'/versions/1/exports',{},'school').status_code==201
    cfg=alembic_config()
    with pytest.raises(RuntimeError,match='refusing destructive downgrade'):
        with migration_connection(write=True) as db:
            cfg.attributes.update(connection=db.raw_connection,database_config=get_migration_database_config())
            command.downgrade(cfg,'0042_thesis_manuscripts')
