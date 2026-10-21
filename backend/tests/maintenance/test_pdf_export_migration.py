"""Additive PDF migration and runtime source/lineage constraints."""
import pytest
from alembic import command
from sqlalchemy.exc import SQLAlchemyError
from tests.api.test_analysis import client  # noqa:F401
from tests.api.test_pdf_exports import successful_docx,fake_renderer  # noqa:F401
from tests.maintenance.test_literature_evidence_migration import fingerprints
from app.db.database import alembic_config,get_migration_database_config,migration_connection,database_connection


def test_pdf_migration_preserves_existing_rows_columns_and_indexes(client):
    successful_docx(client)
    cfg=alembic_config()
    with migration_connection(write=True) as db:
        cfg.attributes.update(connection=db.raw_connection,database_config=get_migration_database_config())
        command.downgrade(cfg,'0035_manuscripts')
        tables=[r['tablename'] for r in db.execute('SELECT tablename FROM pg_tables WHERE schemaname=current_schema()') if r['tablename']!='alembic_version']
        before=fingerprints(db,tables)
        indexes={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        command.upgrade(cfg,'head')
        assert fingerprints(db,tables)==before
        after={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        assert all(after.get(k)==v for k,v in indexes.items())
    with database_connection() as db:
        from app.maintenance.database_audit import audit_database
        result=audit_database(db)
        assert result['ok'],result['schema_issues'] or [c for c in result['data_checks'] if c['invalid']]


def test_pdf_fk_and_typed_source_and_parent_constraints_and_downgrade_guard(client):
    path,source=successful_docx(client)
    saved=client.post(path,json=dict(source_kind='manuscript_export',source_id=source['id'],request_key='pdf')).json()
    for clause,args in (("source_kind='report'",()),("manuscript_export_id='missing',source_id='missing'",()),("parent_export_id='missing'",())):
        with pytest.raises(SQLAlchemyError):
            with database_connection(write=True) as db: db.execute('UPDATE pdf_exports SET '+clause+' WHERE id=%s',(*args,saved['id']))
    cfg=alembic_config()
    with pytest.raises(RuntimeError,match='refusing destructive downgrade'):
        with migration_connection(write=True) as db:
            cfg.attributes.update(connection=db.raw_connection,database_config=get_migration_database_config())
            command.downgrade(cfg,'0035_manuscripts')


def test_audit_rejects_rehashed_task_binding_drift(client):
    from psycopg.types.json import Jsonb
    from app.domain.literature.service import digest
    from app.maintenance.pdf_export_audit import audit_pdf_exports
    path,source=successful_docx(client)
    saved=client.post(path,json=dict(source_kind='manuscript_export',source_id=source['id'],request_key='pdf')).json()
    with migration_connection(write=True) as db:
        row=db.execute('SELECT * FROM pdf_exports WHERE id=%s',(saved['id'],)).fetchone()
        changed=dict(row['input_json'],source_sha256='f'*64)
        db.execute('UPDATE pdf_exports SET input_json=%s,input_sha256=%s WHERE id=%s',(Jsonb(changed),digest(changed),saved['id']))
    with database_connection() as db: assert any(c['invalid'] for c in audit_pdf_exports(db))
    assert client.get(path+'/'+saved['id']).status_code==409
