"""0081 upgrade/recovery and rollback, confined to the fixture's test schema."""

import time

from alembic import command
from psycopg.types.json import Jsonb

from app.auth import service as auth
from app.core.config import get_data_dir
from app.db.database import (SCHEMA_HEAD, alembic_config, database_connection,
                             get_database_config, get_migration_database_config,
                             migration_connection, verify_runtime_permissions)
from app.domain.account_deletion import delete_account
from tests.api.test_admin_operations import PASSWORD, seed_task


def migrate(revision, *, down=False):
    config = get_migration_database_config()
    assert config.environment == 'test' and config.schema.startswith('pa_test_')
    with migration_connection(write=True) as db:
        assert db.execute('SELECT current_database() AS name').fetchone()['name'] == 'paperassist_system_test'
        settings = alembic_config()
        settings.attributes.update(connection=db.raw_connection, database_config=config)
        (command.downgrade if down else command.upgrade)(settings, revision)


def function_security(*, current_tables=True):
    with database_connection() as db:
        runtime = get_database_config()
        if current_tables:
            verify_runtime_permissions(db.raw_connection, runtime)
        row = db.execute("""SELECT p.oid, p.prosecdef, p.proconfig,
            has_function_privilege(%s, p.oid, 'EXECUTE') AS runtime_execute,
            EXISTS (SELECT 1 FROM aclexplode(COALESCE(p.proacl, acldefault('f',p.proowner))) a
                    WHERE a.grantee=0 AND a.privilege_type='EXECUTE') AS public_execute
            FROM pg_proc p WHERE p.oid='erase_account_records(text,text,integer,jsonb)'::regprocedure""",
            (runtime.url.username,)).fetchone()
        assert row['prosecdef'] and row['runtime_execute'] and not row['public_execute']
        assert row['proconfig'] == [f'search_path=pg_catalog, {runtime.schema}, pg_temp']
        return dict(row)


def test_upgrade_preserves_pending_plan_and_recovers_legacy_rows():
    target = auth.create_user('pending@deletion-migration.test', PASSWORD, 'customer')
    operator = auth.create_user('admin@deletion-migration.test', PASSWORD, 'admin')
    other = auth.create_user('retained@deletion-migration.test', PASSWORD, 'customer')
    target_project, _ = seed_task(target['id'])
    retained_project, _ = seed_task(other['id'])
    other_token, identity = auth.authenticate(other['email'], PASSWORD, '127.0.0.1')
    security = function_security()
    migrate('0080_account_deletion', down=True)

    plan = {'root': str(get_data_dir()), 'files': []}
    with database_connection(write=True) as db:
        # Run the actual legacy first phase, not a fabricated account_deletions row.
        assert db.execute('SELECT erase_account_records(%s,%s,1,%s) AS error',
                          (operator['id'], target['id'], Jsonb(plan))).fetchone()['error'] is None
        db.execute("INSERT INTO session_revocations(token_hash,user_id,reason,revoked_at,source) VALUES(%s,%s,'account_disabled',%s,'session')",
                   ('legacy-revocation', target['id'], time.time()))
    with database_connection() as db:
        before = {table: db.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall()
                  for table in ('users', 'projects', 'tasks', 'sessions', 'session_revocations', 'account_deletions')}
    migrate(SCHEMA_HEAD)
    assert function_security() == security
    with database_connection() as db:
        for table, rows in before.items():
            assert db.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall() == rows, table
        assert db.execute('SELECT assets FROM account_deletions WHERE user_id=%s', (target['id'],)).fetchone()['assets'] == plan
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()['version_num'] == SCHEMA_HEAD
    assert delete_account(operator['id'], target['id'], 1) == {'id': target['id'], 'deleted': True}
    assert auth.resolve_session(other_token) == identity
    with database_connection() as db:
        assert not db.execute('SELECT id FROM users WHERE id=%s', (target['id'],)).fetchone()
        assert not db.execute('SELECT id FROM projects WHERE id=%s', (target_project,)).fetchone()
        assert not db.execute('SELECT 1 FROM session_revocations WHERE user_id=%s', (target['id'],)).fetchone()
        assert not db.execute('SELECT 1 FROM account_deletions WHERE user_id=%s', (target['id'],)).fetchone()
        assert db.execute('SELECT id FROM projects WHERE id=%s', (retained_project,)).fetchone()


def test_downgrade_and_reupgrade_preserve_data_and_function_permissions():
    account = auth.create_user('retained-roundtrip@deletion-migration.test', PASSWORD, 'customer')
    token, identity = auth.authenticate(account['email'], PASSWORD, '127.0.0.1')
    security = function_security()
    migrate('0080_account_deletion', down=True)
    # A historical revision has no table for a later migration. Check the
    # rolled-back function directly and verify full runtime grants at head.
    assert function_security(current_tables=False) == security
    with database_connection() as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()['version_num'] == '0080_account_deletion'
    migrate(SCHEMA_HEAD)
    assert function_security() == security
    assert auth.resolve_session(token) == identity
