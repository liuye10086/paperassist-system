"""Exercise connection guarantees against an isolated real PostgreSQL schema."""

from app.db.database import migration_connection
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from app.db.database import SCHEMA_HEAD, SchemaVersionError, database_connection, ensure_schema_current, migrate_database
from app.db.schema import metadata


def insert_project(database, project_id="project", name="before"):
    return database.execute(
        "INSERT INTO projects (id, name, research_topic, project_type, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (project_id, name, "topic", "sci", "2026-01-01", "2026-01-01"),
    )


def test_read_connections_are_read_only_repeatable_snapshots(postgres_schema):
    with database_connection(write=True) as writer:
        insert_project(writer)
    with database_connection() as reader:
        assert reader.execute("SHOW transaction_isolation").fetchone()["transaction_isolation"] == "repeatable read"
        assert reader.execute("SHOW transaction_read_only").fetchone()["transaction_read_only"] == "on"
        assert reader.execute("SELECT name FROM projects").fetchone()["name"] == "before"
        with database_connection(write=True) as writer:
            writer.execute("UPDATE projects SET name = %s WHERE id = %s", ("after", "project"))
        assert reader.execute("SELECT name FROM projects").fetchone()["name"] == "before"
    with database_connection() as reader:
        assert reader.execute("SELECT name FROM projects").fetchone()["name"] == "after"
    with pytest.raises(SQLAlchemyError):
        with database_connection() as reader:
            insert_project(reader, "forbidden")


def test_write_connections_commit_and_roll_back_atomically(postgres_schema):
    with database_connection(write=True) as writer:
        assert writer.execute("SHOW transaction_isolation").fetchone()["transaction_isolation"] == "read committed"
        assert insert_project(writer).rowcount == 1
    with pytest.raises(RuntimeError, match="abort"):
        with database_connection(write=True) as writer:
            writer.execute("UPDATE projects SET name = %s", ("rolled back",))
            insert_project(writer, "rolled-back-project")
            raise RuntimeError("abort")
    with database_connection() as reader:
        rows = list(reader.execute("SELECT id, name FROM projects"))
        assert [dict(row) for row in rows] == [{"id": "project", "name": "before"}]


def test_waiting_writer_observes_previous_writer_commit(postgres_schema):
    started = Event()
    acquired = Event()

    def waiting_writer():
        started.set()
        with database_connection(write=True, config=postgres_schema) as writer:
            acquired.set()
            return writer.execute("SELECT name FROM projects WHERE id = %s", ("project",)).fetchone()["name"]

    with ThreadPoolExecutor(max_workers=1) as executor:
        with database_connection(write=True) as first:
            insert_project(first, name="committed first")
            future = executor.submit(waiting_writer)
            assert started.wait(timeout=5)
            assert not acquired.wait(timeout=0.2)
        assert future.result(timeout=5) == "committed first"
        assert acquired.is_set()


def test_migration_is_idempotent_and_matches_core_metadata(postgres_schema, postgres_migration_config):
    with database_connection(write=True) as writer:
        insert_project(writer)
    migrate_database(postgres_migration_config)
    with database_connection() as reader:
        ensure_schema_current(reader)
        inspector = inspect(reader.raw_connection)
        assert set(inspector.get_table_names(schema=postgres_schema.schema)) == set(metadata.tables) | {"alembic_version"}
        for name, table in metadata.tables.items():
            actual = inspector.get_columns(name, schema=postgres_schema.schema)
            assert [column["name"] for column in actual] == list(table.c.keys())
            assert [str(column["type"]) for column in actual] == [str(column.type) for column in table.c]
            assert [column["nullable"] for column in actual] == [column.nullable for column in table.c]
        assert reader.execute("SELECT name FROM projects").fetchone()["name"] == "before"
        assert reader.execute("SELECT version_num FROM alembic_version").fetchone()["version_num"] == SCHEMA_HEAD


def test_schema_version_check_never_repairs_wrong_revision(postgres_schema):
    with migration_connection(write=True) as writer:
        writer.execute("UPDATE alembic_version SET version_num = %s", ("unknown_revision",))
    with pytest.raises(SchemaVersionError):
        with database_connection() as reader:
            ensure_schema_current(reader)
    with database_connection() as reader:
        assert reader.execute("SELECT version_num FROM alembic_version").fetchone()["version_num"] == "unknown_revision"
