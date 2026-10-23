"""0044→0045 retains nonempty public records, indexes, originals and sealed history."""
import pytest
from alembic import command
from sqlalchemy.exc import SQLAlchemyError
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_school_templates import setup as school_setup
from tests.api.test_journals import setup,profile,request,post
from tests.maintenance.test_literature_evidence_migration import fingerprints
from app.db.database import migration_connection,database_connection,alembic_config,get_migration_database_config,SCHEMA_HEAD


def test_0045_preserves_nonempty_0044_records_indexes_and_originals(client):
    path,template=school_setup(client)
    original=client.get(path+'/files/'+template['template_file_id']+'/download').content
    cfg=alembic_config()
    with migration_connection(write=True) as db:
        assert db.config.schema.startswith('pa_test_')
        assert db.execute('SELECT current_database() name').fetchone()['name']=='paperassist_system_test'
        cfg.attributes.update(connection=db.raw_connection,database_config=get_migration_database_config())
        command.downgrade(cfg,'0044_school_changes')
        tables=[r['tablename'] for r in db.execute('SELECT tablename FROM pg_tables WHERE schemaname=current_schema()') if r['tablename']!='alembic_version']
        before=fingerprints(db,tables)
        indexes={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        constraints={r['conname']:r['definition'] for r in db.execute('SELECT conname,pg_get_constraintdef(oid) definition FROM pg_constraint WHERE connamespace=current_schema()::regnamespace')}
        command.upgrade(cfg,'0045_journal_recommendations')
        assert fingerprints(db,tables)==before
        after={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        assert all(after.get(k)==v for k,v in indexes.items())
        actual={r['conname']:r['definition'] for r in db.execute('SELECT conname,pg_get_constraintdef(oid) definition FROM pg_constraint WHERE connamespace=current_schema()::regnamespace')}
        assert all(actual.get(k)==v for k,v in constraints.items() if k!='tasks_type_check')
        command.upgrade(cfg,SCHEMA_HEAD)
    assert client.get(path+'/files/'+template['template_file_id']+'/download').content==original
    from app.maintenance.database_audit import audit_database
    with database_connection() as db:audit=audit_database(db)
    assert audit['ok'],audit['schema_issues'] or [c for c in audit['data_checks'] if c['invalid']]


def test_journal_seals_json_checks_scope_and_guarded_downgrade(client):
    base=setup(client);p=post(client,base+'/profiles',profile()).json()
    item=post(client,base+'/recommendations',request()).json()
    for sql in ['UPDATE journal_profiles SET snapshot_json=\'{}\'', 'DELETE FROM journal_profiles', 'UPDATE journal_recommendations SET snapshot_json=\'{}\'', 'DELETE FROM journal_recommendations']:
        with pytest.raises(SQLAlchemyError):
            with database_connection(write=True) as db:db.execute(sql)
    with pytest.raises(SQLAlchemyError):
        with database_connection(write=True) as db:db.execute("UPDATE tasks SET input_snapshot='{}' WHERE id=%s",(item['task']['id'],))
    other=setup(client).split('/projects/')[1].split('/')[0]
    with pytest.raises(SQLAlchemyError):
        with database_connection(write=True) as db:db.execute('''INSERT INTO journal_profiles(id,project_id,user_id,idempotency_key,request_json,request_digest,snapshot_json,snapshot_sha256,created_at,previous_version_id) SELECT 'bad',%s,user_id,'bad',request_json,request_digest,snapshot_json,snapshot_sha256,created_at,id FROM journal_profiles WHERE id=%s''',(other,p['id']))
    cfg=alembic_config()
    with pytest.raises(RuntimeError,match='refusing destructive downgrade'):
        with migration_connection(write=True) as db:
            cfg.attributes.update(connection=db.raw_connection,database_config=get_migration_database_config())
            command.downgrade(cfg,'0044_school_changes')
    with database_connection(write=True) as db:db.execute('UPDATE tasks SET input_digest=%s WHERE id=%s',('a'*64,item['task']['id']))
    from app.maintenance.journal_audit import audit_journals
    with database_connection() as db:checks=audit_journals(db,limit=1)
    assert next(c for c in checks if c['table']=='journal_recommendations')['invalid']==1
