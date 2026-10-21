"""0020 changes only file types and protects OCR history."""
import pytest
from alembic import command
from sqlalchemy.exc import DBAPIError
from app.db.database import migration_connection,database_connection,alembic_config,SCHEMA_HEAD
from tests.api.test_projects import client  # noqa: F401
from tests.api.test_document_versions import uploaded_pdf


def test_0020_preserves_pdf_history(client,postgres_migration_config):
    assert SCHEMA_HEAD=='0040_manuscript_writing_live'
    uploaded_pdf(client)
    with migration_connection(config=postgres_migration_config) as db:
        settings=alembic_config();settings.attributes.update(connection=db.raw_connection,database_config=postgres_migration_config)
        command.downgrade(settings,'0019_pdf_parsing')
        tables=('files','file_parse_results','tasks')
        before={t:[dict(row) for row in db.execute('SELECT * FROM '+t+' ORDER BY id')] for t in tables}
        command.upgrade(settings,'0020_ocr_parsing')
        assert before=={t:[dict(row) for row in db.execute('SELECT * FROM '+t+' ORDER BY id')] for t in tables}


@pytest.mark.parametrize('history',['file','task','result','parser','snapshot'])
def test_0020_refuses_downgrade_with_ocr_history(client,postgres_migration_config,history):
    project,item,_=uploaded_pdf(client)
    with database_connection(write=True) as db:
        if history=='file': db.execute("UPDATE files SET file_type='png'")
        elif history=='task': db.execute("UPDATE tasks SET workflow_version='ocr_document_v1'")
        elif history=='parser': db.execute("UPDATE file_parse_results SET parser_version='rapidocr-3.10.0-ppocrv6-small-v1'")
        elif history=='snapshot': db.execute("UPDATE tasks SET input_snapshot=jsonb_set(input_snapshot,'{kind}','\"ocr_document\"'::jsonb)")
        else: db.execute("UPDATE file_parse_results SET completed_at=clock_timestamp(),result_json='{\"kind\":\"ocr_document\"}'::jsonb")
    with pytest.raises(DBAPIError):
        with migration_connection(config=postgres_migration_config) as db:
            settings=alembic_config();settings.attributes.update(connection=db.raw_connection,database_config=postgres_migration_config)
            command.downgrade(settings,'0019_pdf_parsing')
