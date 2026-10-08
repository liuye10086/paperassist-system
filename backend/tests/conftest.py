from contextlib import contextmanager
import re
from uuid import uuid4

import pytest


@pytest.fixture(autouse=True)
def isolate_cloud_worker(monkeypatch):
    # Tests control cloud completion explicitly; never touch a developer's live API.
    monkeypatch.setenv('PAPERASSIST_PLOT_WORKER_ENABLED', '0')
    monkeypatch.setenv('OPENAI_API_KEY', '')
    monkeypatch.setenv('OPENAI_API_KEY_FILE', '')
    monkeypatch.setenv('PAPERASSIST_EXPLANATION_POLICY_FILE', '')
    monkeypatch.setenv('PAPERASSIST_PLOT_POLICY_FILE', '')
    monkeypatch.setenv('PAPERASSIST_AUTH_TRUSTED_ORIGINS', 'http://testserver')


@pytest.fixture(autouse=True)
def postgres_schema(request, monkeypatch, tmp_path):
    """Run every integration test in its own explicitly migrated PostgreSQL schema."""
    if request.path.name == 'test_database_config.py':
        yield None
        return

    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool
    from app.core.config import local_config
    from app.db.database import DatabaseConfig, get_database_config, get_migration_database_config, migrate_database, validate_database_pair

    url = local_config().get('PAPERASSIST_TEST_DATABASE_URL')
    if not url:
        pytest.fail('PAPERASSIST_TEST_DATABASE_URL is required; SQLite fallback is forbidden.')
    schema = 'pa_test_' + uuid4().hex
    assert re.fullmatch(r'pa_test_[0-9a-f]{32}', schema)
    # Validate every connection option before even constructing an engine.
    config = DatabaseConfig('test', url, schema)
    monkeypatch.setenv('PAPERASSIST_ENV', 'test')
    monkeypatch.setenv('PAPERASSIST_DB_SCHEMA', schema)
    monkeypatch.setenv('PAPERASSIST_DATA_DIR', str(tmp_path / 'data'))
    assert get_database_config() == config
    migration_config = get_migration_database_config()
    validate_database_pair(migration_config, config)

    engine = create_engine(migration_config.url, poolclass=NullPool)
    quoted_schema = engine.dialect.identifier_preparer.quote(schema)
    created = False
    try:
        with engine.begin() as connection:
            assert connection.exec_driver_sql('SELECT current_database()').scalar_one() == 'paperassist_system_test'
            connection.exec_driver_sql(f'CREATE SCHEMA {quoted_schema}')
        created = True
        migrate_database(migration_config)
        yield config
    finally:
        try:
            # This exact schema was created above; never drop arbitrary environment input.
            if created and re.fullmatch(r'pa_test_[0-9a-f]{32}', schema):
                with engine.begin() as connection:
                    assert connection.exec_driver_sql('SELECT current_database()').scalar_one() == 'paperassist_system_test'
                    connection.exec_driver_sql(f'DROP SCHEMA {quoted_schema} CASCADE')
        finally:
            engine.dispose()


@pytest.fixture
def postgres_migration_config(postgres_schema):
    from app.db.database import get_migration_database_config

    config = get_migration_database_config()
    assert config.schema == postgres_schema.schema
    return config


@pytest.fixture
def reject_database_write(postgres_schema):
    """Inject a real PostgreSQL transaction failure, then restore normal writes."""
    from app.db.database import migration_connection

    @contextmanager
    def rejecting(table, event='INSERT'):
        assert table in {'files', 'analysis_setups', 'analysis_runs', 'figures'}
        assert event in {'INSERT', 'UPDATE'}
        with migration_connection(write=True) as db:
            db.execute("""CREATE FUNCTION reject_test_write() RETURNS trigger
                LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'test write failure'; END $$""")
            db.execute(f'CREATE TRIGGER reject_test_write BEFORE {event} ON {table} '
                       'FOR EACH ROW EXECUTE FUNCTION reject_test_write()')
        try:
            yield
        finally:
            with migration_connection(write=True) as db:
                db.execute(f'DROP TRIGGER reject_test_write ON {table}')
                db.execute('DROP FUNCTION reject_test_write()')

    return rejecting
