"""Additive migration retains historical rows and refuses destructive downgrade."""
import pytest
from alembic import command
from sqlalchemy.exc import SQLAlchemyError
from app.db.database import alembic_config,get_migration_database_config,migration_connection,database_connection,verify_runtime_permissions
from tests.api.test_analysis import client  # noqa:F401
from tests.api.test_manuscripts import setup,body
from tests.api.test_literature_evidence import post
from tests.maintenance.test_literature_evidence_migration import fingerprints


def test_manuscript_upgrade_preserves_old_history_and_indexes(client):
    setup(client)
    cfg=alembic_config()
    with migration_connection(write=True) as db:
        cfg.attributes.update(connection=db.raw_connection,database_config=get_migration_database_config())
        command.downgrade(cfg,'0034_literature_pmc')
        tables=[r['tablename'] for r in db.execute('SELECT tablename FROM pg_tables WHERE schemaname=current_schema()') if r['tablename']!='alembic_version']
        before=fingerprints(db,tables)
        indexes={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        command.upgrade(cfg,'head')
        assert fingerprints(db,tables)==before
        after={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        assert all(after.get(k)==v for k,v in indexes.items())
    with database_connection() as db:
        verify_runtime_permissions(db.raw_connection,db.config)
        from app.maintenance.database_audit import audit_database
        result=audit_database(db)
        assert result['ok'],result


def test_manuscript_history_blocks_downgrade_and_runtime_mutation(client):
    path,_,_=setup(client)
    assert post(client,path,body(),'first').status_code==201
    cfg=alembic_config()
    with pytest.raises(RuntimeError,match='refusing destructive downgrade'):
        with migration_connection(write=True) as db:
            cfg.attributes.update(connection=db.raw_connection,database_config=get_migration_database_config())
            command.downgrade(cfg,'0034_literature_pmc')
    for table in ('manuscript_versions','manuscript_sources','manuscript_citations'):
        with pytest.raises(SQLAlchemyError):
            with database_connection(write=True) as db: db.execute('DELETE FROM '+table)
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM manuscript_versions').fetchone()['n']==1
        from app.maintenance.manuscript_audit import audit_manuscripts
        assert not any(c['invalid'] for c in audit_manuscripts(db))


def test_manuscript_audit_detects_rehashed_snapshot_content_drift(client):
    from psycopg.types.json import Jsonb
    from app.domain.literature.service import digest
    path,_,_=setup(client);created=post(client,path,body(),'first').json()
    with migration_connection(write=True) as db:
        row=db.execute('SELECT * FROM manuscript_versions').fetchone()
        changed=dict(row['snapshot_json'],title='Fabricated title')
        db.execute('UPDATE manuscript_versions SET snapshot_json=%s,snapshot_sha256=%s WHERE id=%s',(Jsonb(changed),digest(changed),row['id']))
    with database_connection() as db:
        from app.maintenance.manuscript_audit import audit_manuscripts
        assert any(c['invalid'] for c in audit_manuscripts(db))
    assert client.get(path+'/'+created['id']).status_code==409
