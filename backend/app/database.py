"""Validated PostgreSQL connections and explicit Alembic migrations.

Application connections never create tables. Development and test use separate
databases, and tests must additionally select a unique, disposable schema.
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import lru_cache
import hashlib
from pathlib import Path
import re
from typing import Any, Iterator

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, CursorResult, Engine, URL, make_url
from sqlalchemy.exc import SQLAlchemyError

from .config import local_config


SCHEMA_HEAD = "0001_postgresql"
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

    def __post_init__(self):
        if self.environment not in {"development", "test", "production"}:
            raise ValueError("PAPERASSIST_ENV must be development, test, or production.")
        try:
            parsed = make_url(self.url)
        except (SQLAlchemyError, TypeError, ValueError):
            raise ValueError("PaperAssist requires a valid PostgreSQL database URL.") from None
        if parsed.drivername not in {"postgresql", "postgresql+psycopg"}:
            raise ValueError("PaperAssist requires PostgreSQL with the psycopg driver.")
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


def migrate_database(config: DatabaseConfig | None = None) -> None:
    config = config or get_database_config()
    with database_connection(write=True, config=config) as connection:
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
    except (SQLAlchemyError, ValueError):
        print("数据库操作失败，请检查专用 PostgreSQL 配置、权限和迁移版本。", file=sys.stderr)
        return 1
    print(f"PaperAssist database schema is current ({SCHEMA_HEAD}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
