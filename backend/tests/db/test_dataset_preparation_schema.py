"""Frozen 0017 definitions preserve old tables and create real workflow relations."""
from alembic import command
from sqlalchemy import inspect
from app.db.database import alembic_config,migration_connection,verify_runtime_permissions
from app.db.schema import metadata
from app.maintenance.database_audit import audit_database
from tests.db.test_task_schema import seed_owner,task_row,insert_row
from tests.db.test_dataset_schema import assert_preserved_indexes


def test_0017_preserves_original_tables_and_json(postgres_schema,postgres_migration_config):
    with migration_connection(config=postgres_migration_config) as db:
        settings=alembic_config()
        settings.attributes.update(connection=db.raw_connection,database_config=postgres_migration_config)
        command.downgrade(settings,'0016_dataset_versions')
        seed_owner(db)
        insert_row(db,'tasks',task_row(input_snapshot={'schema_version':1,'result':{'old':[None,1]}}))
        inspector=inspect(db.raw_connection)
        originals=[name for name in inspector.get_table_names() if name!='alembic_version']
        records={name:[dict(row) for row in db.execute('SELECT * FROM '+name)] for name in originals}
        def columns(name):
            return [{**col,'type':str(col['type'].compile(dialect=db.raw_connection.dialect))} for col in inspector.get_columns(name)]
        old_columns={name:columns(name) for name in originals}
        old_indexes={name:inspector.get_indexes(name) for name in originals}
        command.upgrade(settings,'head')
        inspector=inspect(db.raw_connection)
        for name in originals:
            assert [dict(row) for row in db.execute('SELECT * FROM '+name)] == records[name]
            assert columns(name) == old_columns[name]
            assert_preserved_indexes(inspector,name,old_indexes[name])
        for name in ('task_checkpoints','dataset_preparation_decisions','prepared_dataset_versions'):
            assert db.execute('SELECT count(*) AS n FROM '+name).fetchone()['n'] == 0
        result=audit_database(db)
        assert result['ok'],result['schema_issues']


def test_preparation_tables_native_constraints_and_permissions(postgres_schema):
    from app.db.database import database_connection
    with database_connection() as db:
        inspector=inspect(db.raw_connection)
        for name in ('task_checkpoints','dataset_preparation_decisions','prepared_dataset_versions'):
            assert name in metadata.tables
            assert name in inspector.get_table_names()
        assert len(inspector.get_foreign_keys('dataset_preparation_decisions')) == 5
        uniques=inspector.get_unique_constraints('prepared_dataset_versions')
        assert any(u['column_names']==['task_id'] for u in uniques)
        assert any(u['column_names']==['parent_dataset_id','version'] for u in uniques)
        verify_runtime_permissions(db.raw_connection,postgres_schema)
