"""Real authentication/deletion races in disposable test schemas only."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time
from uuid import uuid4

import pytest

from app.auth import service as auth
from app.core.exceptions import StorageError
from app.db.database import DatabaseConnection, database_connection, migration_connection
from app.domain import account_deletion, account_deletion_assets
from tests.api.test_admin_operations import PASSWORD


def accounts():
    target = auth.create_user('target@deletion-sessions.test', PASSWORD, 'customer')
    operator = auth.create_user('admin@deletion-sessions.test', PASSWORD, 'admin')
    token, _ = auth.authenticate(target['email'], PASSWORD, '127.0.0.1')
    return target, operator, token


def wait_until(predicate, message):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    pytest.fail(message)


def blocked_by(waiter, blocker):
    with database_connection() as db:
        return blocker in db.execute('SELECT pg_blocking_pids(%s) AS pids', (waiter,)).fetchone()['pids']


def observe_deletion(monkeypatch):
    started, pids = Event(), []
    original = account_deletion._erase_records

    def observe(db, *args):
        if not started.is_set():
            pids.append(db.execute('SELECT pg_backend_pid() AS pid').fetchone()['pid'])
            started.set()
        return original(db, *args)

    monkeypatch.setattr(account_deletion, '_erase_records', observe)
    return started, pids


def assert_erased(target):
    with database_connection() as db:
        for table, key in [('users', 'id'), ('sessions', 'user_id'),
                           ('session_revocations', 'user_id'), ('account_deletions', 'user_id')]:
            assert db.execute(f'SELECT 1 FROM {table} WHERE {key}=%s', (target['id'],)).fetchone() is None


def test_refresh_after_row_capture_cannot_strand_account(monkeypatch, postgres_schema):
    target, operator, token = accounts()
    other = auth.create_user('other@deletion-sessions.test', PASSWORD, 'customer')
    other_token, other_identity = auth.authenticate(other['email'], PASSWORD, '127.0.0.1')
    gate_key = uuid4().int % (2**63 - 1)
    # Pause the real stored function exactly after collecting the row identities.
    # The hook exists solely inside this fixture-owned test schema.
    with migration_connection(write=True) as db:
        assert db.config.schema == postgres_schema.schema
        assert db.execute('SELECT current_database() AS name').fetchone()['name'] == 'paperassist_system_test'
        definition = db.execute("SELECT pg_get_functiondef('erase_account_records(text,text,integer,jsonb)'::regprocedure) AS body").fetchone()['body']
        marker = '    WHILE EXISTS (SELECT 1 FROM pg_temp.account_erase_rows'
        assert definition.count(marker) == 1
        definition = definition.replace(marker, f'    PERFORM pg_catalog.pg_advisory_xact_lock({gate_key});\n' + marker)
        db.raw_connection.exec_driver_sql(definition, execution_options={'no_parameters': True})

    deleting_started, deleting_pids = observe_deletion(monkeypatch)
    reading_started, reading_pids = Event(), []
    ensure = auth.ensure_schema_current

    def observe_reader(db):
        ensure(db)
        reading_pids.append(db.execute('SELECT pg_backend_pid() AS pid').fetchone()['pid'])
        reading_started.set()

    monkeypatch.setattr(auth, 'ensure_schema_current', observe_reader)
    with ThreadPoolExecutor(max_workers=3) as executor:
        with database_connection(write=True, serialize_writes=False) as gate:
            gate_pid = gate.execute('SELECT pg_backend_pid() AS pid').fetchone()['pid']
            gate.execute('SELECT pg_advisory_xact_lock(%s)', (gate_key,))
            deletion = executor.submit(account_deletion.delete_account, operator['id'], target['id'], 1)
            assert deleting_started.wait(8)
            wait_until(lambda: blocked_by(deleting_pids[0], gate_pid), 'Deletion did not reach the row-capture gate')
            refresh = executor.submit(auth.resolve_session, token)
            assert reading_started.wait(8)
            wait_until(lambda: refresh.done() or blocked_by(reading_pids[0], deleting_pids[0]),
                       'Refresh neither completed nor waited for the deletion row lock')
            assert executor.submit(auth.resolve_session, other_token).result(timeout=8) == other_identity
        # Old 0080 lets refresh complete with a new ctid, then fails the final user DELETE.
        assert deletion.result(timeout=10) == {'id': target['id'], 'deleted': True}
        assert refresh.result(timeout=10) is None
    assert_erased(target)
    assert auth.resolve_session(other_token) == other_identity


@pytest.mark.parametrize('revoked', [False, True])
def test_pending_retry_cleans_legacy_authentication_rows(monkeypatch, revoked):
    target, operator, token = accounts()
    other = auth.create_user('other@deletion-retry.test', PASSWORD, 'customer')
    other_token, other_identity = auth.authenticate(other['email'], PASSWORD, '127.0.0.1')

    def fail_cleanup(*args):
        raise StorageError('account_delete_incomplete', 'Injected filesystem failure', 503)

    with monkeypatch.context() as patch:
        patch.setattr(account_deletion_assets, 'remove_account_assets', fail_cleanup)
        with pytest.raises(StorageError, match='Injected filesystem failure'):
            account_deletion.delete_account(operator['id'], target['id'], 1)
    # Recreate the two states left by an old 0080 session race: a live session,
    # or the revocation audit written when that session next sees inactive user.
    with database_connection(write=True) as db:
        if revoked:
            db.execute('INSERT INTO session_revocations(token_hash,user_id,reason,revoked_at,source) VALUES(%s,%s,%s,%s,%s)',
                       (auth.digest(token), target['id'], 'account_disabled', time.time(), 'session'))
        else:
            db.execute('INSERT INTO sessions(token_hash,user_id,csrf_token,created_at,last_seen_at,expires_at) VALUES(%s,%s,%s,%s,%s,%s)',
                       (auth.digest(token), target['id'], 'legacy', time.time(), time.time(), time.time() + 3600))
        pending = db.execute('SELECT assets FROM account_deletions WHERE user_id=%s', (target['id'],)).fetchone()
        assert pending
    assert account_deletion.delete_account(operator['id'], target['id'], 1) == {'id': target['id'], 'deleted': True}
    assert_erased(target)
    assert auth.resolve_session(other_token) == other_identity


@pytest.mark.parametrize('expired', [False, True])
def test_inflight_session_and_deletion_do_not_deadlock(monkeypatch, expired):
    target, operator, token = accounts()
    if expired:
        with database_connection(write=True) as db:
            db.execute('UPDATE sessions SET expires_at=0 WHERE token_hash=%s', (auth.digest(token),))
    revoking, resume = Event(), Event()
    resolver_pids = []
    revoke = auth.revoke_sessions
    execute = DatabaseConnection.execute

    def pause_revocation(db, **kwargs):
        resolver_pids.append(db.execute('SELECT pg_backend_pid() AS pid').fetchone()['pid'])
        revoking.set()
        assert resume.wait(10)
        return revoke(db, **kwargs)

    def pause_touch(db, sql, parameters=()):
        if not expired and sql.startswith('UPDATE sessions SET last_seen_at'):
            resolver_pids.append(db.raw_connection.exec_driver_sql('SELECT pg_backend_pid()').scalar_one())
            revoking.set()
            assert resume.wait(10)
        return execute(db, sql, parameters)

    monkeypatch.setattr(auth, 'revoke_sessions', pause_revocation)
    monkeypatch.setattr(DatabaseConnection, 'execute', pause_touch)
    started, deleting_pids = observe_deletion(monkeypatch)
    with ThreadPoolExecutor(max_workers=2) as executor:
        resolving = executor.submit(auth.resolve_session, token)
        try:
            assert revoking.wait(8)
            deletion = executor.submit(account_deletion.delete_account, operator['id'], target['id'], 1)
            assert started.wait(8)
            wait_until(lambda: blocked_by(deleting_pids[0], resolver_pids[0]), 'Deletion did not wait for the session row')
        finally:
            resume.set()
        result = resolving.result(timeout=10)
        if expired:
            assert result is None
        else:
            assert result['user']['id'] == target['id']
        assert deletion.result(timeout=10) == {'id': target['id'], 'deleted': True}
    assert_erased(target)
