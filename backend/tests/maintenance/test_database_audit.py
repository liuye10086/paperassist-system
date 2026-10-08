import json
from datetime import datetime, timedelta, timezone
import pytest
from app.maintenance.database_audit import valid_json, valid_timestamp, valid_numeric_time, audit_database, main

@pytest.mark.parametrize('value,expected', [('{}', True), ('null', True), ('{"x":NaN}', False), ('Infinity', False), ('{', False)])
def test_json(value, expected):
    assert valid_json(value) == expected

@pytest.mark.parametrize('value,expected', [('2026-10-05T01:02:03Z', True), ('2026-10-05T01:02:03.123456+00:00', True), ('2026-10-05', False), ('2026-10-05T01:02:03+08:00', False), ('2026-10-05T01:02:03.1234567Z', False)])
def test_timestamp(value, expected):
    assert valid_timestamp(value) == expected

def test_numeric_time():
    assert valid_numeric_time(123.123456789)
    assert not valid_numeric_time(float('nan'))
    assert not valid_numeric_time(float('inf'))


@pytest.mark.parametrize('value,expected', [
    (datetime(2026, 10, 8, tzinfo=timezone.utc), True),
    (datetime(2026, 10, 8, tzinfo=timezone(timedelta(hours=8))), True),
    (datetime(2026, 10, 8), False),
    ('2026-10-08T00:00:00Z', False),
])
def test_native_datetime_keeps_legacy_text_validation_separate(value, expected):
    from app.maintenance import database_audit
    assert database_audit.valid_datetime(value) is expected
    if isinstance(value, datetime):
        assert not valid_timestamp(value)
    else:
        assert valid_timestamp(value)

def test_clean_schema(postgres_schema):
    from app.db.database import database_connection
    with database_connection(config=postgres_schema) as db:
        result = audit_database(db)
    assert result['ok'], result
    assert len(result['data_checks']) == 50

def test_cli_failure_is_safe(monkeypatch, capsys):
    import app.maintenance.database_audit as module
    def fail():
        raise RuntimeError('secret password and row payload')
    monkeypatch.setattr(module, 'get_database_config', fail)
    assert main() == 1
    output = capsys.readouterr()
    assert 'secret' not in output.err + output.out

def test_audit_bad_values_and_readonly(postgres_schema):
    from app.db.database import database_connection
    from sqlalchemy.exc import SQLAlchemyError
    with database_connection(write=True, config=postgres_schema) as db:
        db.execute("INSERT INTO projects(id,name,research_topic,project_type,created_at,updated_at) VALUES ('private-row','hidden business','topic','sci','invalid','2026-10-05T00:00:00Z')")
        db.execute("INSERT INTO files(id,project_id,filename,file_type,size_bytes,sha256,uploaded_at,parse_status,error_json) VALUES ('f','private-row','hidden filename','csv',1,'hash','2026-10-05T00:00:00Z','parsed','NaN')")
    with database_connection(config=postgres_schema) as db:
        result = audit_database(db)
    assert not result['ok']
    counts = {(c['table'], c['column']): c['invalid'] for c in result['data_checks']}
    assert counts['projects', 'created_at'] == 1
    assert counts['files', 'error_json'] == 1
    assert 'hidden' not in json.dumps(result)
    with pytest.raises(SQLAlchemyError):
        with database_connection(config=postgres_schema) as db:
            db.execute('DELETE FROM projects')

def test_detect_index_sort_drift(postgres_schema, postgres_migration_config):
    from app.db.database import database_connection, migration_connection
    with migration_connection(write=True, config=postgres_migration_config) as db:
        db.execute('DROP INDEX projects_owner_updated')
        db.execute('CREATE INDEX projects_owner_updated ON projects(owner_id,updated_at ASC,id ASC)')
    with database_connection(config=postgres_schema) as db:
        result = audit_database(db)
    assert {'table': 'projects', 'kind': 'index:projects_owner_updated'} in result['schema_issues']


@pytest.mark.parametrize('expected_predicate,actual_predicate,valid', [
    ('active = true', 'active = true', True),
    ('active = true', 'active = false', False),
    ('active = true', None, False),
    (None, 'active = true', False),
])
def test_partial_index_predicate_is_audited_against_metadata(
        postgres_schema, postgres_migration_config, expected_predicate, actual_predicate, valid):
    """An intended partial index must pass, while a changed/removed filter must fail."""
    from app.db.database import database_connection, migration_connection
    from app.db.schema import metadata
    from sqlalchemy import Index, text
    table = metadata.tables['users']
    index = Index('users_active_email_audit_probe', table.c.email, unique=True,
                  postgresql_where=text(expected_predicate) if expected_predicate else None)
    try:
        with migration_connection(write=True, config=postgres_migration_config) as db:
            suffix = ' WHERE ' + actual_predicate if actual_predicate else ''
            db.execute('CREATE UNIQUE INDEX users_active_email_audit_probe ON users(email)' + suffix)
        with database_connection(config=postgres_schema) as db:
            result = audit_database(db)
        assert result['ok'] is valid, result
        issue = {'table': 'users', 'kind': 'index:users_active_email_audit_probe'}
        assert (issue in result['schema_issues']) is not valid
    finally:
        table.indexes.remove(index)


def test_wait_audit_accepts_native_response_json_and_keeps_values_private(postgres_schema):
    from app.db.database import database_connection
    from tests.db.test_task_schema import seed_owner, insert_row, task_row, NOW
    version = {'setup_revision': 1, 'output_language': 'zh-CN'}
    with database_connection(write=True, config=postgres_schema) as db:
        seed_owner(db)
        insert_row(db, 'tasks', task_row(revision=2))
        insert_row(db, 'task_waits', dict(
            id='wait', task_id='t', user_id='u', project_id='p', kind='budget_confirmation',
            status='resolved', task_revision=1, input_version=version,
            reason_code='budget_exceeded', error_code=None, created_at=NOW,
            resolved_at=NOW, resolved_task_revision=2))
        insert_row(db, 'task_resume_requests', dict(
            id='request', task_id='t', user_id='u', idempotency_key='private-resume-key',
            operation='resume', wait_id='wait', request_digest='a' * 64,
            expected_task_revision=1, input_version=version, result_task_revision=2,
            response_json={'id': 'private-task-result', 'status': 'queued'}, created_at=NOW))
    with database_connection(config=postgres_schema) as db:
        result = audit_database(db)
    assert result['ok'], {'schema_issues': result['schema_issues'],
                          'invalid_checks': [item for item in result['data_checks'] if item['invalid']]}
    checks = {(item['table'], item['column']): item for item in result['data_checks']}
    for key in (('task_waits', 'created_at'), ('task_waits', 'resolved_at'),
                ('task_resume_requests', 'created_at')):
        assert checks[key]['rows'] == 1
        assert checks[key]['invalid'] == 0
    assert ('task_resume_requests', 'response_json') not in checks
    assert 'private-' not in json.dumps(result)


@pytest.mark.parametrize('table', ['task_waits', 'task_resume_requests'])
@pytest.mark.parametrize('drift', ['missing_delete', 'extra_truncate'])
def test_wait_table_runtime_permissions_are_enforced(
        postgres_schema, postgres_migration_config, table, drift):
    from app.db.database import database_connection, migration_connection, verify_runtime_permissions
    with database_connection(config=postgres_schema) as db:
        verify_runtime_permissions(db.raw_connection, postgres_schema)
    with migration_connection(write=True, config=postgres_migration_config) as db:
        quote = db.raw_connection.dialect.identifier_preparer.quote
        role = quote(postgres_schema.url.username)
        statement = (f'REVOKE DELETE ON {table} FROM {role}' if drift == 'missing_delete'
                     else f'GRANT TRUNCATE ON {table} TO {role}')
        db.execute(statement)
    message = ('missing business table permissions' if drift == 'missing_delete'
               else 'administrative table permissions')
    with database_connection(config=postgres_schema) as db:
        with pytest.raises(ValueError, match=message):
            verify_runtime_permissions(db.raw_connection, postgres_schema)

def test_source_chain_mismatch(postgres_schema):
    from app.db.database import database_connection
    with database_connection(write=True, config=postgres_schema) as db:
        db.execute("INSERT INTO projects(id,name,research_topic,project_type,created_at,updated_at) VALUES ('p','n','t','sci','2026-10-05T00:00:00Z','2026-10-05T00:00:00Z')")
        db.execute("INSERT INTO files(id,project_id,filename,file_type,size_bytes,sha256,uploaded_at,parse_status) VALUES ('f','p','n','csv',1,'h','2026-10-05T00:00:00Z','parsed')")
        for run, revision in [('r1',1), ('r2',2)]:
            db.execute("INSERT INTO analysis_runs(id,file_id,setup_revision,engine_version,completed_at,result_json) VALUES (%s,'f',%s,'v','2026-10-05T00:00:00Z','{}')", (run,revision))
        db.execute("INSERT INTO figures(id,analysis_run_id,renderer_version,figure_json) VALUES ('fig','r1','v','{}')")
        db.execute("INSERT INTO explanations(id,analysis_run_id,figure_id,engine_version,explanation_json) VALUES ('exp','r2','fig','v','{}')")
    with database_connection(config=postgres_schema) as db:
        result = audit_database(db)
    assert next(c for c in result['data_checks'] if c['table']=='explanations' and c['column']=='figure_id')['invalid'] == 1

def test_index_migration_roundtrip_preserves_values(postgres_schema, postgres_migration_config):
    from alembic import command
    from app.db.database import alembic_config, migration_connection
    with migration_connection(write=True, config=postgres_migration_config) as db:
        db.execute("INSERT INTO projects(id,name,research_topic,project_type,created_at,updated_at) VALUES ('p','n','t','sci','legacy exact text','2026-10-05T00:00:00.123456Z')")
        before = dict(db.execute("SELECT * FROM projects WHERE id='p'").fetchone())
        settings = alembic_config()
        settings.attributes['connection'] = db.raw_connection
        settings.attributes['database_config'] = postgres_migration_config
        command.downgrade(settings, '0004_language_preferences')
        assert db.execute("SELECT to_regclass('projects_owner_updated') AS name").fetchone()['name'] is None
        command.upgrade(settings, 'head')
        assert dict(db.execute("SELECT * FROM projects WHERE id='p'").fetchone()) == before
        assert db.execute("SELECT to_regclass('projects_owner_updated') AS name").fetchone()['name'] is not None

def test_index_drift_still_audits_legacy_values(postgres_schema, postgres_migration_config):
    from app.db.database import database_connection, migration_connection
    with database_connection(write=True, config=postgres_schema) as db:
        db.execute("INSERT INTO projects(id,name,research_topic,project_type,created_at,updated_at) VALUES ('p','n','t','sci','bad timestamp','2026-10-05T00:00:00Z')")
    with migration_connection(write=True, config=postgres_migration_config) as db:
        db.execute('DROP INDEX reports_run')
    with database_connection(config=postgres_schema) as db:
        result = audit_database(db)
    assert not result['ok']
    assert {'table': 'reports', 'kind': 'index:reports_run'} in result['schema_issues']
    assert len(result['data_checks']) == 50
    assert next(c for c in result['data_checks'] if c['table']=='projects' and c['column']=='created_at')['invalid'] == 1

def test_version_drift_is_reported_without_hiding_data(postgres_schema, postgres_migration_config):
    from app.db.database import database_connection, migration_connection
    with migration_connection(write=True, config=postgres_migration_config) as db:
        db.execute("UPDATE alembic_version SET version_num='0004_language_preferences'")
    with database_connection(config=postgres_schema) as db:
        result = audit_database(db)
    assert not result['ok']
    assert {'table': 'alembic_version', 'kind': 'version'} in result['schema_issues']
    assert len(result['data_checks']) == 50

import unittest

class AuditNormalizationTests(unittest.TestCase):
    def test_literals_remain_case_sensitive(self):
        from app.maintenance.database_audit import _check_signature
        self.assertNotEqual(_check_signature("ui_language IN ('zh-CN','en')"), _check_signature("ui_language IN ('zh-cn','EN')"))
        self.assertNotEqual(_check_signature("'zh-CN'::text"), _check_signature("'zh-cn'::text"))

    def test_literal_contents_remain_intact(self):
        from app.maintenance.database_audit import _check_signature
        for left, right in [("'A (B)'", "'A B'"), ("'a b'", "'ab'"), ("'::text'", "''"), ("'a''B'", "'a''b'")]:
            self.assertNotEqual(_check_signature('value = ' + left), _check_signature('value = ' + right))

    def test_postgresql_rewrites_are_equivalent(self):
        from app.maintenance.database_audit import _check_signature
        self.assertEqual(_check_signature("ui_language IN ('zh-CN', 'en')"), _check_signature("((ui_language = ANY (ARRAY['zh-CN'::text, 'en'::text])))"))

    def test_json_numeric_overflow(self):
        self.assertFalse(valid_json('1e1000'))
        self.assertFalse(valid_json('{"nested":[1e1000]}'))
        self.assertTrue(valid_json('{"nested":[1e100]}'))

def test_not_valid_constraint_is_reported(postgres_schema, postgres_migration_config):
    from app.db.database import database_connection, migration_connection
    with migration_connection(write=True, config=postgres_migration_config) as db:
        db.execute('ALTER TABLE users DROP CONSTRAINT users_role_check')
        db.execute("INSERT INTO users(id,email,password_hash,role,active,created_at,updated_at) VALUES ('invalid-role-user','private@example.test','private-hash','unexpected',true,1,1)")
        db.execute("ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (role IN ('user','admin')) NOT VALID")
    with database_connection(config=postgres_schema) as db:
        result = audit_database(db)
    assert not result['ok']
    assert {'table': 'users', 'kind': 'constraint_state:users_role_check'} in result['schema_issues']
    assert len(result['data_checks']) == 50
    assert 'private@example.test' not in json.dumps(result)
    assert 'unexpected' not in json.dumps(result)
