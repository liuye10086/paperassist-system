from app.core.paths import BACKEND_ROOT, PROJECT_ROOT
"""Password security uses only the fixture's disposable PostgreSQL schema."""
from app.db.database import migration_connection
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.auth import service
from app.db.database import database_connection
from app.core.exceptions import StorageError

PASSWORD = "correct password 123"
NEW = "replacement password 456"
EMAIL = "user@example.local"
WEB = {"X-PaperAssist-Client": "web", "Origin": "http://testserver"}


def account(email=EMAIL):
    return service.create_user(email, PASSWORD)


def login(client, email=EMAIL):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}, headers=WEB)
    assert response.status_code == 200
    return {**WEB, "X-CSRF-Token": response.json()["csrf_token"]}


def reset(client, code, password=NEW, headers=None):
    return client.post("/api/v1/auth/reset-password", json={"recovery_code": code, "new_password": password}, headers=headers or WEB)


def issue(email=EMAIL):
    from app.auth.passwords import issue_recovery_code
    return issue_recovery_code(email)


def rows(table):
    with database_connection() as db:
        return [dict(row) for row in db.execute(f"SELECT * FROM {table}")]


def test_change_password_revokes_only_own_sessions_and_audits_digest():
    own = account()
    account("other@example.local")
    with TestClient(app) as client, TestClient(app) as second, TestClient(app) as other:
        headers = login(client)
        login(second)
        login(other, "other@example.local")
        token = client.cookies.get("paperassist_session")
        csrf = headers["X-CSRF-Token"]
        result = client.post("/api/v1/auth/change-password", json={"current_password": PASSWORD, "new_password": NEW}, headers=headers)
        assert result.status_code == 204
        assert "Max-Age=0" in result.headers["set-cookie"]
        assert second.get("/api/v1/auth/me").status_code == 401
        assert other.get("/api/v1/auth/me").status_code == 200
        audit = rows("session_revocations")
        assert len(audit) == 2
        assert {row["user_id"] for row in audit} == {own["id"]}
        assert {row["reason"] for row in audit} == {"password_changed"}
        assert {row["source"] for row in audit} == {"web"}
        assert service.digest(token) in {row["token_hash"] for row in audit}
        for secret in (token, csrf, PASSWORD, NEW):
            assert secret not in str(audit)
        assert client.post("/api/v1/auth/login", json={"email": EMAIL, "password": NEW}, headers=WEB).status_code == 200


def test_change_requires_auth_csrf_valid_password_and_persists_failure_limit():
    account()
    with TestClient(app) as client:
        body = {"current_password": PASSWORD, "new_password": NEW}
        assert client.post("/api/v1/auth/change-password", json=body, headers=WEB).status_code == 401
        headers = login(client)
        assert client.post("/api/v1/auth/change-password", json=body, headers=WEB).status_code == 403
        for invalid in ("short", "x" * 129):
            result = client.post("/api/v1/auth/change-password", json={**body, "new_password": invalid}, headers=headers)
            assert result.status_code == 422
            assert result.json()["detail"]["code"] == "invalid_request"
            assert invalid not in result.text
        for _ in range(5):
            result = client.post("/api/v1/auth/change-password", json={**body, "current_password": "wrong secret"}, headers=headers)
            assert result.status_code == 400
            assert result.json()["detail"]["code"] == "invalid_current_password"
        result = client.post("/api/v1/auth/change-password", json=body, headers=headers)
        assert result.status_code == 429
        assert result.headers["Retry-After"] == "900"
        assert len(rows("auth_password_attempts")) == 5
        assert "wrong secret" not in str(rows("auth_password_attempts"))


def test_recovery_digest_lifetime_success_and_replay():
    own = account()
    with TestClient(app) as client:
        login(client)
        before = time.time()
        code = issue()
        record = rows("password_recovery_codes")[0]
        assert record["code_hash"] == service.digest(code)
        assert code not in str(record)
        assert before + 900 <= record["expires_at"] <= time.time() + 900
        assert record["used_at"] is None and record["revoked_at"] is None
        result = reset(client, code)
        assert result.status_code == 204
        assert "Max-Age=0" in result.headers["set-cookie"]
        assert client.get("/api/v1/auth/me").status_code == 401
        assert rows("password_recovery_codes")[0]["used_at"] is not None
        assert rows("session_revocations")[0]["reason"] == "password_recovered"
        assert rows("session_revocations")[0]["user_id"] == own["id"]
        assert reset(client, code).json()["detail"]["code"] == "invalid_recovery_code"


@pytest.mark.parametrize("action", ["expiry", "reissue", "disable", "enable", "admin_reset", "self_change"])
def test_recovery_invalidation(action, monkeypatch):
    account()
    code = issue()
    if action == "expiry":
        from app.auth import passwords
        expiry = rows("password_recovery_codes")[0]["expires_at"]
        monkeypatch.setattr(passwords, "now", lambda: expiry)
    elif action == "reissue":
        assert issue() != code
    elif action in ("disable", "enable"):
        service.set_user_active(EMAIL, action == "enable")
    elif action == "admin_reset":
        service.reset_password(EMAIL, NEW)
    else:
        with TestClient(app) as client:
            headers = login(client)
            assert client.post("/api/v1/auth/change-password", json={"current_password": PASSWORD, "new_password": NEW}, headers=headers).status_code == 204
    with TestClient(app) as client:
        result = reset(client, code)
        assert result.status_code == 400
        assert result.json()["detail"]["code"] == "invalid_recovery_code"


def test_public_recovery_origin_validation_no_secret_echo_and_code_limit():
    with TestClient(app) as client:
        assert client.post("/api/v1/auth/reset-password", json={"recovery_code": "secret", "new_password": NEW}).status_code == 403
        assert reset(client, "secret", headers={**WEB, "Origin": "https://evil.example"}).status_code == 403
        assert reset(client, "secret", headers={**WEB, "Sec-Fetch-Site": "cross-site"}).status_code == 403
        assert reset(client, "secret", "short").status_code == 422
        for _ in range(5):
            result = reset(client, "secret")
            assert result.status_code == 400
            assert "secret" not in result.text
        result = reset(client, "secret")
        assert result.status_code == 429
        assert result.json()["detail"]["code"] == "password_rate_limited"
        assert "secret" not in str(rows("auth_password_attempts"))


def test_password_direct_ip_limit_ignores_forwarded_for():
    with TestClient(app) as client:
        for number in range(30):
            assert reset(client, f"invalid-code-{number}").status_code == 400
        assert reset(client, "another", headers={**WEB, "X-Forwarded-For": "fresh-ip"}).status_code == 429


def test_password_limit_expires_at_fifteen_minutes(monkeypatch):
    from app.auth import passwords
    with TestClient(app) as client:
        for _ in range(5):
            assert reset(client, "bad-code").status_code == 400
        cutoff = max(row["attempted_at"] for row in rows("auth_password_attempts")) + 900
        monkeypatch.setattr(passwords, "now", lambda: cutoff)
        assert reset(client, "bad-code").status_code == 400


def test_concurrent_recovery_has_one_success():
    from app.auth.passwords import recover_password
    account()
    code = issue()
    def consume(number):
        try:
            recover_password(code, NEW, str(number))
            return 204
        except StorageError as error:
            return error.status
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(consume, (1, 2))) == [204, 400]


@pytest.mark.parametrize("action,reason,source", [("logout", "logout", "web"), ("absolute", "absolute_expired", "session"), ("idle", "idle_expired", "session"), ("reset", "admin_password_reset", "cli"), ("disable", "account_disabled", "cli"), ("enable", "account_enabled", "cli")])
def test_all_session_removals_audited_once(action, reason, source):
    account()
    with TestClient(app) as client:
        headers = login(client)
        token = client.cookies.get("paperassist_session")
        if action == "logout":
            assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
        elif action in ("absolute", "idle"):
            with database_connection(write=True) as db:
                db.execute("UPDATE sessions SET " + ("expires_at" if action == "absolute" else "last_seen_at") + " = 0")
            assert client.get("/api/v1/auth/me").status_code == 401
        elif action == "reset":
            service.reset_password(EMAIL, NEW)
        else:
            service.set_user_active(EMAIL, action == "enable")
        service.revoke_session(token)
        records = rows("session_revocations")
        assert len(records) == 1
        assert records[0]["reason"] == reason and records[0]["source"] == source


def test_audit_failure_rolls_back_password_sessions_and_recovery():
    account()
    with TestClient(app) as client:
        login(client)
        code = issue()
        original = rows("users")[0]["password_hash"]
        with migration_connection(write=True) as db:
            db.execute("CREATE FUNCTION reject_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'audit failure'; END $$")
            db.execute("CREATE TRIGGER reject_audit BEFORE INSERT ON session_revocations FOR EACH ROW EXECUTE FUNCTION reject_audit()")
        result = reset(client, code)
        assert result.status_code == 503
        assert "audit failure" not in result.text and code not in result.text
        assert rows("users")[0]["password_hash"] == original
        assert len(rows("sessions")) == 1
        assert rows("password_recovery_codes")[0]["used_at"] is None


def test_change_revalidates_session_after_middleware(monkeypatch):
    from app.auth import middleware
    account()
    with TestClient(app) as client:
        headers = login(client)
        original_resolve = middleware.resolve_session
        def revoke_after_resolve(token):
            result = original_resolve(token)
            service.revoke_session(token)
            return result
        monkeypatch.setattr(middleware, "resolve_session", revoke_after_resolve)
        result = client.post("/api/v1/auth/change-password", json={"current_password": PASSWORD, "new_password": NEW}, headers=headers)
        assert result.status_code == 401
        assert service.hasher.verify(rows("users")[0]["password_hash"], PASSWORD)


def test_migration_preserves_accounts_sessions_projects_and_matches_metadata(postgres_schema, postgres_migration_config):
    from alembic import command
    from sqlalchemy import inspect
    from app.db.database import alembic_config, migrate_database, SCHEMA_HEAD
    from app.db.schema import metadata
    account()
    service.authenticate(EMAIL, PASSWORD, "test")
    with migration_connection(write=True) as db:
        db.execute("INSERT INTO projects (id,name,research_topic,project_type,created_at,updated_at,owner_id) SELECT 'legacy','name','topic','sci','now','now',id FROM users")
        config = alembic_config()
        config.attributes["connection"] = db.raw_connection
        config.attributes["database_config"] = postgres_migration_config
        command.downgrade(config, "0002_auth_ownership")
        originals = {table: [dict(row) for row in db.execute(f"SELECT * FROM {table}")] for table in ("users", "sessions", "projects")}
    migrate_database(postgres_migration_config)
    assert SCHEMA_HEAD == "0005_ownership_indexes"
    with database_connection() as db:
        for table, original in originals.items():
            actual = [dict(row) for row in db.execute(f"SELECT * FROM {table}")]
            for row in actual:
                if table in ("users", "projects"):
                    column = "ui_language" if table == "users" else "default_output_language"
                    assert row.pop(column) == "zh-CN"
            assert actual == original
        inspector = inspect(db.raw_connection)
        assert set(inspector.get_table_names()) == set(metadata.tables) | {"alembic_version"}
        for table in ("session_revocations", "password_recovery_codes", "auth_password_attempts"):
            assert {column["name"] for column in inspector.get_columns(table)} == set(metadata.tables[table].columns.keys())


def test_cli_recovery_requires_identity_confirmation_and_terminal(monkeypatch, capsys):
    from app import manage_users
    account()
    monkeypatch.setattr("sys.argv", ["manage_users", "issue-recovery", "--email", EMAIL])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stderr.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    assert manage_users.main() == 1
    assert rows("password_recovery_codes") == []
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "no")
    assert manage_users.main() == 1
    assert rows("password_recovery_codes") == []
    monkeypatch.setattr("builtins.input", lambda prompt: "YES")
    assert manage_users.main() == 0
    output = capsys.readouterr().out
    code = output.splitlines()[-1]
    assert len(code) >= 43
    assert rows("password_recovery_codes")[0]["code_hash"] == service.digest(code)


@pytest.mark.parametrize("action", ["logout", "admin_reset", "disable", "enable", "self_change", "expiry"])
def test_audit_failure_rolls_back_every_revocation_path(action):
    account()
    code = issue()
    with TestClient(app) as client:
        headers = login(client)
        token = client.cookies.get("paperassist_session")
        if action == "expiry":
            with database_connection(write=True) as db:
                db.execute("UPDATE sessions SET expires_at = 0")
        original_user = rows("users")
        original_sessions = rows("sessions")
        original_recovery = rows("password_recovery_codes")
        with migration_connection(write=True) as db:
            db.execute("CREATE FUNCTION reject_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'audit failure'; END $$")
            db.execute("CREATE TRIGGER reject_audit BEFORE INSERT ON session_revocations FOR EACH ROW EXECUTE FUNCTION reject_audit()")
        if action in ("logout", "admin_reset", "disable", "enable", "expiry"):
            with pytest.raises(StorageError):
                if action == "logout":
                    service.revoke_session(token)
                elif action == "admin_reset":
                    service.reset_password(EMAIL, NEW)
                elif action == "expiry":
                    service.resolve_session(token)
                else:
                    service.set_user_active(EMAIL, action == "enable")
        else:
            result = client.post("/api/v1/auth/change-password", json={"current_password": PASSWORD, "new_password": NEW}, headers=headers)
            assert result.status_code == 503
            # Middleware's last-seen refresh is an earlier independent transaction.
            original_sessions[0]["last_seen_at"] = rows("sessions")[0]["last_seen_at"]
        assert rows("users") == original_user
        assert rows("sessions") == original_sessions
        assert rows("password_recovery_codes") == original_recovery
        assert rows("session_revocations") == []
        assert code not in str(original_recovery)


def test_reissue_failure_preserves_previous_usable_recovery_code():
    account()
    code = issue()
    original = rows("password_recovery_codes")
    with migration_connection(write=True) as db:
        db.execute("CREATE FUNCTION reject_code() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'code failure'; END $$")
        db.execute("CREATE TRIGGER reject_code BEFORE INSERT ON password_recovery_codes FOR EACH ROW EXECUTE FUNCTION reject_code()")
    with pytest.raises(StorageError):
        issue()
    assert rows("password_recovery_codes") == original
    with TestClient(app) as client:
        assert reset(client, code).status_code == 204


def test_recovery_cannot_issue_or_consume_inactive_account():
    account()
    code = issue()
    with database_connection(write=True) as db:
        db.execute("UPDATE users SET active = false")
    with pytest.raises(ValueError):
        issue()
    with TestClient(app) as client:
        assert reset(client, code).json()["detail"]["code"] == "invalid_recovery_code"
    assert rows("password_recovery_codes")[0]["used_at"] is None


def test_account_limit_is_shared_across_reissued_credentials_and_self_change():
    own = account()
    old = issue()
    code = issue()
    with TestClient(app) as client:
        headers = login(client)
        for _ in range(5):
            assert reset(client, old).status_code == 400
        assert reset(client, code).status_code == 429
        assert client.post("/api/v1/auth/change-password", json={"current_password": PASSWORD, "new_password": NEW}, headers=headers).status_code == 429
    assert {row["user_id"] for row in rows("auth_password_attempts")} == {own["id"]}


def test_recovery_revokes_only_target_user_and_preserves_others():
    account()
    account("other@example.local")
    own_code, other_code = issue(), issue("other@example.local")
    with TestClient(app) as client, TestClient(app) as other:
        login(client)
        login(other, "other@example.local")
        assert reset(client, own_code).status_code == 204
        assert other.get("/api/v1/auth/me").status_code == 200
        record = next(row for row in rows("password_recovery_codes") if row["code_hash"] == service.digest(other_code))
        assert record["used_at"] is None and record["revoked_at"] is None
        assert reset(other, other_code).status_code == 204


def test_change_rechecks_active_state_csrf_and_expiry_inside_transaction():
    from app.auth.passwords import change_password
    account()
    token, result = service.authenticate(EMAIL, PASSWORD, "test")
    with pytest.raises(StorageError) as error:
        change_password(token, "wrong-csrf", PASSWORD, NEW, "test")
    assert error.value.status == 403
    with database_connection(write=True) as db:
        db.execute("UPDATE sessions SET expires_at = 0")
    with pytest.raises(StorageError) as error:
        change_password(token, result["csrf_token"], PASSWORD, NEW, "test")
    assert error.value.status == 401
    assert rows("session_revocations")[0]["reason"] == "absolute_expired"
    assert service.hasher.verify(rows("users")[0]["password_hash"], PASSWORD)


def test_password_request_errors_never_echo_nested_or_oversized_secrets():
    account()
    with TestClient(app) as client:
        headers = login(client)
        secret = "secret-sensitive" * 20
        for path, body, security in (
            ("change-password", {"current_password": {"secret": secret}, "new_password": NEW}, headers),
            ("reset-password", {"recovery_code": secret, "new_password": NEW}, WEB),
            ("reset-password", {"recovery_code": "valid-format", "new_password": secret}, WEB),
        ):
            result = client.post("/api/v1/auth/" + path, json=body, headers=security)
            assert result.status_code == 422
            assert secret not in result.text


def test_invalid_and_limited_recovery_skip_expensive_password_hash(monkeypatch):
    from app.auth import passwords
    def unexpected_hash(password):
        pytest.fail("Rejected recovery must not spend Argon2 resources on the new password")
    monkeypatch.setattr(passwords, "password_hash", unexpected_hash)
    for _ in range(5):
        with pytest.raises(StorageError) as error:
            passwords.recover_password("bad-code", NEW, "test")
        assert error.value.status == 400
    with pytest.raises(StorageError) as error:
        passwords.recover_password("bad-code", NEW, "test")
    assert error.value.status == 429


def test_documented_uvicorn_server_preserves_direct_peer_for_password_limit():
    """Exercise Uvicorn's real proxy wrapper, not just FastAPI middleware."""
    import uvicorn

    readme = PROJECT_ROOT / "README.md"
    commands = [line for line in readme.read_text(encoding="utf-8").splitlines()
                if "-m uvicorn app.main:app" in line]
    assert len(commands) == 3
    proxy_options = {"--no-proxy-headers" not in line.split() for line in commands}
    assert len(proxy_options) == 1, "All documented server commands must use the same proxy policy"
    config = uvicorn.Config(
        app, proxy_headers=proxy_options.pop(),
        forwarded_allow_ips="127.0.0.1,::1", log_config=None,
    )
    config.load()
    with TestClient(config.loaded_app, client=("127.0.0.1", 50000)) as client:
        for number in range(30):
            result = reset(client, f"proxy-invalid-{number}",
                           headers={**WEB, "X-Forwarded-For": f"192.0.2.{number + 1}"})
            assert result.status_code == 400
        result = reset(client, "proxy-invalid-final",
                       headers={**WEB, "X-Forwarded-For": "192.0.2.100"})
        assert result.status_code == 429
    assert {row["client_ip"] for row in rows("auth_password_attempts")} == {"127.0.0.1"}
