"""Session reads must not queue behind unrelated project/storage writes."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time

import pytest

from app.auth.service import authenticate, create_user, digest, resolve_session
from app.db.database import database_connection


def session():
    account = create_user("session@example.local", "correct password 123")
    token, identity = authenticate(account["email"], "correct password 123", "127.0.0.1")
    return token, identity


def wait_for_blocker(waiter, blocker):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        with database_connection() as db:
            blockers = db.execute("SELECT pg_catalog.pg_blocking_pids(%s) AS blockers", (waiter,)).fetchone()["blockers"]
        if blocker in blockers:
            return
        time.sleep(0.01)
    pytest.fail("Session read never waited for the expected row lock")


@pytest.fixture
def observed_session_reader(monkeypatch):
    from app.auth import service
    started = Event()
    pids = []
    original = service.ensure_schema_current

    def observe(db):
        original(db)
        pids.append(db.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"])
        started.set()

    monkeypatch.setattr(service, "ensure_schema_current", observe)
    return started, pids


def test_session_read_and_touch_do_not_wait_for_unrelated_writer():
    token, identity = session()
    with database_connection(write=True) as db:
        db.execute("UPDATE sessions SET last_seen_at = last_seen_at - 30")
    with database_connection() as db:
        before = db.execute("SELECT last_seen_at FROM sessions").fetchone()["last_seen_at"]

    with ThreadPoolExecutor(max_workers=1) as executor:
        # A storage reconciliation owns this same schema-wide fence while doing
        # filesystem I/O. Authentication must finish before the fence is released.
        with database_connection(write=True):
            result = executor.submit(resolve_session, token).result(timeout=3)
            assert result == identity

    with database_connection() as db:
        assert db.execute("SELECT last_seen_at FROM sessions").fetchone()["last_seen_at"] > before


@pytest.mark.parametrize("change", ["logout", "absolute_expired", "idle_expired"])
def test_waiting_session_read_rechecks_committed_revocation_or_expiry(change, observed_session_reader):
    token, _ = session()
    started, pids = observed_session_reader
    started.clear()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with database_connection(write=True) as db:
            db.execute("SELECT token_hash FROM sessions WHERE token_hash = %s FOR UPDATE", (digest(token),))
            blocker = db.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
            pending = executor.submit(resolve_session, token)
            assert started.wait(timeout=3)
            wait_for_blocker(pids[-1], blocker)
            if change == "logout":
                from app.auth.revocations import revoke_sessions
                revoke_sessions(db, token_hash=digest(token), reason="logout", source="web", revoked_at=time.time())
            elif change == "absolute_expired":
                db.execute("UPDATE sessions SET expires_at = 0 WHERE token_hash = %s", (digest(token),))
            else:
                db.execute("UPDATE sessions SET last_seen_at = 0 WHERE token_hash = %s", (digest(token),))
        assert pending.result(timeout=3) is None

    with database_connection() as db:
        assert db.execute("SELECT token_hash FROM sessions").fetchone() is None
        rows = list(db.execute("SELECT reason FROM session_revocations WHERE token_hash = %s", (digest(token),)))
        assert [row["reason"] for row in rows] == [change]


@pytest.mark.parametrize("active", [True, False])
def test_waiting_session_read_uses_current_account_state(active, observed_session_reader):
    token, identity = session()
    started, pids = observed_session_reader
    started.clear()
    with ThreadPoolExecutor(max_workers=1) as executor:
        with database_connection(write=True) as db:
            db.execute("SELECT token_hash FROM sessions WHERE token_hash = %s FOR UPDATE", (digest(token),))
            blocker = db.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
            pending = executor.submit(resolve_session, token)
            assert started.wait(timeout=3)
            wait_for_blocker(pids[-1], blocker)
            db.execute("UPDATE users SET active = %s, ui_language = 'en', role = 'admin' WHERE id = %s", (active, identity["user"]["id"]))
        result = pending.result(timeout=3)
        if active:
            assert result["user"] == {**identity["user"], "ui_language": "en", "role": "admin"}
        else:
            assert result is None
            with database_connection() as db:
                assert db.execute("SELECT reason FROM session_revocations").fetchone()["reason"] == "account_disabled"


def test_other_session_of_same_user_is_not_blocked_by_session_row_lock():
    token, identity = session()
    other, _ = authenticate(identity["user"]["email"], "correct password 123", "127.0.0.1")
    with ThreadPoolExecutor(max_workers=1) as executor:
        with database_connection(write=True) as db:
            db.execute("SELECT token_hash FROM sessions WHERE token_hash = %s FOR UPDATE", (digest(other),))
            assert executor.submit(resolve_session, token).result(timeout=3) == identity


def test_expiry_revocation_does_not_deadlock_with_preferences(monkeypatch):
    import time
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    import pytest
    from app.auth import service
    from app.core.exceptions import StorageError
    from app.db.database import DatabaseConnection, database_connection

    token, identity = session()
    with database_connection(write=True) as db:
        db.execute("UPDATE sessions SET expires_at = 0")

    resolving = Event()
    resume = Event()
    preferences_started = Event()
    pids = {}
    original_revoke = service.revoke_sessions
    original_execute = DatabaseConnection.execute

    def pause_revoke(db, **kwargs):
        if not resolving.is_set():
            pids["resolve"] = db.raw_connection.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
            resolving.set()
            assert resume.wait(timeout=5)
        return original_revoke(db, **kwargs)

    def observe_preference_lock(db, sql, parameters=()):
        if "OF users, sessions" in sql:
            pids["preferences"] = db.raw_connection.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
            preferences_started.set()
        return original_execute(db, sql, parameters)

    monkeypatch.setattr(service, "revoke_sessions", pause_revoke)
    monkeypatch.setattr(DatabaseConnection, "execute", observe_preference_lock)

    with ThreadPoolExecutor(max_workers=2) as executor:
        resolving_future = executor.submit(service.resolve_session, token)
        try:
            assert resolving.wait(timeout=3)
            preferences_future = executor.submit(service.update_preferences, token, identity["csrf_token"], "en")
            assert preferences_started.wait(timeout=3)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                with database_connection() as db:
                    blockers = db.execute(
                        "SELECT pg_catalog.pg_blocking_pids(%s) AS blockers", (pids["preferences"],)
                    ).fetchone()["blockers"]
                if pids["resolve"] in blockers:
                    break
                time.sleep(0.01)
            else:
                pytest.fail("Preferences never waited for the session row lock")
        finally:
            resume.set()
        assert resolving_future.result(timeout=5) is None
        with pytest.raises(StorageError) as rejected:
            preferences_future.result(timeout=5)
        assert rejected.value.code == "authentication_required"

    with database_connection() as db:
        assert db.execute("SELECT token_hash FROM sessions").fetchone() is None
        assert [row["reason"] for row in db.execute("SELECT reason FROM session_revocations")] == ["absolute_expired"]
        assert db.execute("SELECT ui_language FROM users").fetchone()["ui_language"] == "zh-CN"
