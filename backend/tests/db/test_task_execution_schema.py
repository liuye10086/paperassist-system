"""Execution additions preserve the accepted task contract and old records."""
from alembic import command
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
import pytest

from app.db.database import SCHEMA_HEAD, alembic_config, database_connection, migration_connection
from app.db.schema import metadata
from app.maintenance.database_audit import audit_database
from tests.db.test_task_schema import seed_owner, insert_row, task_row


def test_execution_schema_has_report_reference_and_lease_index(postgres_schema):
    assert SCHEMA_HEAD == '0011_task_waits'
    with database_connection() as db:
        inspector = inspect(db.raw_connection)
        columns = {column['name']: column for column in inspector.get_columns('tasks', schema=postgres_schema.schema)}
        assert columns['result_report_id']['nullable']
        assert columns['error_code']['nullable']
        assert any(fk['constrained_columns'] == ['result_report_id'] and fk['referred_table'] == 'reports'
                   for fk in inspector.get_foreign_keys('tasks', schema=postgres_schema.schema))
        assert any(index['column_names'] == ['status', 'lease_expires_at']
                   for index in inspector.get_indexes('task_attempts', schema=postgres_schema.schema))
        result = audit_database(db)
    assert result['ok'], result


def test_result_reference_requires_existing_report(postgres_schema):
    with database_connection(write=True) as db:
        seed_owner(db)
    with pytest.raises(IntegrityError):
        with database_connection(write=True) as db:
            insert_row(db, 'tasks', task_row(result_report_id='missing'))


def test_0006_upgrade_preserves_task_values_and_downgrade(postgres_schema, postgres_migration_config):
    with migration_connection(write=True, config=postgres_migration_config) as db:
        settings = alembic_config()
        settings.attributes.update(connection=db.raw_connection, database_config=postgres_migration_config)
        command.downgrade(settings, '0006_unified_tasks')
        seed_owner(db)
        # Frozen 0006 does not yet have application metadata's new columns.
        row = task_row()
        from psycopg.types.json import Jsonb
        db.execute('INSERT INTO tasks (' + ','.join(row) + ') VALUES (' + ','.join(['%s'] * len(row)) + ')',
                   tuple(Jsonb(value) if key == 'input_snapshot' else value for key, value in row.items()))
        before = dict(db.execute("SELECT * FROM tasks WHERE id='t'").fetchone())
        command.upgrade(settings, 'head')
        after = dict(db.execute("SELECT * FROM tasks WHERE id='t'").fetchone())
        assert {key: after[key] for key in before} == before
        assert after['result_report_id'] is None and after['error_code'] is None
        command.downgrade(settings, '0006_unified_tasks')
        assert dict(db.execute("SELECT * FROM tasks WHERE id='t'").fetchone()) == before
        command.upgrade(settings, 'head')
