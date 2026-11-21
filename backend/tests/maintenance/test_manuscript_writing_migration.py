"""0037 preserves all existing rows, columns and indexes and guards its history."""
from tests.helpers.historical_migration import historical_workflow, assert_saved_history_blocks
import pytest
from alembic import command
from tests.api.test_manuscripts import client,setup,body
from tests.api.test_literature_evidence import post
from tests.maintenance.test_literature_evidence_migration import fingerprints
from app.db.database import alembic_config,get_migration_database_config,migration_connection,database_connection

def test_writing_migration_is_additive_and_audited(client):
    path,_,_=setup(client)
    response = post(client,path,body(),'base')
    assert response.status_code == 201, response.text
    saved = response.json()
    with historical_workflow(get_migration_database_config(), '0036_pdf_exports') as (db, cfg):
        assert db.execute("SELECT 1 FROM manuscripts WHERE id=%s", (saved['id'],)).fetchone()
        tables=[r['tablename'] for r in db.execute('SELECT tablename FROM pg_tables WHERE schemaname=current_schema()') if r['tablename']!='alembic_version']
        before=fingerprints(db,tables)
        indexes={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        command.upgrade(cfg,'0037_manuscript_writing')
        assert fingerprints(db,tables)==before
        after={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        assert all(after.get(k)==v for k,v in indexes.items())
    with database_connection() as db:
        from app.maintenance.database_audit import audit_database
        audit=audit_database(db)
        assert audit['ok'],audit['schema_issues'] or [c for c in audit['data_checks'] if c['invalid']]

def test_writing_history_blocks_downgrade(client):
    from tests.api.test_manuscript_writing import candidate_ready
    candidate_ready(client)
    assert_saved_history_blocks('0037_manuscript_writing', 'Writing history exists; refusing destructive downgrade.')
