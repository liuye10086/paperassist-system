import json
import pytest
from app.database_audit import valid_json, valid_timestamp, valid_numeric_time, audit_database, main

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

def test_clean_schema(postgres_schema):
    from app.database import database_connection
    with database_connection(config=postgres_schema) as db:
        result = audit_database(db)
    assert result['ok'], result
    assert len(result['data_checks']) == 31

def test_cli_failure_is_safe(monkeypatch, capsys):
    import app.database_audit as module
    def fail():
        raise RuntimeError('secret password and row payload')
    monkeypatch.setattr(module, 'get_database_config', fail)
    assert main() == 1
    output = capsys.readouterr()
    assert 'secret' not in output.err + output.out

def test_audit_bad_values_and_readonly(postgres_schema):
    from app.database import database_connection
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
    from app.database import database_connection, migration_connection
    with migration_connection(write=True, config=postgres_migration_config) as db:
        db.execute('DROP INDEX projects_owner_updated')
        db.execute('CREATE INDEX projects_owner_updated ON projects(owner_id,updated_at ASC,id ASC)')
    with database_connection(config=postgres_schema) as db:
        result = audit_database(db)
    assert {'table': 'projects', 'kind': 'index:projects_owner_updated'} in result['schema_issues']

def test_source_chain_mismatch(postgres_schema):
    from app.database import database_connection
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
    from app.database import alembic_config, migration_connection
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
    from app.database import database_connection, migration_connection
    with database_connection(write=True, config=postgres_schema) as db:
        db.execute("INSERT INTO projects(id,name,research_topic,project_type,created_at,updated_at) VALUES ('p','n','t','sci','bad timestamp','2026-10-05T00:00:00Z')")
    with migration_connection(write=True, config=postgres_migration_config) as db:
        db.execute('DROP INDEX reports_run')
    with database_connection(config=postgres_schema) as db:
        result = audit_database(db)
    assert not result['ok']
    assert {'table': 'reports', 'kind': 'index:reports_run'} in result['schema_issues']
    assert len(result['data_checks']) == 31
    assert next(c for c in result['data_checks'] if c['table']=='projects' and c['column']=='created_at')['invalid'] == 1

def test_version_drift_is_reported_without_hiding_data(postgres_schema, postgres_migration_config):
    from app.database import database_connection, migration_connection
    with migration_connection(write=True, config=postgres_migration_config) as db:
        db.execute("UPDATE alembic_version SET version_num='0004_language_preferences'")
    with database_connection(config=postgres_schema) as db:
        result = audit_database(db)
    assert not result['ok']
    assert {'table': 'alembic_version', 'kind': 'version'} in result['schema_issues']
    assert len(result['data_checks']) == 31

import unittest

class AuditNormalizationTests(unittest.TestCase):
    def test_literals_remain_case_sensitive(self):
        from app.database_audit import _check_signature
        self.assertNotEqual(_check_signature("ui_language IN ('zh-CN','en')"), _check_signature("ui_language IN ('zh-cn','EN')"))
        self.assertNotEqual(_check_signature("'zh-CN'::text"), _check_signature("'zh-cn'::text"))

    def test_literal_contents_remain_intact(self):
        from app.database_audit import _check_signature
        for left, right in [("'A (B)'", "'A B'"), ("'a b'", "'ab'"), ("'::text'", "''"), ("'a''B'", "'a''b'")]:
            self.assertNotEqual(_check_signature('value = ' + left), _check_signature('value = ' + right))

    def test_postgresql_rewrites_are_equivalent(self):
        from app.database_audit import _check_signature
        self.assertEqual(_check_signature("ui_language IN ('zh-CN', 'en')"), _check_signature("((ui_language = ANY (ARRAY['zh-CN'::text, 'en'::text])))"))

    def test_json_numeric_overflow(self):
        self.assertFalse(valid_json('1e1000'))
        self.assertFalse(valid_json('{"nested":[1e1000]}'))
        self.assertTrue(valid_json('{"nested":[1e100]}'))

def test_not_valid_constraint_is_reported(postgres_schema, postgres_migration_config):
    from app.database import database_connection, migration_connection
    with migration_connection(write=True, config=postgres_migration_config) as db:
        db.execute('ALTER TABLE users DROP CONSTRAINT users_role_check')
        db.execute("INSERT INTO users(id,email,password_hash,role,active,created_at,updated_at) VALUES ('invalid-role-user','private@example.test','private-hash','unexpected',true,1,1)")
        db.execute("ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (role IN ('user','admin')) NOT VALID")
    with database_connection(config=postgres_schema) as db:
        result = audit_database(db)
    assert not result['ok']
    assert {'table': 'users', 'kind': 'constraint_state:users_role_check'} in result['schema_issues']
    assert len(result['data_checks']) == 31
    assert 'private@example.test' not in json.dumps(result)
    assert 'unexpected' not in json.dumps(result)
