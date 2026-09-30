import pytest
from fastapi.testclient import TestClient
from app.main import app

PASSWORD = "correct password 123"
HEADERS = {"X-PaperAssist-Client": "web"}


def user():
    from app.auth.service import create_user

    return create_user("USER@example.local", PASSWORD)


def login(client, password=PASSWORD):
    return client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.local", "password": password},
        headers=HEADERS,
    )


def test_anonymous_api_requires_login():
    with TestClient(app) as client:
        assert client.get("/api/v1/projects").status_code == 401


def test_password_hash_and_normalized_email():
    from app.database import database_connection

    account = user()
    assert account["email"] == "user@example.local"
    with database_connection() as db:
        row = db.execute(
            "SELECT password_hash FROM users WHERE id = %s", (account["id"],)
        ).fetchone()
    assert row["password_hash"].startswith("$argon2id$")
    assert PASSWORD not in row["password_hash"]


def test_login_me_csrf_logout():
    user()
    with TestClient(app) as client:
        result = login(client)
        assert result.status_code == 200
        token = result.json()["csrf_token"]
        assert client.get("/api/v1/auth/me").json() == result.json()
        assert "HttpOnly" in result.headers["set-cookie"]
        assert client.post("/api/v1/auth/logout", headers=HEADERS).status_code == 403
        assert (
            client.post(
                "/api/v1/auth/logout", headers={**HEADERS, "X-CSRF-Token": token}
            ).status_code
            == 204
        )
        assert client.get("/api/v1/auth/me").status_code == 401


@pytest.mark.parametrize("action", ["reset", "disable", "expired"])
def test_revoked_and_expired_session(action):
    from app.auth.service import reset_password, set_user_active
    from app.database import database_connection

    user()
    with TestClient(app) as client:
        assert login(client).status_code == 200
        if action == "reset":
            reset_password("user@example.local", "replacement password 123")
        elif action == "disable":
            set_user_active("user@example.local", False)
        else:
            with database_connection(write=True) as db:
                db.execute("UPDATE sessions SET expires_at = 0")
        assert client.get("/api/v1/auth/me").status_code == 401


def test_login_rate_limit_and_cross_site():
    user()
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"email": "user@example.local", "password": PASSWORD},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"email": "user@example.local", "password": PASSWORD},
                headers={**HEADERS, "Origin": "https://evil.example"},
            ).status_code
            == 403
        )
        for _ in range(5):
            assert login(client, "wrong password").status_code == 401
        limited = login(client)
        assert limited.status_code == 429
        assert int(limited.headers["Retry-After"]) > 0


def test_bootstrap_claims_only_once():
    from app.auth.service import bootstrap_admin, create_user
    from app.database import database_connection

    with database_connection(write=True) as db:
        db.execute(
            "INSERT INTO projects (id,name,research_topic,project_type,created_at,updated_at) VALUES ('legacy','name','topic','sci','now','now')"
        )
    admin = bootstrap_admin("admin@paperassist.local", PASSWORD)
    assert admin["claimed_project_ids"] == ["legacy"]
    with database_connection() as db:
        assert (
            db.execute("SELECT owner_id FROM projects WHERE id='legacy'").fetchone()[
                "owner_id"
            ]
            == admin["id"]
        )
    with pytest.raises(ValueError):
        bootstrap_admin("other@example.local", PASSWORD)
    with pytest.raises(ValueError):
        create_user("claim@example.local", PASSWORD, claim_legacy=True)


def test_idle_expiry(monkeypatch):
    import time
    from app.database import database_connection

    monkeypatch.setenv("PAPERASSIST_AUTH_IDLE_SECONDS", "1")
    user()
    with TestClient(app) as client:
        assert login(client).status_code == 200
        with database_connection(write=True) as db:
            db.execute("UPDATE sessions SET last_seen_at = %s", (time.time() - 2,))
        assert client.get("/api/v1/auth/me").status_code == 401


def test_password_validation_and_no_http_echo():
    from app.auth.service import create_user

    for password in ("short", "x" * 129):
        with pytest.raises(ValueError):
            create_user("invalid@example.local", password)
    with TestClient(app) as client:
        password = "sensitive" * 20
        response = login(client, password)
        assert password not in response.text


def test_direct_ip_rate_limit():
    with TestClient(app) as client:
        for number in range(30):
            response = client.post(
                "/api/v1/auth/login",
                json={"email": f"missing{number}@example.local", "password": PASSWORD},
                headers=HEADERS,
            )
            assert response.status_code == 401
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"email": "new@example.local", "password": PASSWORD},
                headers={**HEADERS, "X-Forwarded-For": "new-ip"},
            ).status_code
            == 429
        )


def test_bootstrap_claim_failure_rolls_back_account():
    from app.auth.service import bootstrap_admin
    from app.database import database_connection
    from app.storage import StorageError

    with database_connection(write=True) as db:
        db.execute(
            "INSERT INTO projects (id,name,research_topic,project_type,created_at,updated_at) VALUES ('legacy','name','topic','sci','now','now')"
        )
        db.execute(
            "CREATE FUNCTION reject_claim() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'claim failure'; END $$"
        )
        db.execute(
            "CREATE TRIGGER reject_claim BEFORE UPDATE ON projects FOR EACH ROW EXECUTE FUNCTION reject_claim()"
        )
    with pytest.raises(StorageError):
        bootstrap_admin("admin@paperassist.local", PASSWORD)
    with database_connection() as db:
        assert (
            db.execute("SELECT count(*) AS total FROM users").fetchone()["total"] == 0
        )
        assert (
            db.execute("SELECT owner_id FROM projects WHERE id='legacy'").fetchone()[
                "owner_id"
            ]
            is None
        )


def test_cli_requires_interactive_tty(monkeypatch):
    from app.manage_users import read_password

    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(ValueError):
        read_password()


def test_auth_database_errors_are_safe(monkeypatch):
    from app.auth import middleware
    from app.storage import StorageError

    user()
    with TestClient(app) as client:
        assert login(client).status_code == 200

        def fail(token):
            raise StorageError("storage_unavailable", "safe message")

        monkeypatch.setattr(middleware, "resolve_session", fail)
        response = client.get("/api/v1/auth/me")
        assert response.status_code == 503
        assert response.json()["detail"]["message"] == "safe message"
        assert response.headers["cache-control"] == "no-store"


def test_account_updated_at_changes_with_management():
    from app.auth.service import reset_password, set_user_active
    from app.database import database_connection

    account = user()
    with database_connection() as db:
        before = db.execute(
            "SELECT created_at,updated_at FROM users WHERE id = %s", (account["id"],)
        ).fetchone()
    reset_password(account["email"], "another password 123")
    set_user_active(account["email"], False)
    with database_connection() as db:
        after = db.execute(
            "SELECT updated_at FROM users WHERE id = %s", (account["id"],)
        ).fetchone()
    assert after["updated_at"] > before["updated_at"] >= before["created_at"]


def test_non_ascii_csrf_header_rejected():
    user()
    with TestClient(app) as client:
        assert login(client).status_code == 200
        response = client.post(
            "/api/v1/auth/logout",
            headers=[(b"X-PaperAssist-Client", b"web"), (b"X-CSRF-Token", b"\xff")],
        )
        assert response.status_code == 403


def test_upgrade_preserves_entire_legacy_resource_chain(postgres_schema):
    from alembic import command
    from app.database import database_connection, alembic_config, migrate_database

    tables = (
        "projects",
        "files",
        "analysis_setups",
        "analysis_runs",
        "figures",
        "figure_jobs",
        "explanations",
        "explanation_jobs",
        "reports",
    )
    with database_connection(write=True) as db:
        config = alembic_config()
        config.attributes["connection"] = db.raw_connection
        config.attributes["database_config"] = postgres_schema
        command.downgrade(config, "0001_postgresql")
        db.execute(
            "INSERT INTO projects VALUES ('p','legacy','topic','sci','created','updated')"
        )
        db.execute(
            "INSERT INTO files VALUES ('f','p','legacy.xlsx','xlsx',123,'hash','uploaded','parsed',NULL,'{}')"
        )
        db.execute("INSERT INTO analysis_setups VALUES ('f',1,'{}')")
        db.execute("INSERT INTO analysis_runs VALUES ('r','f',1,'v1','completed','{}')")
        db.execute("INSERT INTO figures VALUES ('g','r','v1','{}')")
        db.execute(
            "INSERT INTO figure_jobs (id,analysis_run_id,renderer_version,created_at,job_json) VALUES ('gj','r','v1','created','{}')"
        )
        db.execute("INSERT INTO explanations VALUES ('e','r','g','v1','{}')")
        db.execute(
            "INSERT INTO explanation_jobs (id,analysis_run_id,figure_id,engine_version,created_at,job_json) VALUES ('ej','r','g','v1','created','{}')"
        )
        db.execute("INSERT INTO reports VALUES ('rp','r','e','v1','{}','{}')")
        original = {
            table: [dict(row) for row in db.execute(f"SELECT * FROM {table}")]
            for table in tables
        }
    migrate_database(postgres_schema)
    with database_connection() as db:
        for table in tables:
            rows = [dict(row) for row in db.execute(f"SELECT * FROM {table}")]
            if table == "projects":
                assert rows[0].pop("owner_id") is None
            assert rows == original[table]
        assert (
            db.execute("SELECT count(*) AS total FROM users").fetchone()["total"] == 0
        )


def test_production_requires_origins_and_secure_settings(monkeypatch):
    from app.auth.config import settings

    user()
    monkeypatch.setenv("PAPERASSIST_ENV", "production")
    monkeypatch.setenv("PAPERASSIST_AUTH_TRUSTED_ORIGINS", "")
    with pytest.raises(ValueError):
        settings()
    monkeypatch.setenv(
        "PAPERASSIST_AUTH_TRUSTED_ORIGINS", "https://paperassist.example"
    )
    assert settings().secure
    # Use test DB configuration for the service call; cookie settings are checked directly.


def test_session_database_contains_digest_only():
    import hashlib
    from app.database import database_connection

    user()
    with TestClient(app) as client:
        assert login(client).status_code == 200
        token = client.cookies.get("paperassist_session")
        with database_connection() as db:
            row = db.execute("SELECT token_hash FROM sessions").fetchone()
        assert row["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
        assert row["token_hash"] != token
