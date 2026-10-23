"""0042 adds a nullable school binding without rewriting SCI history."""
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_manuscripts import setup,body
from tests.api.test_literature_evidence import post
from app.db.database import database_connection


def test_school_binding_column_preserves_sci_snapshot(client):
    path,_,_=setup(client)
    created=post(client,path,body(),'sci-control')
    assert created.status_code==201,created.text
    version=created.json()['versions'][0]
    with database_connection() as db:
        row=db.execute('SELECT snapshot_json,school_confirmation_id FROM manuscript_versions WHERE id=%s',(version['id'],)).fetchone()
        assert row['school_confirmation_id'] is None
        assert row['snapshot_json']==version['snapshot']
    assert 'thesis_context' not in version['snapshot']

def test_school_migration_adds_scope_fk_preserves_old_data_and_guards_downgrade(client):
    import pytest
    from alembic import command
    from sqlalchemy.exc import SQLAlchemyError
    from app.db.database import migration_connection,alembic_config,get_migration_database_config
    from tests.api.test_thesis_manuscripts import bound
    from tests.maintenance.test_literature_evidence_migration import fingerprints
    path,_,_=setup(client)
    sci=post(client,path,body(),'sci-before').json()
    cfg=alembic_config()
    with migration_connection(write=True) as db:
        cfg.attributes.update(connection=db.raw_connection,database_config=get_migration_database_config())
        command.downgrade(cfg,'0041_school_templates')
        before=fingerprints(db,['manuscripts','manuscript_versions','manuscript_sources','school_template_versions'])
        # Compare the pre-existing fields; the sole new nullable column is expected.
        rows=list(db.execute('SELECT id,snapshot_json,snapshot_sha256,request_json,request_digest FROM manuscript_versions'))
        command.upgrade(cfg,'0042_thesis_manuscripts')
        assert list(db.execute('SELECT id,snapshot_json,snapshot_sha256,request_json,request_digest FROM manuscript_versions'))==rows
        assert fingerprints(db,['manuscripts','manuscript_sources','school_template_versions'])=={k:v for k,v in before.items() if k!='manuscript_versions'}
        # Restore the current additive head before exercising application APIs.
        command.upgrade(cfg,'head')
    school,_,request=bound(client)
    school_root=post(client,school+'/manuscripts',request,'school').json()
    with pytest.raises(SQLAlchemyError) as scope_error:
        with migration_connection(write=True) as db:
            db.execute('UPDATE manuscript_versions SET school_confirmation_id=%s WHERE id=%s',(request['thesis']['confirmation_id'],sci['versions'][0]['id']))
    assert scope_error.value.orig.diag.constraint_name=='mv_school_confirmation_scope_fk'
    with pytest.raises(RuntimeError,match='refusing destructive downgrade'):
        with migration_connection(write=True) as db:
            cfg.attributes.update(connection=db.raw_connection,database_config=get_migration_database_config())
            command.downgrade(cfg,'0041_school_templates')
    assert client.get(school+'/manuscripts/'+school_root['id']).status_code==200
