"""One-time local PostgreSQL role separation; passwords never enter argv/logs.

Run through setup-database-roles.cmd. This prepares roles and credentials only;
schema upgrades remain a separate, explicit operation.
"""
from __future__ import annotations

from datetime import datetime, timezone
import getpass
import os
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from dotenv import dotenv_values
from psycopg import Error as PsycopgError
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool


PAIRS = (
    ("PAPERASSIST_DATABASE_URL", "PAPERASSIST_MIGRATION_DATABASE_URL", "paperassist_system", "paperassist_runtime"),
    ("PAPERASSIST_TEST_DATABASE_URL", "PAPERASSIST_TEST_MIGRATION_DATABASE_URL", "paperassist_system_test", "paperassist_test_runtime"),
)


def replace_settings(source: str, updates: dict[str, str], remove: set[str] | None = None) -> str:
    """Preserve unrelated local settings; remove duplicate managed definitions."""
    remaining = dict(updates)
    managed = set(updates) | (remove or set())
    result = []
    for line in source.splitlines():
        stripped = line.strip()
        candidate = stripped.removeprefix("export ").split("=", 1)[0].strip()
        if "=" in stripped and candidate in managed:
            if candidate in remaining:
                result.append(f"{candidate}='{remaining.pop(candidate)}'")
        else:
            result.append(line)
    result.extend(f"{key}='{value}'" for key, value in remaining.items())
    return "\n".join(result) + "\n"


def write_private(path: Path, content: str) -> None:
    # Same directory means replace is atomic on the same volume. Windows access
    # follows the user's existing backend directory ACL; files stay Git-ignored.
    temporary = path.with_name(path.name + ".writing")
    with temporary.open("w", encoding="utf-8", newline="\n") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def connect_engine(url):
    return create_engine(url, poolclass=NullPool, hide_parameters=True,
                         connect_args={"connect_timeout": 5})


def validate_owner_url(value: str | None, database: str):
    if not value:
        raise ValueError("Migration owner URL is missing.")
    url = make_url(value)
    # This local bootstrap intentionally disallows routing/query options.
    if (url.drivername not in {"postgresql", "postgresql+psycopg"}
            or url.database != database or url.host not in {"localhost", "127.0.0.1", "::1"}
            or url.query or not url.username or not url.password):
        raise ValueError("Bootstrap requires an explicit local owner URL without query options.")
    return url.set(drivername="postgresql+psycopg")


def run(progress=lambda phase: None) -> None:
    from app.database import DatabaseConfig, grant_runtime_access, verify_runtime_permissions

    progress('local_configuration')
    env_path = BACKEND / ".env"
    migration_path = BACKEND / ".env.migrations"
    pending_path = BACKEND / ".env.runtime.pending"
    watched = {key for pair in PAIRS for key in pair[:2]} | {"PAPERASSIST_ENV", "PAPERASSIST_DB_SCHEMA"}
    if any(key in os.environ for key in watched):
        raise ValueError("Clear PaperAssist database environment overrides before local bootstrap.")
    original = env_path.read_text(encoding="utf-8-sig")
    current = dotenv_values(env_path, encoding="utf-8-sig", interpolate=False)
    migrations = dotenv_values(migration_path, encoding="utf-8-sig", interpolate=False)
    pending = dotenv_values(pending_path, encoding="utf-8-sig", interpolate=False) if pending_path.exists() else {}
    if current.get("PAPERASSIST_ENV", "development") != "development" or current.get("PAPERASSIST_DB_SCHEMA", "public") != "public":
        raise ValueError("Local bootstrap only supports development/public.")

    targets = []
    for runtime_key, migration_key, database, runtime_role in PAIRS:
        owner_url = validate_owner_url(migrations.get(migration_key) or current.get(runtime_key), database)
        saved_runtime = pending.get(runtime_key) or current.get(runtime_key)
        saved_url = make_url(saved_runtime) if saved_runtime else None
        reusable = saved_url is not None and saved_url.username == runtime_role
        runtime_url = saved_url if reusable else owner_url.set(username=runtime_role, password=secrets.token_urlsafe(36))
        if (runtime_url.host, runtime_url.port or 5432, runtime_url.database) != (owner_url.host, owner_url.port or 5432, database):
            raise ValueError("Saved runtime target differs from migration target.")
        if owner_url.username == runtime_role or runtime_url.query:
            raise ValueError("Separate local owner and runtime accounts are required.")
        targets.append((owner_url, runtime_url, reusable))
    if len({(o.host, o.port or 5432) for o, _, _ in targets}) != 1:
        raise ValueError("Both project databases must use the same local PostgreSQL instance.")

    # Check existing owner credentials before requesting administrative credentials.
    for index, (owner, _, _) in enumerate(targets):
        progress('migration_owner_development' if index == 0 else 'migration_owner_test')
        engine = connect_engine(owner)
        try:
            with engine.connect() as connection:
                valid = connection.exec_driver_sql("""SELECT current_user = r.rolname
                    FROM pg_database d JOIN pg_roles r ON r.oid=d.datdba
                    WHERE d.datname=current_database()""").scalar_one()
                if not valid:
                    raise ValueError("Configured migration account must own its project database.")
        finally:
            engine.dispose()

    print("Targets: paperassist_system / paperassist_system_test, schema public.")
    print("Create/reuse only paperassist_runtime and paperassist_test_runtime. No schema upgrade.")
    admin_user = input("PostgreSQL administrator [postgres]: ").strip() or "postgres"
    admin_password = getpass.getpass("PostgreSQL administrator password (hidden): ")
    progress('admin_authentication')
    admin_url = targets[0][0].set(username=admin_user, password=admin_password)
    admin_engine = connect_engine(admin_url)
    try:
        with admin_engine.begin() as connection:
            progress('admin_permissions')
            capable = connection.exec_driver_sql("SELECT rolsuper FROM pg_roles WHERE rolname=current_user").scalar_one()
            if not capable:
                raise ValueError("Local bootstrap requires a PostgreSQL administrator (superuser).")
            progress('existing_roles')
            for _, runtime, reusable in targets:
                exists = connection.exec_driver_sql("SELECT 1 FROM pg_roles WHERE rolname=%s", (runtime.username,)).first()
                if exists and not reusable:
                    raise ValueError("A runtime role already exists without matching local credentials; refusing to take it over.")
            progress('save_configuration_backup')
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup_dir = BACKEND / "backups" / ("role-config-" + stamp)
            backup_dir.mkdir(parents=True, exist_ok=False)
            write_private(backup_dir / ".env", original)
            migration_text = migration_path.read_text(encoding="utf-8-sig") if migration_path.exists() else "# Migration credentials. Never load into the web service.\n"
            if migration_path.exists():
                write_private(backup_dir / ".env.migrations", migration_text)
            owner_updates = {pair[1]: target[0].render_as_string(hide_password=False) for pair, target in zip(PAIRS, targets)}
            runtime_updates = {pair[0]: target[1].render_as_string(hide_password=False) for pair, target in zip(PAIRS, targets)}
            # Save recovery credentials before the role transaction commits. A
            # retry authenticates existing roles; it never resets their password.
            write_private(migration_path, replace_settings(migration_text, owner_updates))
            write_private(pending_path, replace_settings(original, runtime_updates, set(owner_updates)))
            from psycopg import sql
            progress('create_runtime_roles')
            for _, runtime, _ in targets:
                exists = connection.exec_driver_sql("SELECT 1 FROM pg_roles WHERE rolname=%s", (runtime.username,)).first()
                if not exists:
                    raw = connection.connection.driver_connection
                    with raw.cursor() as cursor:
                        cursor.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD {}").format(sql.Identifier(runtime.username), sql.Literal(runtime.password)))
    finally:
        admin_engine.dispose()
        admin_password = None

    for index, (owner, runtime, _) in enumerate(targets):
        progress('apply_permissions_development' if index == 0 else 'apply_permissions_test')
        owner_engine, runtime_engine = connect_engine(owner), connect_engine(runtime)
        try:
            with owner_engine.begin() as connection:
                quote = connection.dialect.identifier_preparer.quote
                connection.exec_driver_sql(f"REVOKE ALL ON DATABASE {quote(owner.database)} FROM PUBLIC")
                connection.exec_driver_sql(f"REVOKE ALL ON DATABASE {quote(owner.database)} FROM {quote(runtime.username)}")
                connection.exec_driver_sql(f"GRANT CONNECT ON DATABASE {quote(owner.database)} TO {quote(runtime.username)}")
                connection.exec_driver_sql("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
                if index == 0:
                    migration_config = DatabaseConfig("development", owner, "public", purpose="migration")
                    runtime_config = DatabaseConfig("development", runtime, "public")
                    grant_runtime_access(connection, migration_config, runtime_config)
            # CONNECT must be granted before authenticating the new role: these
            # databases intentionally have PUBLIC CONNECT revoked.
            progress('verify_runtime_development' if index == 0 else 'verify_runtime_test')
            with runtime_engine.connect() as connection:
                state = connection.exec_driver_sql("""SELECT current_user, current_database(),
                    rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls
                    OR EXISTS(SELECT 1 FROM pg_auth_members WHERE member=r.oid)
                    OR has_database_privilege(current_user,current_database(),'CREATE')
                    OR has_database_privilege(current_user,current_database(),'TEMP')
                    OR EXISTS(SELECT 1 FROM pg_namespace WHERE has_schema_privilege(current_user,oid,'CREATE'))
                    OR EXISTS(SELECT 1 FROM pg_database WHERE datdba=r.oid)
                    OR EXISTS(SELECT 1 FROM pg_namespace WHERE nspowner=r.oid)
                    OR EXISTS(SELECT 1 FROM pg_class WHERE relowner=r.oid) AS dangerous
                    FROM pg_roles r WHERE rolname=current_user""").one()
                if tuple(state) != (runtime.username, owner.database, False):
                    raise ValueError("Runtime role identity or privileges are unsafe.")
                if index == 0:
                    verify_runtime_permissions(connection, runtime_config)
        finally:
            owner_engine.dispose()
            runtime_engine.dispose()

    progress('verify_cross_database_isolation')
    for index, (_, runtime, _) in enumerate(targets):
        engine = connect_engine(runtime)
        try:
            with engine.connect() as connection:
                if connection.exec_driver_sql("SELECT has_database_privilege(current_user,%s,'CONNECT')", (PAIRS[1 - index][2],)).scalar_one():
                    raise ValueError("Runtime role must not connect to the other project database.")
        finally:
            engine.dispose()

    # Switch the app only after both databases have passed permission checks.
    progress('activate_runtime_configuration')
    os.replace(pending_path, env_path)
    print("Role setup complete. Runtime credentials: backend/.env; migration credentials: backend/.env.migrations.")
    print("No tables/data were migrated. Return to the development task for checks and explicit upgrade.")


def main() -> int:
    phase = 'starting'
    def progress(value):
        nonlocal phase
        phase = value
        print('Step: ' + phase, flush=True)
    try:
        run(progress)
    except (SQLAlchemyError, PsycopgError, ValueError, OSError, EOFError, KeyboardInterrupt) as error:
        print("Setup did not complete. Check local configuration, administrator credentials and permissions.", file=sys.stderr)
        print('Failed stage: ' + phase, file=sys.stderr)
        driver_error = getattr(error, 'orig', error)
        state = getattr(driver_error, 'sqlstate', None)
        if isinstance(state, str) and len(state) == 5 and state.isascii() and state.isalnum():
            print('PostgreSQL SQLSTATE: ' + state, file=sys.stderr)
        if phase == 'admin_authentication':
            print('Administrator login failed. Use the PostgreSQL password, not the PaperAssist web login password.', file=sys.stderr)
        elif phase == 'admin_permissions':
            print('This account needs PostgreSQL superuser privileges for this bootstrap.', file=sys.stderr)
        print("No exception/URL is printed. Keep .env.runtime.pending if present, correct the cause and rerun; the script never resets an existing role password.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
