"""Unified-task persistence contract, exercised only in the disposable test schema."""
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.db.database import (
    SCHEMA_HEAD, alembic_config, database_connection, migration_connection,
    verify_runtime_permissions,
)
from app.db.schema import metadata
from app.maintenance.database_audit import audit_database


TASK_TABLES = {'tasks', 'task_attempts', 'task_events', 'task_outbox'}
NOW = datetime(2026, 10, 8, tzinfo=timezone.utc)


def seed_owner(db):
    db.execute("INSERT INTO users(id,email,password_hash,role,active,created_at,updated_at) VALUES ('u','u@example.invalid','unused','user',true,1,1)")
    db.execute("INSERT INTO projects(id,name,research_topic,project_type,created_at,updated_at,owner_id) VALUES ('p','name','topic','sci','2026-10-08T00:00:00Z','2026-10-08T00:00:00Z','u')")


def task_row(**changes):
    row = dict(id='t', project_id='p', user_id='u', task_type='boxplot',
               idempotency_key='key', input_digest='a' * 64, input_snapshot={},
               workflow_version='v1', status='queued', phase='parse', revision=1,
               current_attempt=0, reason_code=None, created_at=NOW, updated_at=NOW)
    return {**row, **changes}


def insert_row(db, table, values):
    db.raw_connection.execute(metadata.tables[table].insert(), values)


@pytest.fixture
def task_schema(postgres_schema):
    with database_connection(write=True) as db:
        seed_owner(db)
        insert_row(db, 'tasks', task_row())
    return postgres_schema


def test_four_task_tables_have_current_head_and_native_types(postgres_schema):
    assert TASK_TABLES <= metadata.tables.keys()
    assert SCHEMA_HEAD == '0011_task_waits'
    with database_connection() as db:
        inspector = inspect(db.raw_connection)
        assert TASK_TABLES <= set(inspector.get_table_names(schema=postgres_schema.schema))
        columns = {c['name']: c for c in inspector.get_columns('tasks', schema=postgres_schema.schema)}
        assert str(columns['input_snapshot']['type']) == 'JSONB'
        assert columns['created_at']['type'].timezone is True
        assert columns['updated_at']['type'].timezone is True
        result = audit_database(db)
    assert result['ok'], result


@pytest.mark.parametrize('changes', [
    {'task_type': 'arbitrary'}, {'status': 'cancelled'}, {'phase': 'other'},
    {'reason_code': 'private exception'}, {'revision': 0}, {'current_attempt': -1},
    {'idempotency_key': ''}, {'idempotency_key': 'x' * 129},
    {'input_digest': 'A' * 64}, {'input_digest': 'a' * 63},
    {'workflow_version': ''}, {'input_snapshot': []},
    {'updated_at': datetime(2026, 10, 7, tzinfo=timezone.utc)},
    {'project_id': 'missing'}, {'user_id': 'missing'},
])
def test_tasks_reject_invalid_values(task_schema, changes):
    with pytest.raises(IntegrityError):
        with database_connection(write=True) as db:
            insert_row(db, 'tasks', task_row(**{'id': 'invalid', 'idempotency_key': 'new', **changes}))


def test_idempotency_key_is_scoped_to_owner_project_type(task_schema):
    with pytest.raises(IntegrityError):
        with database_connection(write=True) as db:
            insert_row(db, 'tasks', task_row(id='duplicate'))
    with database_connection(write=True) as db:
        insert_row(db, 'tasks', task_row(id='other-type', task_type='explanation'))


@pytest.mark.parametrize('table,values', [
    ('task_attempts', dict(id='a', task_id='t', attempt_no=0, status='running', started_at=NOW)),
    ('task_attempts', dict(id='a', task_id='t', attempt_no=1, status='queued', started_at=NOW)),
    ('task_attempts', dict(id='a', task_id='t', attempt_no=1, status='running', started_at=NOW, finished_at=NOW)),
    ('task_attempts', dict(id='a', task_id='t', attempt_no=1, status='failed', started_at=NOW)),
    ('task_attempts', dict(id='a', task_id='t', attempt_no=1, status='failed', started_at=NOW, finished_at=datetime(2026, 10, 7, tzinfo=timezone.utc))),
    ('task_attempts', dict(id='a', task_id='t', attempt_no=1, status='running', started_at=NOW, reason_code='raw detail')),
    ('task_events', dict(task_id='t', seq=0, task_revision=0, event_type='created', status='queued', phase='parse', created_at=NOW)),
    ('task_events', dict(task_id='t', seq=2, task_revision=1, event_type='created', status='queued', phase='parse', created_at=NOW)),
    ('task_events', dict(task_id='t', seq=1, task_revision=1, event_type='unknown', status='queued', phase='parse', created_at=NOW)),
    ('task_events', dict(task_id='t', seq=1, task_revision=1, event_type='created', status='unknown', phase='parse', created_at=NOW)),
    ('task_events', dict(task_id='t', seq=1, task_revision=1, event_type='created', status='queued', phase='unknown', created_at=NOW)),
    ('task_events', dict(task_id='t', seq=1, task_revision=1, event_type='created', status='queued', phase='parse', reason_code='raw detail', created_at=NOW)),
    ('task_outbox', dict(id='o', task_id='t', task_revision=0, event_type='task_ready', available_at=NOW, created_at=NOW, publish_attempts=0)),
    ('task_outbox', dict(id='o', task_id='t', task_revision=1, event_type='unknown', available_at=NOW, created_at=NOW, publish_attempts=0)),
    ('task_outbox', dict(id='o', task_id='t', task_revision=1, event_type='task_ready', available_at=NOW, created_at=NOW, publish_attempts=-1)),
])
def test_task_children_reject_invalid_values(task_schema, table, values):
    with pytest.raises(IntegrityError):
        with database_connection(write=True) as db:
            insert_row(db, table, values)


def test_task_children_unique_keys_and_foreign_keys(task_schema):
    rows = {
        'task_attempts': dict(id='a', task_id='t', attempt_no=1, status='running', started_at=NOW),
        'task_events': dict(task_id='t', seq=1, task_revision=1, event_type='created', status='queued', phase='parse', created_at=NOW),
        'task_outbox': dict(id='o', task_id='t', task_revision=1, event_type='task_ready', available_at=NOW, created_at=NOW, publish_attempts=0),
    }
    with database_connection(write=True) as db:
        for table, row in rows.items():
            insert_row(db, table, row)
    for table, row in rows.items():
        orphan = {'task_id': 'missing', **({'id': 'orphan'} if 'id' in row else {})}
        for changes in ({'id': 'duplicate'} if 'id' in row else {}, orphan):
            with pytest.raises(IntegrityError):
                with database_connection(write=True) as db:
                    insert_row(db, table, {**row, **changes})
    with pytest.raises(IntegrityError):
        with database_connection(write=True) as db:
            db.execute("DELETE FROM tasks WHERE id='t'")
    with database_connection() as db:
        result = audit_database(db)
    assert result['ok'], result


def test_event_sequence_is_per_task_and_creates_no_global_sequence(task_schema):
    event = dict(seq=1, task_revision=1, event_type='created', status='queued', phase='parse', created_at=NOW)
    with database_connection(write=True) as db:
        insert_row(db, 'tasks', task_row(id='second', idempotency_key='second'))
        insert_row(db, 'task_events', {'task_id': 't', **event})
        insert_row(db, 'task_events', {'task_id': 'second', **event})
        assert db.execute('SELECT count(*) AS total FROM task_events WHERE seq=1').fetchone()['total'] == 2
        sequences = inspect(db.raw_connection).get_sequence_names(schema=task_schema.schema)
        assert not any(name.startswith('task') for name in sequences)


def test_task_runtime_has_dml_but_no_ddl_or_administrative_rights(task_schema):
    with database_connection(write=True) as db:
        verify_runtime_permissions(db.raw_connection, db.config)
        db.execute("UPDATE tasks SET workflow_version='v2' WHERE id='t'")
        assert db.execute("SELECT workflow_version FROM tasks WHERE id='t'").fetchone()['workflow_version'] == 'v2'
        db.execute("DELETE FROM tasks WHERE id='t'")
    for statement in ('ALTER TABLE tasks ADD COLUMN probe TEXT', 'DROP TABLE tasks', 'TRUNCATE task_outbox'):
        with pytest.raises(SQLAlchemyError):
            with database_connection(write=True) as db:
                db.execute(statement)


def test_0005_0006_roundtrip_preserves_old_columns_and_values(postgres_schema, postgres_migration_config):
    with migration_connection(write=True, config=postgres_migration_config) as db:
        settings = alembic_config()
        settings.attributes.update(connection=db.raw_connection, database_config=postgres_migration_config)
        command.downgrade(settings, '0005_ownership_indexes')
        seed_owner(db)
        db.execute("UPDATE projects SET created_at='legacy exact text', updated_at='2026-10-08T00:00:00.123456Z'")
        db.execute("INSERT INTO files(id,project_id,filename,file_type,size_bytes,sha256,uploaded_at,parse_status) VALUES ('f','p','original.csv','csv',1,'hash','2026-10-08T00:00:00Z','parsed')")
        db.execute("INSERT INTO analysis_setups(file_id,revision,setup_json) VALUES ('f',1,'{\"spacing\":  true}')")
        db.execute("INSERT INTO analysis_runs(id,file_id,setup_revision,engine_version,completed_at,result_json) VALUES ('r','f',1,'original','2026-10-08T00:00:00Z','{}')")
        db.execute("INSERT INTO figures(id,analysis_run_id,renderer_version,figure_json) VALUES ('fig','r','original','{}')")
        db.execute("INSERT INTO figure_jobs(id,analysis_run_id,renderer_version,created_at,job_json) VALUES ('fj','r','original','2026-10-08T00:00:00Z','{\"unchanged\": true}')")
        db.execute("INSERT INTO explanations(id,analysis_run_id,figure_id,engine_version,explanation_json) VALUES ('exp','r','fig','original','{}')")
        db.execute("INSERT INTO explanation_jobs(id,analysis_run_id,figure_id,engine_version,created_at,job_json) VALUES ('ej','r','fig','original','2026-10-08T00:00:00Z','{}')")
        db.execute("INSERT INTO reports(id,analysis_run_id,explanation_id,renderer_version,report_json,input_json) VALUES ('rep','r','exp','original','{}','{\"spacing\":  true}')")
        old_tables = set(inspect(db.raw_connection).get_table_names(schema=postgres_schema.schema)) - {'alembic_version'}
        before = {name: [dict(row) for row in db.execute(f'SELECT * FROM "{name}"')] for name in old_tables}
        before_columns = {name: [(c['name'], str(c['type']), c['nullable'], c.get('default')) for c in inspect(db.raw_connection).get_columns(name, schema=postgres_schema.schema)] for name in old_tables}
        command.upgrade(settings, '0006_unified_tasks')
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()['version_num'] == '0006_unified_tasks'
        for name in old_tables:
            assert [dict(row) for row in db.execute(f'SELECT * FROM "{name}"')] == before[name]
            assert [(c['name'], str(c['type']), c['nullable'], c.get('default')) for c in inspect(db.raw_connection).get_columns(name, schema=postgres_schema.schema)] == before_columns[name]
        for name in TASK_TABLES:
            assert db.execute(f'SELECT count(*) AS total FROM "{name}"').fetchone()['total'] == 0
        command.downgrade(settings, '0005_ownership_indexes')
        assert not TASK_TABLES & set(inspect(db.raw_connection).get_table_names(schema=postgres_schema.schema))
        for name in old_tables:
            assert [dict(row) for row in db.execute(f'SELECT * FROM "{name}"')] == before[name]
        command.upgrade(settings, 'head')


def test_migration_is_frozen_and_has_no_current_metadata_dependency(postgres_schema):
    path = Path(__file__).resolve().parents[2] / 'alembic' / 'versions' / '0006_unified_tasks.py'
    assert path.is_file()
    import ast
    tree = ast.parse(path.read_text(encoding='utf-8'))
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(name and name.startswith('app') for name in imports)
    assert not any(isinstance(node, ast.Attribute) and node.attr in {'create_all', 'drop_all'} for node in ast.walk(tree))
