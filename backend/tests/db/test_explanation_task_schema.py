"""Explanation execution schema remains additive and preserves accepted records."""
from alembic import command
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
import pytest

from app.db.database import alembic_config, database_connection, migration_connection
from app.maintenance.database_audit import audit_database
from tests.db.test_task_schema import seed_owner, insert_row, task_row


def test_explanation_result_fk_and_deferred_event(postgres_schema):
    with database_connection(write=True) as db:
        inspector = inspect(db.raw_connection)
        columns = {column['name']: column for column in inspector.get_columns('tasks', schema=postgres_schema.schema)}
        assert columns['result_explanation_id']['nullable']
        assert any(fk['constrained_columns'] == ['result_explanation_id'] and fk['referred_table'] == 'explanations'
                   for fk in inspector.get_foreign_keys('tasks', schema=postgres_schema.schema))
        seed_owner(db)
        task = task_row()
        insert_row(db, 'tasks', task)
        db.execute("""INSERT INTO task_events(task_id,seq,task_revision,event_type,status,phase,created_at)
            VALUES ('t',1,1,'deferred','running','interpret',%s)""", (task['created_at'],))
        result = audit_database(db)
        assert result['ok'], result


def test_explanation_reference_rejects_missing_product(postgres_schema):
    with database_connection(write=True) as db:
        seed_owner(db)
    with pytest.raises(IntegrityError):
        with database_connection(write=True) as db:
            insert_row(db, 'tasks', task_row(result_explanation_id='missing'))


def test_0008_upgrade_preserves_records_and_reverses(postgres_migration_config):
    with migration_connection(write=True, config=postgres_migration_config) as db:
        settings = alembic_config()
        settings.attributes.update(connection=db.raw_connection, database_config=postgres_migration_config)
        command.downgrade(settings, '0008_model_usage')
        seed_owner(db)
        insert_row(db, 'tasks', task_row())
        before = dict(db.execute("SELECT * FROM tasks WHERE id='t'").fetchone())
        command.upgrade(settings, 'head')
        after = dict(db.execute("SELECT * FROM tasks WHERE id='t'").fetchone())
        assert {key: after[key] for key in before} == before
        assert after['result_explanation_id'] is None
        command.downgrade(settings, '0008_model_usage')
        assert dict(db.execute("SELECT * FROM tasks WHERE id='t'").fetchone()) == before
        command.upgrade(settings, 'head')
