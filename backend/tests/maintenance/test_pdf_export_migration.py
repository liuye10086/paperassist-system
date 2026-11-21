"""Additive PDF migration and runtime source/lineage constraints."""
from tests.helpers.historical_migration import historical_workflow, assert_saved_history_blocks
import pytest
from alembic import command
from sqlalchemy.exc import SQLAlchemyError
from tests.api.test_analysis import client  # noqa:F401
from tests.api.test_pdf_exports import successful_docx,fake_renderer  # noqa:F401
from tests.maintenance.test_literature_evidence_migration import fingerprints
from app.db.database import alembic_config,get_migration_database_config,migration_connection,database_connection


def test_pdf_migration_preserves_existing_rows_columns_and_indexes(client):
    _, saved = successful_docx(client)
    with historical_workflow(get_migration_database_config(), '0035_manuscripts') as (db, cfg):
        assert db.execute("SELECT 1 FROM manuscript_exports WHERE id=%s", (saved['id'],)).fetchone()
        tables=[r['tablename'] for r in db.execute('SELECT tablename FROM pg_tables WHERE schemaname=current_schema()') if r['tablename']!='alembic_version']
        before=fingerprints(db,tables)
        indexes={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        command.upgrade(cfg,'0036_pdf_exports')
        assert fingerprints(db,tables)==before
        after={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        assert all(after.get(k)==v for k,v in indexes.items())
    with database_connection() as db:
        from app.maintenance.database_audit import audit_database
        result=audit_database(db)
        assert result['ok'],result['schema_issues'] or [c for c in result['data_checks'] if c['invalid']]


def test_pdf_fk_and_typed_source_and_parent_constraints_and_downgrade_guard(client):
    path,source=successful_docx(client)
    from tests.helpers.historical_pdf_exports import historical_pdf
    saved=historical_pdf(path,'manuscript_export',source['id'])
    for clause,args in (("source_kind='report'",()),("manuscript_export_id='missing',source_id='missing'",()),("parent_export_id='missing'",())):
        with pytest.raises(SQLAlchemyError):
            with database_connection(write=True) as db: db.execute('UPDATE pdf_exports SET '+clause+' WHERE id=%s',(*args,saved['id']))
    assert_saved_history_blocks('0036_pdf_exports', 'PDF history exists; refusing destructive downgrade.')


def test_audit_rejects_rehashed_task_binding_drift(client):
    from psycopg.types.json import Jsonb
    from app.domain.literature.service import digest
    from app.maintenance.pdf_export_audit import audit_pdf_exports
    path,source=successful_docx(client)
    from tests.helpers.historical_pdf_exports import historical_pdf
    saved=historical_pdf(path,'manuscript_export',source['id'])
    with migration_connection(write=True) as db:
        row=db.execute('SELECT * FROM pdf_exports WHERE id=%s',(saved['id'],)).fetchone()
        changed=dict(row['input_json'],source_sha256='f'*64)
        db.execute('UPDATE pdf_exports SET input_json=%s,input_sha256=%s WHERE id=%s',(Jsonb(changed),digest(changed),saved['id']))
    with database_connection() as db: assert any(c['invalid'] for c in audit_pdf_exports(db))
    assert client.get(path+'/'+saved['id']).status_code==409
