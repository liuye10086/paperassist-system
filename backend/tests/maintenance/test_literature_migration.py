"""Exercise the actual 0029 -> 0030 DDL while preserving existing business rows."""
from alembic import command
import pytest

from app.db.database import (migration_connection, database_connection, alembic_config,
                             get_migration_database_config, verify_runtime_permissions)
from tests.db.test_task_schema import seed_owner


@pytest.mark.initial_revision('0029_statistics_execution')
def test_incremental_literature_migration_preserves_old_rows_and_indexes():
    with migration_connection(write=True) as db:
        config = alembic_config()
        config.attributes.update(connection=db.raw_connection,database_config=get_migration_database_config())
        seed_owner(db)
        tables = [r['tablename'] for r in db.execute('SELECT tablename FROM pg_tables WHERE schemaname=current_schema()')
                  if r['tablename'] != 'alembic_version']
        rows = {t:db.execute('SELECT * FROM '+t).fetchall() for t in tables}
        indexes = {r['indexname']:r['indexdef'] for r in db.execute('SELECT * FROM pg_indexes WHERE schemaname=current_schema()')}
        command.upgrade(config,'0030_literature_search')
        assert all(db.execute('SELECT * FROM '+t).fetchall() == v for t,v in rows.items())
        after = {r['indexname']:r['indexdef'] for r in db.execute('SELECT * FROM pg_indexes WHERE schemaname=current_schema()')}
        assert all(after[k] == v for k,v in indexes.items())
        # The historical 0029 -> 0030 comparison above remains exact. Runtime
        # permissions and the current audit additionally require the new head.
        command.upgrade(config, 'head')
    with database_connection() as db:
        verify_runtime_permissions(db.raw_connection,db.config)
        from app.maintenance.database_audit import audit_database
        result = audit_database(db)
        assert result['ok'],{k:v for k,v in result.items() if k not in ('data_checks','tables')}
        assert db.execute("SELECT id FROM projects WHERE id='p'").fetchone()
