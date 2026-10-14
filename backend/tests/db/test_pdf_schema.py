"""0019 preserves Word history and blocks loss of PDF history."""
import pytest
from alembic import command
from sqlalchemy.exc import DBAPIError
from app.db.database import migration_connection, database_connection, alembic_config
from tests.api.test_projects import client
from tests.api.test_document_versions import uploaded_pdf, uploaded_docx

def test_0019_preserves_word_rows(client, postgres_migration_config):
    uploaded_docx(client)
    with migration_connection(config=postgres_migration_config) as db:
        settings=alembic_config();settings.attributes.update(connection=db.raw_connection,database_config=postgres_migration_config)
        command.downgrade(settings,'0018_document_parsing')
        before={table:[dict(row) for row in db.execute('SELECT * FROM '+table+' ORDER BY id')] for table in ('files','file_parse_results','tasks')}
        command.upgrade(settings,'0019_pdf_parsing')
        after={table:[dict(row) for row in db.execute('SELECT * FROM '+table+' ORDER BY id')] for table in before}
        assert before==after

def test_0019_pdf_history_prevents_downgrade(client, postgres_migration_config):
    uploaded_pdf(client)
    with pytest.raises(DBAPIError):
        with migration_connection(config=postgres_migration_config) as db:
            settings=alembic_config();settings.attributes.update(connection=db.raw_connection,database_config=postgres_migration_config)
            command.downgrade(settings,'0018_document_parsing')
    with database_connection() as db:
        assert db.execute('SELECT file_type FROM files').fetchone()['file_type']=='pdf'
