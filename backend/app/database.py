"""Validated PostgreSQL connections and explicit Alembic migrations.

Application connections never create tables. Development and test use separate
databases, and tests must additionally select a unique, disposable schema.
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import lru_cache
import hashlib
import os
import json
import sys

from dotenv import dotenv_values
from pathlib import Path
import re
from typing import Any, Iterator

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, CursorResult, Engine, URL, make_url
from sqlalchemy.exc import SQLAlchemyError

from .config import local_config


SCHEMA_HEAD = "0005_ownership_indexes"
_SCHEMA_NAME = re.compile(r"[a-z_][a-z0-9_]{0,62}\Z")
_TEST_SCHEMA = re.compile(r"pa_test_[0-9a-f]{32}\Z")
_CONNECTION_OPTIONS = frozenset({
    "sslmode", "sslrootcert", "sslcert", "sslkey", "sslpassword",
    "sslcrl", "sslcrldir", "sslsni", "connect_timeout", "application_name",
    "channel_binding", "target_session_attrs", "gssencmode",
})


@dataclass(frozen=True)
class DatabaseConfig:
    environment: str
    url: URL | str = field(repr=False)
    schema: str = "public"
    purpose: str = "runtime"

    def __post_init__(self):
        if self.purpose not in {"runtime", "migration"}:
            raise ValueError("Database purpose must be runtime or migration.")
        if self.environment not in {"development", "test", "production"}:
            raise ValueError("PAPERASSIST_ENV must be development, test, or production.")
        try:
            parsed = make_url(self.url)
        except (SQLAlchemyError, TypeError, ValueError):
            raise ValueError("PaperAssist requires a valid PostgreSQL database URL.") from None
        if parsed.drivername not in {"postgresql", "postgresql+psycopg"}:
            raise ValueError("PaperAssist requires PostgreSQL with the psycopg driver.")
        if not parsed.username or not parsed.host:
            raise ValueError("Database URL requires an explicit host and username.")
        expected = "paperassist_system_test" if self.environment == "test" else "paperassist_system"
        if parsed.database != expected:
            raise ValueError(f"PaperAssist {self.environment} requires database {expected}.")
        if set(parsed.query) - _CONNECTION_OPTIONS:
            raise ValueError("Database URL contains unsupported connection options.")
        if not isinstance(self.schema, str) or not _SCHEMA_NAME.fullmatch(self.schema):
            raise ValueError("PAPERASSIST_DB_SCHEMA must be a safe lowercase schema identifier.")
        if self.schema.startswith("pg_") or self.schema == "information_schema":
            raise ValueError("PAPERASSIST_DB_SCHEMA cannot select a PostgreSQL system schema.")
        if self.environment == "test" and not _TEST_SCHEMA.fullmatch(self.schema):
            raise ValueError("Test schema must be pa_test_ followed by 32 lowercase UUID hex digits.")
        object.__setattr__(self, "url", parsed.set(drivername="postgresql+psycopg"))


def get_database_config() -> DatabaseConfig:
    values = local_config()
    environment = values.get("PAPERASSIST_ENV", "development")
    key = "PAPERASSIST_TEST_DATABASE_URL" if environment == "test" else "PAPERASSIST_DATABASE_URL"
    url = values.get(key)
    if not url or not isinstance(url, str) or not url.strip():
        raise ValueError(f"{key} must be configured; SQLite fallback is not supported.")
    return DatabaseConfig(environment, url, values.get("PAPERASSIST_DB_SCHEMA", "public"))


def _endpoint(config):
    return ((config.url.host or "").lower(), config.url.port or 5432, config.url.database)


def validate_database_pair(migration_config, runtime_config):
    if migration_config.purpose != "migration" or runtime_config.purpose != "runtime":
        raise ValueError("Separate migration and runtime configurations are required.")
    if (migration_config.environment != runtime_config.environment
            or migration_config.schema != runtime_config.schema
            or _endpoint(migration_config) != _endpoint(runtime_config)
            or migration_config.url.username == runtime_config.url.username):
        raise ValueError("Migration and runtime must share environment, schema and endpoint with distinct users.")


def get_migration_database_config() -> DatabaseConfig:
    values = local_config()
    environment = values.get("PAPERASSIST_ENV", "development")
    credentials = {**dotenv_values(Path(__file__).resolve().parents[1] / '.env.migrations',
                                  encoding='utf-8-sig', interpolate=False), **os.environ}
    key = "PAPERASSIST_TEST_MIGRATION_DATABASE_URL" if environment == "test" else "PAPERASSIST_MIGRATION_DATABASE_URL"
    url = credentials.get(key)
    if not isinstance(url, str) or not url.strip():
        raise ValueError(f"{key} must be configured; runtime credentials are never used for migration.")
    config = DatabaseConfig(environment, url, values.get("PAPERASSIST_DB_SCHEMA", "public"), "migration")
    validate_database_pair(config, get_database_config())
    return config


@lru_cache(maxsize=8)
def _engine_for_url(url: URL) -> Engine:
    return create_engine(
        url, pool_pre_ping=True, hide_parameters=True,
        connect_args={"connect_timeout": 10},
    )


def get_engine(config: DatabaseConfig | None = None) -> Engine:
    return _engine_for_url((config or get_database_config()).url)


class DatabaseResult:
    """Expose mapping rows while retaining DML row counts."""

    def __init__(self, result: CursorResult):
        self.rowcount = result.rowcount
        self._rows = result.mappings() if result.returns_rows else None

    def fetchone(self):
        return self._rows.fetchone() if self._rows is not None else None

    def fetchall(self):
        return self._rows.fetchall() if self._rows is not None else []

    def __iter__(self):
        return iter(self._rows) if self._rows is not None else iter(())


class DatabaseConnection:
    def __init__(self, connection: Connection, config: DatabaseConfig):
        self.raw_connection = connection
        self.config = config

    def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> DatabaseResult:
        return DatabaseResult(self.raw_connection.exec_driver_sql(sql, parameters))


class SchemaVersionError(SQLAlchemyError):
    """The selected schema has not been migrated to this application's head."""


def ensure_schema_current(connection: DatabaseConnection) -> None:
    # Fully qualify the relation lookup: another schema's version table must not
    # accidentally make an empty or older schema appear usable.
    table = connection.execute(
        "SELECT pg_catalog.to_regclass(%s) AS version_table",
        (f'"{connection.config.schema}"."alembic_version"',),
    ).fetchone()
    if table["version_table"] is None:
        raise SchemaVersionError("数据库尚未初始化，请先执行 python -m app.database upgrade。")
    rows = connection.execute("SELECT version_num FROM alembic_version").fetchall()
    if len(rows) != 1 or rows[0]["version_num"] != SCHEMA_HEAD:
        raise SchemaVersionError("数据库版本不兼容，请先执行 python -m app.database upgrade。")


def _set_schema(connection: Connection, schema: str) -> None:
    exists = connection.exec_driver_sql(
        "SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname = %s", (schema,),
    ).first()
    if exists is None:
        raise SchemaVersionError("目标数据库 schema 不存在，请先创建专用 schema 后执行迁移。")
    # Omitting public prevents accidental reads or writes in a different schema.
    connection.exec_driver_sql("SELECT pg_catalog.set_config('search_path', %s, true)", (schema,))


def _write_lock(connection: Connection, config: DatabaseConfig) -> None:
    digest = hashlib.sha256(f"paperassist:{config.url.database}:{config.schema}".encode()).digest()
    key = int.from_bytes(digest[:8], byteorder="big", signed=True)
    connection.exec_driver_sql("SELECT pg_catalog.pg_advisory_xact_lock(%s)", (key,))


@contextmanager
def database_connection(
    write: bool = False, config: DatabaseConfig | None = None,
) -> Iterator[DatabaseConnection]:
    config = config or get_database_config()
    if config.purpose != "runtime":
        raise ValueError("Business connections require runtime purpose.")
    isolation = "READ COMMITTED" if write else "REPEATABLE READ"
    with get_engine(config).connect().execution_options(isolation_level=isolation) as connection:
        with connection.begin():
            if not write:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            _set_schema(connection, config.schema)
            if write:
                # SQLite previously serialized writes with BEGIN IMMEDIATE.
                # Take the lock before any business reads at READ COMMITTED so
                # a waiting writer observes the preceding writer's commit.
                _write_lock(connection, config)
            yield DatabaseConnection(connection, config)


def alembic_config() -> Config:
    backend = Path(__file__).resolve().parents[1]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    return config



def validate_migration_connection(connection: Connection, config: DatabaseConfig) -> None:
    if config.purpose != "migration":
        raise ValueError("Schema changes require migration purpose.")
    actual = DatabaseConfig(config.environment, connection.engine.url, config.schema, "migration")
    if _endpoint(actual) != _endpoint(config) or actual.url.username != config.url.username:
        raise ValueError("Migration connection does not match configured endpoint and user.")
    row = connection.exec_driver_sql(
        "SELECT current_database(), current_user, session_user").one()
    if tuple(row) != (config.url.database, config.url.username, config.url.username):
        raise ValueError("Migration server identity does not match configuration.")
    _set_schema(connection, config.schema)
    _write_lock(connection, config)


@contextmanager
def migration_connection(write: bool = True, config: DatabaseConfig | None = None):
    config = config or get_migration_database_config()
    if config.purpose != "migration":
        raise ValueError("Administrative connections require migration purpose.")
    with get_engine(config).connect().execution_options(isolation_level="READ COMMITTED") as connection:
        with connection.begin():
            if not write:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            validate_migration_connection(connection, config)
            yield DatabaseConnection(connection, config)


def grant_runtime_access(connection: Connection, migration_config: DatabaseConfig,
                         runtime_config: DatabaseConfig) -> None:
    # Future objects receive privileges at the end of each explicit Alembic
    # operation, using the current metadata allowlist. No broad default-table
    # privileges are installed: version and unrelated tables remain excluded.
    from .db_schema import metadata
    validate_database_pair(migration_config, runtime_config)
    quote = connection.dialect.identifier_preparer.quote_identifier
    role, schema = quote(runtime_config.url.username), quote(runtime_config.schema)
    connection.exec_driver_sql(f"GRANT USAGE ON SCHEMA {schema} TO {role}")
    for name in metadata.tables:
        if connection.exec_driver_sql("SELECT pg_catalog.to_regclass(%s)",
            (f'"{runtime_config.schema}"."{name}"',)).scalar_one() is None:
            continue
        connection.exec_driver_sql(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {schema}.{quote(name)} TO {role}")
    connection.exec_driver_sql(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {schema} TO {role}")
    version = f"{schema}.alembic_version"
    if connection.exec_driver_sql("SELECT pg_catalog.to_regclass(%s)",
        (f'"{runtime_config.schema}"."alembic_version"',)).scalar_one() is None:
        return
    connection.exec_driver_sql(f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE {version} FROM {role}")
    connection.exec_driver_sql(f"GRANT SELECT ON TABLE {version} TO {role}")


def verify_runtime_permissions(connection: Connection, runtime_config: DatabaseConfig) -> None:
    if runtime_config.purpose != "runtime":
        raise ValueError("Permission verification requires runtime purpose.")
    actual = DatabaseConfig(runtime_config.environment, connection.engine.url, runtime_config.schema)
    if _endpoint(actual) != _endpoint(runtime_config) or actual.url.username != runtime_config.url.username:
        raise ValueError("Runtime connection identity mismatch.")
    row = connection.exec_driver_sql("""
        SELECT current_database() AS database, current_user AS username, session_user AS session,
               r.rolsuper OR r.rolcreatedb OR r.rolcreaterole OR r.rolreplication OR r.rolbypassrls AS dangerous,
               EXISTS (SELECT 1 FROM pg_catalog.pg_auth_members WHERE member=r.oid) AS membership,
               has_database_privilege(current_user, current_database(), 'CREATE') AS db_create,
               has_database_privilege(current_user, current_database(), 'TEMP') AS db_temp,
               EXISTS (SELECT 1 FROM pg_catalog.pg_namespace WHERE has_schema_privilege(current_user, oid, 'CREATE')) AS schema_create,
               EXISTS (SELECT 1 FROM pg_catalog.pg_database WHERE datdba=r.oid)
                 OR EXISTS (SELECT 1 FROM pg_catalog.pg_namespace WHERE nspowner=r.oid)
                 OR EXISTS (SELECT 1 FROM pg_catalog.pg_class WHERE relowner=r.oid) AS owner
        FROM pg_catalog.pg_roles r WHERE rolname=current_user
        """).mappings().one()
    if (row['database'] != runtime_config.url.database or row['username'] != runtime_config.url.username
            or row['session'] != runtime_config.url.username
            or any(row[key] for key in ('dangerous', 'membership', 'db_create', 'db_temp', 'schema_create', 'owner'))):
        raise ValueError("Runtime role has unsafe identity, ownership or administrative permissions.")
    from .db_schema import metadata
    for name in metadata.tables:
        for privilege in ('SELECT', 'INSERT', 'UPDATE', 'DELETE'):
            if not connection.exec_driver_sql(
                "SELECT has_table_privilege(current_user, %s, %s)",
                (f'"{runtime_config.schema}"."{name}"', privilege)).scalar_one():
                raise ValueError("Runtime role is missing business table permissions.")
    if not connection.exec_driver_sql("SELECT has_schema_privilege(current_user, %s, 'USAGE')", (runtime_config.schema,)).scalar_one():
        raise ValueError("Runtime role cannot use its schema.")
    for sequence in connection.exec_driver_sql("SELECT c.oid FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relkind='S'", (runtime_config.schema,)):
        for privilege in ('USAGE', 'SELECT'):
            if not connection.exec_driver_sql("SELECT has_sequence_privilege(current_user, %s, %s)", (sequence[0], privilege)).scalar_one():
                raise ValueError("Runtime role is missing sequence permissions.")
        if connection.exec_driver_sql("SELECT has_sequence_privilege(current_user, %s, 'UPDATE')", (sequence[0],)).scalar_one():
            raise ValueError("Runtime role can reset sequences.")
    for name in metadata.tables:
        for privilege in ('TRUNCATE', 'REFERENCES', 'TRIGGER'):
            if connection.exec_driver_sql("SELECT has_table_privilege(current_user, %s, %s)", (f'"{runtime_config.schema}"."{name}"', privilege)).scalar_one():
                raise ValueError("Runtime role has administrative table permissions.")
    for privilege in ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'):
        if connection.exec_driver_sql("SELECT has_table_privilege(current_user, %s, %s)",
              (f'"{runtime_config.schema}"."alembic_version"', privilege)).scalar_one():
            raise ValueError("Runtime role can modify the schema version table.")


def migration_summary(connection: Connection, config: DatabaseConfig, target_revision: str | None = "head") -> None:
    version = connection.exec_driver_sql("SELECT pg_catalog.to_regclass(%s)",
        (f'"{config.schema}"."alembic_version"',)).scalar_one()
    current = None
    if version is not None:
        current = connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one_or_none()
    from alembic.script import ScriptDirectory
    script = ScriptDirectory.from_config(alembic_config())
    known = {revision.revision for revision in script.walk_revisions()}
    target = script.as_revision_number(target_revision)
    if target is not None and target not in known:
        raise ValueError("Migration target revision is not recognized.")
    if current is not None and current not in known:
        current = "unknown"
    print(json.dumps(dict(environment=config.environment, purpose=config.purpose,
        host=config.url.host, port=config.url.port or 5432, database=config.url.database,
        schema=config.schema, user=config.url.username, current_revision=current,
        target_revision=target), ensure_ascii=True), file=sys.stderr)


def migrate_database(config: DatabaseConfig | None = None) -> None:
    config = config or get_migration_database_config()
    if config.purpose != "migration":
        raise ValueError("Schema changes require migration purpose.")
    runtime = get_database_config()
    validate_database_pair(config, runtime)
    with migration_connection(write=True, config=config) as connection:
        settings = alembic_config()
        settings.attributes["connection"] = connection.raw_connection
        settings.attributes["database_config"] = config
        command.upgrade(settings, "head")
        ensure_schema_current(connection)


def main() -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Explicit PaperAssist PostgreSQL schema migration")
    parser.add_argument("command", choices=["upgrade", "check"])
    arguments = parser.parse_args()
    try:
        if arguments.command == "upgrade":
            migrate_database()
        else:
            with database_connection() as connection:
                ensure_schema_current(connection)
                verify_runtime_permissions(connection.raw_connection, connection.config)
    except (SQLAlchemyError, ValueError):
        print("数据库操作失败，请检查专用 PostgreSQL 配置、权限和迁移版本。", file=sys.stderr)
        return 1
    print(f"PaperAssist database schema is current ({SCHEMA_HEAD}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
