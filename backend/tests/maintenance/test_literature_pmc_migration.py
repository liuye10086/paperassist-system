"""0033 -> 0034 is additive and preserves all prior rows, indexes and assets."""
import pytest
from alembic import command
from alembic.script import ScriptDirectory
from app.db.database import alembic_config,migration_connection,get_migration_database_config,database_connection
from tests.api.test_analysis import client
from tests.api.test_literature_citations import seeded
from tests.maintenance.test_literature_evidence_migration import fingerprints


def test_pmc_upgrade_preserves_old_rows_indexes_assets_and_frozen_ddl(client):
    _,_,_,refs=seeded(client)
    url=refs[0]['source']['source_download_url'];raw=client.get(url).content
    cfg=alembic_config()
    assert ScriptDirectory.from_config(cfg).get_heads()==['0034_literature_pmc']
    with migration_connection(write=True) as db:
        cfg.attributes.update(connection=db.raw_connection,database_config=get_migration_database_config())
        command.downgrade(cfg,'0033_literature_checks')
        tables=[r['tablename'] for r in db.execute('SELECT tablename FROM pg_tables WHERE schemaname=current_schema()') if r['tablename']!='alembic_version']
        before=fingerprints(db,tables)
        indexes={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        command.upgrade(cfg,'0034_literature_pmc')
        assert fingerprints(db,tables)==before
        after={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        assert all(after.get(k)==v for k,v in indexes.items())
        now={r['tablename'] for r in db.execute('SELECT tablename FROM pg_tables WHERE schemaname=current_schema()') if r['tablename']!='alembic_version'}
        assert now-set(tables)=={'literature_pmc_receipts'}
    assert client.get(url).content==raw
    with database_connection() as db:
        from app.maintenance.database_audit import audit_database
        audit=audit_database(db)
        assert audit['ok'],audit
    from pathlib import Path
    source=Path('backend/alembic/versions/0034_literature_pmc.py').read_text()
    assert 'from app.db' not in source


def test_history_refuses_downgrade_and_runtime_receipts_are_append_only(client,tmp_path):
    from tests.integration.test_literature_pmc import prepare
    pid,refs,ref,svc,adapter,_,_=prepare(client,tmp_path)
    svc.acquire(pid,ref['id'],'PMC123','saved',adapter=adapter)
    with database_connection() as db:
        from app.db.database import verify_runtime_permissions
        verify_runtime_permissions(db.raw_connection,db.config)
        assert db.execute("SELECT has_table_privilege(current_user,'literature_pmc_receipts','UPDATE') AS allowed").fetchone()['allowed'] is False
        assert db.execute("SELECT has_table_privilege(current_user,'literature_pmc_receipts','DELETE') AS allowed").fetchone()['allowed'] is False
    with migration_connection(write=True) as db:
        cfg=alembic_config();cfg.attributes.update(connection=db.raw_connection,database_config=get_migration_database_config())
        with pytest.raises(RuntimeError,match='Cannot remove saved PMC or comparison history'):
            command.downgrade(cfg,'0033_literature_checks')
