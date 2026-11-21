"""0018 preserves prior rows and rejects destructive downgrade."""
import pytest
from alembic import command
from sqlalchemy.exc import IntegrityError, DBAPIError
from app.db.database import migration_connection, database_connection, alembic_config
from tests.helpers.document_migration import seed_document_parse


@pytest.mark.initial_revision('0017_dataset_preparation')
def test_0018_keeps_0017_rows_and_native_limits(postgres_migration_config):
    seed_document_parse('xlsx')
    with migration_connection(config=postgres_migration_config) as db:
        settings=alembic_config();settings.attributes.update(connection=db.raw_connection,database_config=postgres_migration_config)
        before={table:[dict(row) for row in db.execute('SELECT * FROM '+table+' ORDER BY id')] for table in ('files','file_parse_results','tasks','file_upload_batches','file_upload_items')}
        command.upgrade(settings,'0018_document_parsing')
        after={table:[dict(row) for row in db.execute('SELECT * FROM '+table+' ORDER BY id')] for table in before}
        assert before==after
    for sql in ("UPDATE files SET file_type='pdf'","UPDATE file_parse_results SET version=0"):
        with pytest.raises(IntegrityError):
            with database_connection(write=True) as db: db.execute(sql)
    with database_connection(write=True) as db:
        db.execute('UPDATE file_parse_results SET version=2')
    with pytest.raises(DBAPIError, match='document history requires preservation'):
        with migration_connection(config=postgres_migration_config) as db:
            settings=alembic_config();settings.attributes.update(connection=db.raw_connection,database_config=postgres_migration_config)
            command.downgrade(settings,'0017_dataset_preparation')
    with database_connection() as db:
        assert db.execute('SELECT version FROM file_parse_results').fetchone()['version']==2


@pytest.mark.initial_revision('0018_document_parsing')
def test_0018_word_history_prevents_downgrade(postgres_migration_config):
    seed_document_parse('docx')
    with pytest.raises(DBAPIError, match='document history requires preservation'):
        with migration_connection(config=postgres_migration_config) as db:
            settings=alembic_config();settings.attributes.update(connection=db.raw_connection,database_config=postgres_migration_config)
            command.downgrade(settings,'0017_dataset_preparation')
    with database_connection() as db:
        assert db.execute('SELECT file_type FROM files').fetchone()['file_type']=='docx'
