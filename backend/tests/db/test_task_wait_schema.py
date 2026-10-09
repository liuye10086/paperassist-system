"""Wait records extend 0010 without rewriting task or model history."""
from alembic import command
import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.db.database import SCHEMA_HEAD, alembic_config, database_connection, migration_connection, verify_runtime_permissions
from app.db.schema import metadata
from tests.db.test_task_schema import seed_owner, insert_row, task_row, task_schema, NOW  # noqa: F401


def test_wait_tables_are_native_and_runtime_role_can_access(postgres_schema):
    assert SCHEMA_HEAD == '0013_cost_reconciliation'
    assert {'task_waits', 'task_resume_requests'} <= metadata.tables.keys()
    with database_connection() as db:
        columns = {item['name']: item for item in inspect(db.raw_connection).get_columns('task_waits', schema=postgres_schema.schema)}
        assert str(columns['input_version']['type']) == 'JSONB'
        assert columns['created_at']['type'].timezone
        verify_runtime_permissions(db.raw_connection, postgres_schema)


def test_migration_backfills_only_waiting_tasks_without_rewriting_history(postgres_schema):
    with migration_connection(write=True) as db:
        settings = alembic_config()
        settings.attributes['connection'] = db.raw_connection
        command.downgrade(settings, '0010_boxplot_tasks')
        seed_owner(db)
        for key, status, reason in [('budget', 'waiting_confirmation', 'budget_exceeded'),
                ('unknown', 'waiting_confirmation', 'submission_unknown'), ('input', 'waiting_input', 'input_required'),
                ('confirm', 'waiting_confirmation', 'confirmation_required'), ('done', 'succeeded', None)]:
            insert_row(db, 'tasks', task_row(id=key, idempotency_key=key, status=status, reason_code=reason,
                input_snapshot={'result': {'setup_revision': 1}, 'output_language': 'zh-CN'}))
        before = [dict(row) for row in db.execute('SELECT * FROM tasks ORDER BY id')]
        command.upgrade(settings, 'head')
        upgraded = db.execute('SELECT * FROM tasks ORDER BY id').fetchall()
        assert [{key: row[key] for key in before[0]} for row in upgraded] == before
        assert all(row['retry_count'] == 0 for row in upgraded)
        rows = db.execute('SELECT kind,status FROM task_waits ORDER BY kind').fetchall()
        assert {row['kind'] for row in rows} == {'budget_confirmation', 'submission_unknown', 'unsupported_input', 'unsupported_confirmation'}
        assert all(row['status'] == 'open' for row in rows)
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0
        assert db.execute('SELECT count(*) AS n FROM task_resume_requests').fetchone()['n'] == 0


def wait_row(**changes):
    return {**dict(id='wait', task_id='t', user_id='u', project_id='p', kind='budget_confirmation',
        status='open', task_revision=1, input_version={'setup_revision': 1, 'output_language': 'zh-CN'},
        reason_code='budget_exceeded', error_code=None, created_at=NOW), **changes}


@pytest.mark.parametrize('changes', [{'kind': 'arbitrary'}, {'status': 'accepted'}, {'task_revision': 0},
    {'input_version': []}, {'task_id': 'missing'}, {'status': 'resolved'},
    {'status': 'superseded', 'resolved_at': NOW},
    {'status': 'resolved', 'resolved_at': NOW, 'resolved_task_revision': 1}])
def test_wait_constraints_reject_invalid_or_incomplete_resolutions(task_schema, changes):
    with pytest.raises(IntegrityError):
        with database_connection(write=True) as db:
            insert_row(db, 'task_waits', wait_row(**changes))


def test_only_one_open_wait_per_task_and_generation_is_unique(task_schema):
    with database_connection(write=True) as db:
        insert_row(db, 'task_waits', wait_row())
    for values in [wait_row(id='other', task_revision=2), wait_row(id='same-generation')]:
        with pytest.raises(IntegrityError):
            with database_connection(write=True) as db:
                insert_row(db, 'task_waits', values)


def resume_row(**changes):
    return {**dict(id='resume', task_id='t', user_id='u', operation='resume', wait_id='wait',
        idempotency_key='key', request_digest='a' * 64, expected_task_revision=1,
        input_version={'setup_revision': 1, 'output_language': 'zh-CN'}, result_task_revision=2,
        response_json={'id': 't', 'revision': 2}, created_at=NOW), **changes}


@pytest.mark.parametrize('changes', [{'operation': 'arbitrary'}, {'operation': 'retry'}, {'wait_id': None},
    {'idempotency_key': ''}, {'idempotency_key': 'has space'}, {'idempotency_key': '中文'},
    {'request_digest': 'invalid'}, {'expected_task_revision': 0}, {'result_task_revision': 1},
    {'input_version': []}, {'response_json': []}, {'wait_id': 'missing'}])
def test_resume_constraints_reject_invalid_receipts(task_schema, changes):
    with database_connection(write=True) as db:
        insert_row(db, 'task_waits', wait_row())
    with pytest.raises(IntegrityError):
        with database_connection(write=True) as db:
            insert_row(db, 'task_resume_requests', resume_row(**changes))


def test_receipt_key_unique_and_wait_must_belong_to_same_task(task_schema):
    with database_connection(write=True) as db:
        insert_row(db, 'task_waits', wait_row())
        insert_row(db, 'task_resume_requests', resume_row())
        insert_row(db, 'tasks', task_row(id='second', idempotency_key='second'))
    for changes in [{'id': 'duplicate'}, {'id': 'wrong-task', 'task_id': 'second'}]:
        with pytest.raises(IntegrityError):
            with database_connection(write=True) as db:
                insert_row(db, 'task_resume_requests', resume_row(**changes))
