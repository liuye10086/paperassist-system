"""Additive plot recovery fields keep every accepted source and result intact."""
from alembic import command
import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.db.database import alembic_config, database_connection, migration_connection
from app.maintenance.database_audit import audit_database
from tests.db.test_model_usage_schema import call_row
from tests.db.test_task_schema import seed_owner, insert_row, task_row


def test_plot_recovery_fields_are_nullable_and_figure_fk_is_enforced(postgres_schema):
    with database_connection(write=True) as db:
        inspector = inspect(db.raw_connection)
        columns = {c['name']: c for c in inspector.get_columns('tasks', schema=postgres_schema.schema)}
        assert columns['result_figure_id']['nullable']
        assert columns['figure_candidate']['nullable']
        assert str(columns['figure_candidate']['type']) == 'JSONB'
        assert any(fk['constrained_columns'] == ['result_figure_id'] and fk['referred_table'] == 'figures'
                   for fk in inspector.get_foreign_keys('tasks', schema=postgres_schema.schema))
        model_columns = {c['name']: c for c in inspector.get_columns('model_calls', schema=postgres_schema.schema)}
        assert model_columns['provider_state']['nullable']
        assert str(model_columns['provider_state']['type']) == 'JSONB'
        seed_owner(db)
        insert_row(db, 'tasks', task_row())
        insert_row(db, 'model_calls', call_row())
        assert db.execute("SELECT figure_candidate FROM tasks WHERE id='t'").fetchone()['figure_candidate'] is None
        assert db.execute("SELECT provider_state FROM model_calls WHERE id='call'").fetchone()['provider_state'] is None
        result = audit_database(db)
        assert result['ok'], result
    with pytest.raises(IntegrityError):
        with database_connection(write=True) as db:
            db.execute("UPDATE tasks SET result_figure_id='missing' WHERE id='t'")


@pytest.mark.parametrize('table,column,key', [
    ('tasks', 'figure_candidate', 't'), ('model_calls', 'provider_state', 'call'),
])
def test_plot_recovery_metadata_rejects_nonobjects(postgres_schema, table, column, key):
    with database_connection(write=True) as db:
        seed_owner(db)
        insert_row(db, 'tasks', task_row())
        insert_row(db, 'model_calls', call_row())
    for value in ('[]', 'null', '3'):
        with pytest.raises(IntegrityError):
            with database_connection(write=True) as db:
                db.execute(f'UPDATE {table} SET {column}=%s::jsonb WHERE id=%s', (value, key))
    with database_connection(write=True) as db:
        db.execute(f"UPDATE {table} SET {column}='{{}}'::jsonb WHERE id=%s", (key,))
        assert db.execute(f'SELECT {column} FROM {table} WHERE id=%s', (key,)).fetchone()[column] == {}


def test_0009_upgrade_preserves_all_columns_and_can_reverse(postgres_migration_config):
    with migration_connection(write=True, config=postgres_migration_config) as db:
        settings = alembic_config()
        settings.attributes.update(connection=db.raw_connection, database_config=postgres_migration_config)
        command.downgrade(settings, '0009_explanation_tasks')
        seed_owner(db)
        insert_row(db, 'tasks', task_row())
        insert_row(db, 'model_calls', call_row())
        before = {table: dict(db.execute(f'SELECT * FROM {table}').fetchone())
                  for table in ('tasks', 'model_calls')}
        command.upgrade(settings, 'head')
        command.upgrade(settings, 'head')
        for table, original in before.items():
            current = dict(db.execute(f'SELECT * FROM {table}').fetchone())
            assert {key: current[key] for key in original} == original
        assert db.execute('SELECT result_figure_id,figure_candidate FROM tasks').fetchone() == {
            'result_figure_id': None, 'figure_candidate': None}
        assert db.execute('SELECT provider_state FROM model_calls').fetchone()['provider_state'] is None
        command.downgrade(settings, '0009_explanation_tasks')
        for table, original in before.items():
            assert dict(db.execute(f'SELECT * FROM {table}').fetchone()) == original
        command.upgrade(settings, 'head')
