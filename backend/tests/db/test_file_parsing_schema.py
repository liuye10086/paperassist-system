"""0014-to-0015 preservation and native constraint checks."""
import json

from alembic import command
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
import pytest

from app.db.database import alembic_config, migration_connection, database_connection
from app.maintenance.database_audit import audit_database
from tests.db.test_task_schema import seed_owner, task_row, insert_row


def test_0015_preserves_every_old_file_value_and_task_snapshot(postgres_schema, postgres_migration_config):
    with migration_connection(config=postgres_migration_config) as db:
        settings = alembic_config()
        settings.attributes.update(connection=db.raw_connection, database_config=postgres_migration_config)
        command.downgrade(settings, '0014_file_assets')
        seed_owner(db)
        db.execute('''INSERT INTO files(id,project_id,filename,file_type,size_bytes,sha256,uploaded_at,
            parse_status,error_json,preview_json,uploader_id,object_key,metadata_revision)
            VALUES ('old','p','same.xlsx','xlsx',3,%s,'2026-10-08T00:00:00Z','parsed',NULL,%s,'u','files/old.xlsx',4)''',
            ('a'*64, json.dumps({'preserved': ['old', 1, None]})))
        old_file = dict(db.execute('SELECT * FROM files').fetchone())
        insert_row(db, 'tasks', task_row(input_snapshot={'schema_version': 1, 'result': {'old': [None, 1]}}))
        old_task = dict(db.execute('SELECT * FROM tasks').fetchone())
        old_indexes = inspect(db.raw_connection).get_indexes('files', schema=postgres_schema.schema)
        command.upgrade(settings, 'head')
        new_file = dict(db.execute('SELECT * FROM files').fetchone())
        assert {key: new_file[key] for key in old_file} == old_file
        assert new_file['parse_revision'] == 0 and new_file['upload_item_id'] is None
        current_task=dict(db.execute('SELECT * FROM tasks').fetchone())
        assert current_task.pop('verification_failure') is None
        assert current_task == old_task
        assert all(index in inspect(db.raw_connection).get_indexes('files', schema=postgres_schema.schema) for index in old_indexes)
        assert db.execute('SELECT count(*) AS n FROM file_parse_results').fetchone()['n'] == 0
        result = audit_database(db)
        assert result['ok'], result['schema_issues']


@pytest.mark.parametrize('status', ['queued', 'parsing', 'parsed', 'failed'])
def test_new_file_states_allowed_and_parse_revision_nonnegative(postgres_schema, status):
    with database_connection(write=True) as db:
        seed_owner(db)
        db.execute('''INSERT INTO files(id,project_id,filename,file_type,size_bytes,sha256,uploaded_at,parse_status,parse_revision)
            VALUES ('f','p','data.xlsx','xlsx',1,%s,'2026-10-08T00:00:00Z',%s,1)''', ('a'*64, status))
        insert_row(db, 'tasks', task_row(task_type='parse_file', workflow_version='parse_file_v1'))
    with pytest.raises(IntegrityError):
        with database_connection(write=True) as db:
            db.execute('UPDATE files SET parse_revision=-1')
    with pytest.raises(IntegrityError):
        with database_connection(write=True) as db:
            db.execute("UPDATE files SET parse_status='unknown'")


def test_parser_record_native_constraints_and_downgrade_preservation(client):
    from tests.domain.test_file_parse_execution import queued
    _, item, _ = queued(client)
    for statement in ("UPDATE file_parse_results SET version=0",
        "UPDATE file_parse_results SET source_sha256='bad'",
        "UPDATE file_parse_results SET settings_json='[]'::jsonb",
        "UPDATE file_parse_results SET result_json='{}'::jsonb",
        "UPDATE file_upload_items SET ordinal=10",
        "UPDATE file_upload_items SET error_json='[]'::jsonb"):
        with pytest.raises(IntegrityError):
            with database_connection(write=True) as db:
                db.execute(statement)


from tests.api.test_projects import client  # noqa: E402,F401
