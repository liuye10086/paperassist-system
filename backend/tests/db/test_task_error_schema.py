from alembic import command
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
import pytest

from app.db.database import SCHEMA_HEAD, alembic_config, database_connection, migration_connection
from tests.db.test_task_schema import seed_owner, task_row, insert_row, NOW


def test_incremental_upgrade_keeps_old_history_null_and_downgrades(postgres_schema, postgres_migration_config):
    assert SCHEMA_HEAD == '0013_cost_reconciliation'
    with migration_connection(write=True, config=postgres_migration_config) as db:
        settings = alembic_config()
        settings.attributes.update(connection=db.raw_connection, database_config=postgres_migration_config)
        command.downgrade(settings, '0011_task_waits')
        seed_owner(db)
        from psycopg.types.json import Jsonb
        row = task_row(status='failed', current_attempt=1, reason_code='execution_failed')
        db.execute('INSERT INTO tasks (' + ','.join(row) + ') VALUES (' + ','.join(['%s'] * len(row)) + ')',
            tuple(Jsonb(value) if key == 'input_snapshot' else value for key, value in row.items()))
        db.execute("UPDATE tasks SET error_code='plot_invalid_result'")
        db.execute("INSERT INTO task_attempts(id,task_id,attempt_no,status,started_at,finished_at,reason_code) VALUES ('a','t',1,'failed',%s,%s,'execution_failed')", (NOW, NOW))
        db.execute("INSERT INTO task_events(task_id,seq,task_revision,event_type,status,phase,reason_code,created_at) VALUES ('t',1,1,'failed','failed','parse','execution_failed',%s)", (NOW,))
        before = {table: dict(db.execute('SELECT * FROM ' + table).fetchone()) for table in ('tasks', 'task_attempts', 'task_events')}
        command.upgrade(settings, 'head')
        assert db.execute('SELECT retry_count FROM tasks').fetchone()['retry_count'] == 0
        for table in ('task_attempts', 'task_events'):
            history = db.execute('SELECT * FROM ' + table).fetchone()
            assert all(history[key] is None for key in ('error_code', 'error_category', 'retry_reason'))
        command.downgrade(settings, '0011_task_waits')
        for table in before:
            assert dict(db.execute('SELECT * FROM ' + table).fetchone()) == before[table]
        command.upgrade(settings, 'head')


@pytest.mark.parametrize('count', [-1, 4])
def test_retry_count_is_bounded(postgres_schema, count):
    with database_connection(write=True) as db:
        seed_owner(db)
    with pytest.raises(IntegrityError):
        with database_connection(write=True) as db:
            insert_row(db, 'tasks', task_row(retry_count=count))
