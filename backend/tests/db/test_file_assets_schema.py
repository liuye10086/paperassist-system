from alembic import command
from sqlalchemy import inspect

from app.db.database import alembic_config, migration_connection
from app.maintenance.database_audit import audit_database
from tests.db.test_task_schema import seed_owner


def test_0014_preserves_historical_columns_indexes_and_backfills_only_object_key(postgres_schema, postgres_migration_config):
    with migration_connection(config=postgres_migration_config) as db:
        settings = alembic_config()
        settings.attributes.update(connection=db.raw_connection, database_config=postgres_migration_config)
        command.downgrade(settings, '0013_cost_reconciliation')
        seed_owner(db)
        db.execute("INSERT INTO files VALUES ('old','p','old.xlsx','xlsx',3,'hash','2026-10-08T00:00:00Z','parsed',NULL,'{}')")
        columns = [c['name'] for c in inspect(db.raw_connection).get_columns('files', schema=postgres_schema.schema)]
        old = dict(db.execute('SELECT * FROM files').fetchone())
        indexes = inspect(db.raw_connection).get_indexes('files', schema=postgres_schema.schema)
        command.upgrade(settings, 'head')
        row = dict(db.execute('SELECT * FROM files').fetchone())
        assert [c['name'] for c in inspect(db.raw_connection).get_columns('files', schema=postgres_schema.schema)][:len(columns)] == columns
        assert {key: row[key] for key in columns} == old
        assert row['object_key'] == 'files/old.xlsx'
        assert row['uploader_id'] is None and row['metadata_revision'] == 1 and row['storage_backend'] == 'local'
        current = inspect(db.raw_connection).get_indexes('files', schema=postgres_schema.schema)
        assert all(index in current for index in indexes)
        assert db.execute('SELECT count(*) AS n FROM file_purposes').fetchone()['n'] == 0
        audit = audit_database(db)
        assert audit['ok'], audit
        command.downgrade(settings, '0013_cost_reconciliation')
        assert dict(db.execute('SELECT * FROM files').fetchone()) == old
        command.upgrade(settings, 'head')
