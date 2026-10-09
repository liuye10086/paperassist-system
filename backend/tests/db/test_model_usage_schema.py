"""Model budget migration and constraints use disposable PostgreSQL schemas."""
from datetime import datetime, timezone

from alembic import command
import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.db.database import SCHEMA_HEAD, alembic_config, database_connection, migration_connection
from app.db.schema import metadata
from app.maintenance.database_audit import audit_database
from tests.db.test_task_schema import seed_owner, insert_row, task_row


TABLES = {'model_calls', 'usage_events', 'model_budgets', 'budget_reservations'}
NOW = datetime(2026, 10, 8, tzinfo=timezone.utc)


def budget_row(**changes):
    return dict(id='budget', user_id='u', scope_type='user', scope_key='u',
                project_id=None, task_id=None, limit_micro_usd=1_000_000,
                revision=1, created_at=NOW, updated_at=NOW, **changes)


def call_row(**changes):
    row = dict(id='call', user_id='u', project_id='p', task_id='t', attempt_no=1,
               call_key='explain', input_digest='a' * 64, provider='openai', model='test-model',
               policy_snapshot={}, price_snapshot={}, status='reserved', provider_status=None,
               provider_request_id=None, provider_response_id=None, error_code=None,
               estimated_cost_micro_usd=None, usage_status='pending', created_at=NOW, updated_at=NOW)
    return {**row, **changes}


@pytest.fixture
def model_rows(postgres_schema):
    with database_connection(write=True) as db:
        seed_owner(db)
        insert_row(db, 'tasks', task_row())
        insert_row(db, 'model_budgets', budget_row())
        insert_row(db, 'model_calls', call_row())
    return postgres_schema


def test_model_usage_migration_has_native_snapshots_and_matches_audit(postgres_schema):
    assert TABLES <= metadata.tables.keys()
    assert SCHEMA_HEAD == '0013_cost_reconciliation'
    with database_connection() as db:
        inspector = inspect(db.raw_connection)
        assert TABLES <= set(inspector.get_table_names(schema=postgres_schema.schema))
        columns = {item['name']: item for item in inspector.get_columns('model_calls', schema=postgres_schema.schema)}
        assert str(columns['price_snapshot']['type']) == 'JSONB'
        assert columns['created_at']['type'].timezone is True
        result = audit_database(db)
    assert result['ok'], {key: value for key, value in result.items() if key not in ('data_checks', 'compatibility')}


def test_0007_upgrade_preserves_all_original_table_values(postgres_schema, postgres_migration_config):
    with migration_connection(write=True, config=postgres_migration_config) as db:
        settings = alembic_config()
        settings.attributes.update(connection=db.raw_connection, database_config=postgres_migration_config)
        command.downgrade(settings, '0007_task_execution')
        seed_owner(db)
        insert_row(db, 'tasks', task_row())
        old_tables = inspect(db.raw_connection).get_table_names(schema=postgres_schema.schema)
        old_tables = [name for name in old_tables if name != 'alembic_version']
        assert len(old_tables) == 19
        before = {name: [dict(row) for row in db.execute(f'SELECT * FROM "{name}" ORDER BY 1').fetchall()]
                  for name in old_tables}
        command.upgrade(settings, '0008_model_usage')
        command.upgrade(settings, '0008_model_usage')
        for name in old_tables:
            assert [dict(row) for row in db.execute(f'SELECT * FROM "{name}" ORDER BY 1').fetchall()] == before[name]
        command.downgrade(settings, '0007_task_execution')
        assert TABLES.isdisjoint(inspect(db.raw_connection).get_table_names(schema=postgres_schema.schema))
        command.upgrade(settings, 'head')


@pytest.mark.parametrize('changes', [
    {'scope_type': 'project', 'scope_key': 'p'},
    {'scope_type': 'user', 'scope_key': 'other'},
    {'scope_type': 'task', 'scope_key': 't', 'task_id': 't'},
    {'limit_micro_usd': -1}, {'limit_micro_usd': 1_000_000_000_001}, {'revision': 0},
])
def test_budgets_reject_bad_scope_or_amount(model_rows, changes):
    row = {**budget_row(), 'id': 'bad', **changes}
    with pytest.raises(IntegrityError):
        with database_connection(write=True) as db:
            insert_row(db, 'model_budgets', row)


@pytest.mark.parametrize('changes', [
    {'status': 'unknown-invalid'}, {'usage_status': 'free'},
    {'estimated_cost_micro_usd': -1}, {'input_digest': 'short'},
    {'price_snapshot': []}, {'task_id': 'missing'},
])
def test_calls_reject_invalid_or_unrelated_rows(model_rows, changes):
    with pytest.raises(IntegrityError):
        with database_connection(write=True) as db:
            insert_row(db, 'model_calls', call_row(id='bad', call_key='new', **changes))


def test_call_and_observation_idempotency_have_database_constraints(model_rows):
    with pytest.raises(IntegrityError):
        with database_connection(write=True) as db:
            insert_row(db, 'model_calls', call_row(id='duplicate'))
    event = dict(id='event', call_id='call', event_key='response-final', event_digest='b' * 64,
                 event_type='observation', provider_usage=None, price_snapshot={},
                 estimated_cost_micro_usd=None, usage_status='pending', reason_code=None, created_at=NOW)
    with database_connection(write=True) as db:
        insert_row(db, 'usage_events', event)
        insert_row(db, 'budget_reservations', dict(call_id='call', budget_id='budget', reserved_micro_usd=300,
                                                  accounted_micro_usd=0, status='held', updated_at=NOW))
    for table, row in [('usage_events', {**event, 'id': 'event2'}),
                       ('budget_reservations', dict(call_id='call', budget_id='budget', reserved_micro_usd=300,
                                                   accounted_micro_usd=0, status='held', updated_at=NOW))]:
        with pytest.raises(IntegrityError):
            with database_connection(write=True) as db:
                insert_row(db, table, row)
