"""Real PostgreSQL privilege boundary tests use the isolated test fixture."""
import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.database import (database_connection, migration_connection,
                          get_migration_database_config, verify_runtime_permissions)


def test_runtime_role_privileges_are_minimal(postgres_schema):
    with database_connection() as db:
        verify_runtime_permissions(db.raw_connection, db.config)


@pytest.mark.parametrize('statement', [
    'CREATE TABLE runtime_ddl_probe (id integer)',
    'ALTER TABLE projects ADD COLUMN runtime_probe integer',
    'DROP TABLE projects CASCADE',
    'TRUNCATE projects CASCADE',
    "UPDATE alembic_version SET version_num = 'probe'",
    'DELETE FROM alembic_version',
    "INSERT INTO alembic_version VALUES ('probe')",
])
def test_postgresql_rejects_runtime_ddl_and_version_writes(postgres_schema, statement):
    with pytest.raises(SQLAlchemyError):
        with database_connection(write=True) as db:
            db.execute(statement)


def test_migration_role_retains_transactional_ddl(postgres_schema):
    config = get_migration_database_config()
    with pytest.raises(RuntimeError, match='rollback probe'):
        with migration_connection(config=config) as db:
            db.execute('CREATE TABLE migration_rollback_probe (id integer)')
            raise RuntimeError('rollback probe')
    with migration_connection(write=False, config=config) as db:
        assert db.execute("SELECT to_regclass('migration_rollback_probe') AS table_name").fetchone()['table_name'] is None


def test_runtime_dml_works(postgres_schema):
    with database_connection(write=True) as db:
        db.execute("INSERT INTO users (id, email, password_hash, role, active, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                   ('permissions-user', 'permissions@example.invalid', 'unused', 'user', True, 1.0, 1.0))
        db.execute("INSERT INTO projects (id, name, research_topic, project_type, created_at, updated_at, owner_id) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                   ('permissions-project', 'probe', '', 'sci', 'same', 'same', 'permissions-user'))
        db.execute("UPDATE projects SET name=%s WHERE id=%s", ('updated', 'permissions-project'))
        assert db.execute("SELECT name FROM projects WHERE id=%s", ('permissions-project',)).fetchone()['name'] == 'updated'
        db.execute("DELETE FROM projects WHERE id=%s", ('permissions-project',))


def test_external_connection_without_transaction_commits_migration(postgres_schema):
    from alembic import command
    from sqlalchemy import create_engine
    from app.database import alembic_config
    config = get_migration_database_config()
    engine = create_engine(config.url)
    settings = alembic_config()
    settings.attributes['database_config'] = config
    try:
        with engine.connect() as connection:
            settings.attributes['connection'] = connection
            command.downgrade(settings, '0004_language_preferences')
        with migration_connection(write=False, config=config) as db:
            assert db.execute('SELECT version_num FROM alembic_version').fetchone()['version_num'] == '0004_language_preferences'
        with engine.connect() as connection:
            settings.attributes['connection'] = connection
            command.upgrade(settings, 'head')
        with migration_connection(write=False, config=config) as db:
            assert db.execute('SELECT version_num FROM alembic_version').fetchone()['version_num'] == '0005_ownership_indexes'
    finally:
        engine.dispose()
