"""Lifecycle schema is additive, scoped and refuses destructive downgrade."""
import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import DBAPIError
from app.db.database import database_connection, migration_connection, alembic_config, verify_runtime_permissions
from app.db.schema import metadata
from tests.api.test_projects import client  # noqa: F401


def test_lifecycle_tables_runtime_permissions_and_audit(postgres_schema):
    from app.maintenance.database_audit import audit_database
    with database_connection() as db:
        for name in ('file_deletion_requests','file_reparse_assessments'):
            assert name in inspect(db.raw_connection).get_table_names() and name in metadata.tables
        verify_runtime_permissions(db.raw_connection,postgres_schema)
        audit = audit_database(db)
        assert audit['ok'], str(audit['schema_issues']) + str([c for c in audit['data_checks'] if c['invalid']])
        assert any(c['column']=='lifecycle_integrity' for c in audit['data_checks'])


def test_lifecycle_migration_preserves_rows_and_old_indexes(postgres_schema,postgres_migration_config):
    from alembic import command
    from tests.db.test_task_schema import seed_owner,task_row,insert_row
    with migration_connection(config=postgres_migration_config) as db:
        config=alembic_config()
        config.attributes.update(connection=db.raw_connection,database_config=postgres_migration_config)
        command.downgrade(config,'0022_analysis_plans')
        seed_owner(db)
        insert_row(db,'tasks',task_row())
        tables=[r['table_name'] for r in db.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema() AND table_name<>'alembic_version'")]
        before={name:[dict(r) for r in db.execute('SELECT * FROM '+name)] for name in tables}
        indexes={r['indexname'] for r in db.execute('SELECT indexname FROM pg_indexes WHERE schemaname=current_schema()')}
        command.upgrade(config,'0023_file_lifecycle')
        assert before=={name:[dict(r) for r in db.execute('SELECT * FROM '+name)] for name in tables}
        assert indexes <= {r['indexname'] for r in db.execute('SELECT indexname FROM pg_indexes WHERE schemaname=current_schema()')}
        assert db.execute('SELECT count(*) AS n FROM file_deletion_requests').fetchone()['n']==0
        command.downgrade(config,'0022_analysis_plans')
        command.upgrade(config,'head')
    with database_connection() as db:
        verify_runtime_permissions(db.raw_connection,postgres_schema)


def test_lifecycle_scope_append_only_and_nonempty_downgrade(client,postgres_migration_config):
    from alembic import command
    from uuid import uuid4
    from tests.api.test_file_lifecycle import lifecycle,assessment
    from tests.api.test_projects import create_project
    from tests.db.test_task_schema import insert_row
    from app.maintenance.database_audit import audit_database
    _,_,base=lifecycle(client)
    value=assessment(client,base)
    created=client.post(base+'/lifecycle/deletion-requests',json=dict(reason='retain',expected_assessment_revision=value['assessment_revision']),headers={'Idempotency-Key':'keep'})
    assert created.status_code==201
    other=create_project(client)
    with database_connection() as db:
        row=dict(db.execute('SELECT * FROM file_deletion_requests').fetchone())
        assert audit_database(db)['ok']
    for changes in ({'project_id':other['id']},{'requested_by':'foreign'}):
        with pytest.raises(DBAPIError):
            with database_connection(write=True) as db:
                insert_row(db,'file_deletion_requests',{**row,'id':str(uuid4()),'idempotency_key':'invalid',**changes})
    for sql in ("UPDATE file_deletion_requests SET reason='changed'",'DELETE FROM file_deletion_requests'):
        with pytest.raises(DBAPIError):
            with database_connection(write=True) as db:
                db.execute(sql)
    with pytest.raises(DBAPIError):
        with migration_connection(config=postgres_migration_config) as db:
            config=alembic_config()
            config.attributes.update(connection=db.raw_connection,database_config=postgres_migration_config)
            command.downgrade(config,'0022_analysis_plans')
    with database_connection() as db:
        assert dict(db.execute('SELECT * FROM file_deletion_requests').fetchone())==row
        assert audit_database(db)['ok']


def test_lifecycle_audit_detects_tampered_snapshot_and_trigger_body(client,postgres_migration_config):
    from tests.api.test_file_lifecycle import lifecycle,assessment
    from app.maintenance.database_audit import audit_database
    _,_,base=lifecycle(client)
    value=assessment(client,base)
    client.post(base+'/lifecycle/deletion-requests',json=dict(reason='retain',expected_assessment_revision=value['assessment_revision']),headers={'Idempotency-Key':'keep'})
    with migration_connection(config=postgres_migration_config,write=True) as db:
        db.execute('ALTER TABLE file_deletion_requests DISABLE TRIGGER file_deletion_requests_scope')
        db.execute("UPDATE file_deletion_requests SET assessment_json=jsonb_set(assessment_json,'{assessment,original_available}','false'::jsonb)")
        db.execute('ALTER TABLE file_deletion_requests ENABLE TRIGGER file_deletion_requests_scope')
    with database_connection() as db:
        audit=audit_database(db)
        assert any(c['column']=='lifecycle_integrity' and c['invalid']==1 for c in audit['data_checks'])
    with migration_connection(config=postgres_migration_config,write=True) as db:
        db.execute('CREATE OR REPLACE FUNCTION enforce_file_lifecycle_scope() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$')
    with database_connection() as db:
        audit=audit_database(db)
        assert any(c['column']=='lifecycle_scope_trigger' and c['invalid']==1 for c in audit['data_checks'])
