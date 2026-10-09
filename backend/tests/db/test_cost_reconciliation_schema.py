"""Additive migration and evidence constraints in disposable schemas."""
from alembic import command
import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.db.database import alembic_config, database_connection, migration_connection
from app.maintenance.database_audit import audit_database
from tests.db.test_model_usage_schema import model_rows, call_row, NOW  # noqa: F401
from tests.db.test_task_schema import seed_owner, insert_row, task_row


def test_0013_round_trip_preserves_old_columns_and_indexes(postgres_schema, postgres_migration_config):
    with migration_connection(write=True, config=postgres_migration_config) as db:
        settings = alembic_config()
        settings.attributes.update(connection=db.raw_connection, database_config=postgres_migration_config)
        command.downgrade(settings, '0012_task_errors')
        seed_owner(db)
        insert_row(db, 'tasks', task_row())
        insert_row(db, 'model_calls', call_row())
        tables = inspect(db.raw_connection).get_table_names(schema=postgres_schema.schema)
        tables.remove('alembic_version')
        columns = {table: [column['name'] for column in inspect(db.raw_connection).get_columns(table, schema=postgres_schema.schema)] for table in tables}
        before = {table: [dict(row) for row in db.execute('SELECT * FROM "' + table + '" ORDER BY 1').fetchall()] for table in tables}
        indexes = {table: inspect(db.raw_connection).get_indexes(table, schema=postgres_schema.schema) for table in tables}
        command.upgrade(settings, 'head')
        for table in tables:
            assert [dict(row) for row in db.execute('SELECT ' + ','.join('"' + col + '"' for col in columns[table]) + ' FROM "' + table + '" ORDER BY 1').fetchall()] == before[table]
            assert inspect(db.raw_connection).get_indexes(table, schema=postgres_schema.schema) == indexes[table]
        call = db.execute('SELECT * FROM model_calls').fetchone()
        assert call['actual_token_micro_usd'] is None and call['actual_tool_micro_usd'] is None and call['reconciliation_revision'] == 0
        audit = audit_database(db)
        assert audit['ok'], {key: value for key, value in audit.items() if key not in ('data_checks', 'compatibility')}
        command.downgrade(settings, '0012_task_errors')
        for table in tables:
            assert [dict(row) for row in db.execute('SELECT * FROM "' + table + '" ORDER BY 1').fetchall()] == before[table]
        command.upgrade(settings, 'head')


@pytest.mark.parametrize('changes', [{'actual_token_micro_usd': -1}, {'actual_tool_micro_usd': -1}, {'reconciliation_revision': -1}])
def test_actual_fields_reject_invalid_values(model_rows, changes):
    with pytest.raises(IntegrityError):
        with database_connection(write=True) as db:
            insert_row(db, 'model_calls', call_row(id='bad', call_key='bad', **changes))


@pytest.mark.parametrize('kind,payload', [('reconciliation', None), ('reconciliation', {}), ('observation', {}), ('reconciliation', [])])
def test_evidence_shape_is_constrained(model_rows, kind, payload):
    with pytest.raises(IntegrityError):
        with database_connection(write=True) as db:
            insert_row(db, 'usage_events', dict(id='event', call_id='call', event_key='bad', event_digest='b' * 64,
                event_type=kind, reconciliation=payload, provider_usage=None, price_snapshot={}, estimated_cost_micro_usd=None,
                usage_status='pending', reason_code=None, created_at=NOW))


def test_empty_evidence_request_and_receipt_are_rejected(model_rows):
    payload = dict(request={}, receipt={}, operator='admin', revision=1,
        previous_actual_micro_usd={}, actual_micro_usd={}, accounted_before_micro_usd=0,
        accounted_after_micro_usd=0, delta_micro_usd=0)
    with pytest.raises(IntegrityError):
        with database_connection(write=True) as db:
            insert_row(db, 'usage_events', dict(id='event', call_id='call', event_key='bad', event_digest='b' * 64,
                event_type='reconciliation', reconciliation=payload, provider_usage=None, price_snapshot={},
                estimated_cost_micro_usd=None, usage_status='pending', reason_code=None, created_at=NOW))
