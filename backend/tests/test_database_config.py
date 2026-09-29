"""PostgreSQL configuration tests never open a database connection."""

import importlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


TEST_SCHEMA = "pa_test_" + "a" * 32
DEV_URL = "postgresql://app:do-not-print-me@localhost:5432/paperassist_system"
TEST_URL = "postgresql://tester:do-not-print-me@localhost:5432/paperassist_system_test"


def test_database_module_is_available():
    assert importlib.util.find_spec("app.database") is not None, "PostgreSQL database module is required"


@pytest.fixture
def database():
    return importlib.import_module("app.database")


def configured(database, monkeypatch, values):
    monkeypatch.setattr(database, "local_config", lambda: values)
    return database.get_database_config()


def test_development_uses_only_project_database(database, monkeypatch):
    config = configured(database, monkeypatch, {"PAPERASSIST_DATABASE_URL": DEV_URL})
    assert config.environment == "development"
    assert config.schema == "public"
    assert config.url.drivername == "postgresql+psycopg"
    assert config.url.database == "paperassist_system"
    assert "do-not-print-me" not in repr(config)


def test_generic_database_urls_are_never_used(database, monkeypatch):
    with pytest.raises(ValueError, match="PAPERASSIST_DATABASE_URL"):
        configured(database, monkeypatch, {"DATABASE_URL": DEV_URL, "TEST_DATABASE_URL": TEST_URL})


def test_test_environment_uses_only_dedicated_test_url(database, monkeypatch):
    config = configured(database, monkeypatch, {
        "PAPERASSIST_ENV": "test", "PAPERASSIST_DATABASE_URL": DEV_URL,
        "PAPERASSIST_TEST_DATABASE_URL": TEST_URL, "PAPERASSIST_DB_SCHEMA": TEST_SCHEMA,
    })
    assert config.url.database == "paperassist_system_test"
    assert config.schema == TEST_SCHEMA


def test_test_environment_never_falls_back_to_development_url(database, monkeypatch):
    with pytest.raises(ValueError, match="PAPERASSIST_TEST_DATABASE_URL"):
        configured(database, monkeypatch, {
            "PAPERASSIST_ENV": "test", "PAPERASSIST_DATABASE_URL": DEV_URL,
            "PAPERASSIST_DB_SCHEMA": TEST_SCHEMA,
        })


@pytest.mark.parametrize("url", [
    "", "sqlite:///private.db", "not-a-url-do-not-print-me",
    "postgresql://app:do-not-print-me@localhost/postgres",
    "postgresql://app:do-not-print-me@localhost/paperassist_system_test",
    DEV_URL + "?dbname=postgres", DEV_URL + "?service=unrelated",
    DEV_URL + "?host=other-server", DEV_URL + "?options=-csearch_path=public",
    "postgresql+psycopg2://app:do-not-print-me@localhost/paperassist_system",
])
def test_invalid_urls_fail_without_exposing_credentials(database, monkeypatch, url):
    with pytest.raises(ValueError) as raised:
        configured(database, monkeypatch, {"PAPERASSIST_DATABASE_URL": url})
    assert "do-not-print-me" not in str(raised.value)
    assert url not in str(raised.value) if url else True


@pytest.mark.parametrize("schema", ["public", "", "pa_test_short", "pa_test_" + "f" * 31,
                                        "pa_test_" + "f" * 33, "pa_test_" + "G" * 32])
def test_tests_require_a_unique_isolated_schema(database, monkeypatch, schema):
    with pytest.raises(ValueError, match="schema"):
        configured(database, monkeypatch, {
            "PAPERASSIST_ENV": "test", "PAPERASSIST_TEST_DATABASE_URL": TEST_URL,
            "PAPERASSIST_DB_SCHEMA": schema,
        })


@pytest.mark.parametrize("schema", ["unsafe; DROP SCHEMA public", "pg_catalog", "information_schema",
                                    "contains-dash", "a" * 64, 'with"quote'])
def test_schema_identifier_is_validated(database, monkeypatch, schema):
    with pytest.raises(ValueError, match="schema"):
        configured(database, monkeypatch, {
            "PAPERASSIST_DATABASE_URL": DEV_URL, "PAPERASSIST_DB_SCHEMA": schema,
        })


def test_unknown_environment_is_rejected(database, monkeypatch):
    with pytest.raises(ValueError, match="PAPERASSIST_ENV"):
        configured(database, monkeypatch, {"PAPERASSIST_ENV": "testing", "PAPERASSIST_DATABASE_URL": DEV_URL})


def test_direct_config_creation_cannot_bypass_database_guard(database):
    with pytest.raises(ValueError):
        database.DatabaseConfig("test", DEV_URL, TEST_SCHEMA)


@pytest.mark.parametrize('query', [
    'dbname=unrelated_project', 'host=other-server', 'service=unrelated',
    'options=-csearch_path=public',
])
def test_schema_fixture_rejects_url_redirection_before_creating_engine(database, monkeypatch, tmp_path, query):
    import sqlalchemy
    from app import config
    from conftest import postgres_schema

    monkeypatch.setattr(config, 'local_config', lambda: {'PAPERASSIST_TEST_DATABASE_URL': TEST_URL + '?' + query})

    def unexpected_engine(*args, **kwargs):
        raise AssertionError('Unsafe fixture URL reached create_engine before validation.')

    monkeypatch.setattr(sqlalchemy, 'create_engine', unexpected_engine)
    request = SimpleNamespace(path=Path('test_integration.py'))
    fixture = postgres_schema.__wrapped__(request, monkeypatch, tmp_path)
    try:
        with pytest.raises(ValueError, match='unsupported connection options'):
            next(fixture)
    finally:
        fixture.close()


def test_schema_preserves_nine_tables_and_uses_job_sequences(database):
    schema = importlib.import_module("app.db_schema")
    assert set(schema.metadata.tables) == {
        "projects", "files", "analysis_setups", "analysis_runs", "figures", "figure_jobs",
        "explanations", "explanation_jobs", "reports",
    }
    for name in ("figure_jobs", "explanation_jobs"):
        table = schema.metadata.tables[name]
        assert table.c.seq.identity is not None
        assert table.c.id.primary_key
        assert str(table.c.job_json.type) == "TEXT"


def test_alembic_has_one_known_head(database):
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(database.alembic_config())
    assert script.get_heads() == [database.SCHEMA_HEAD]
