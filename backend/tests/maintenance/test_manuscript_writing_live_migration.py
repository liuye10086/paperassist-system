import pytest
from alembic import command
from tests.api.test_manuscripts import client
from tests.api.test_manuscript_writing_live import preview
from tests.maintenance.test_literature_evidence_migration import fingerprints
from app.db.database import alembic_config, get_migration_database_config, migration_connection, database_connection, SCHEMA_HEAD

def test_0040_is_additive_and_schema_head_audit_agree(client):
    cfg=alembic_config()
    with migration_connection(write=True) as db:
        cfg.attributes.update(connection=db.raw_connection,database_config=get_migration_database_config())
        command.downgrade(cfg,'0039_layout_exports')
        tables=[r['tablename'] for r in db.execute('SELECT tablename FROM pg_tables WHERE schemaname=current_schema()') if r['tablename']!='alembic_version']
        before=fingerprints(db,tables)
        command.upgrade(cfg,'head')
        assert fingerprints(db,tables)==before
    with database_connection() as db:
        from app.maintenance.database_audit import audit_database
        result=audit_database(db)
        assert result['ok'],result['schema_issues'] or [c for c in result['data_checks'] if c['invalid']]
        assert SCHEMA_HEAD=='0040_manuscript_writing_live'
        assert {r['table'] for r in result['data_checks']} >= {'manuscript_writing_bundles','manuscript_writing_authorizations','manuscript_writing_authorized_tasks','manuscript_writing_call_admissions'}
        from sqlalchemy import inspect
        fks=inspect(db.raw_connection).get_foreign_keys('manuscript_writing_call_admissions',schema=db.config.schema)
        assert any(fk['referred_table']=='model_calls' and fk['constrained_columns']==['model_call_id','project_id','user_id'] for fk in fks)

def test_saved_bundle_prevents_destructive_downgrade(client):
    preview(client);cfg=alembic_config()
    with pytest.raises(RuntimeError,match='refusing destructive downgrade'):
        with migration_connection(write=True) as db:
            cfg.attributes.update(connection=db.raw_connection,database_config=get_migration_database_config())
            command.downgrade(cfg,'0039_layout_exports')

def test_completed_synthetic_candidate_is_audited(client):
    from tests.api.test_manuscript_writing_live import create_live,LiveFixture
    from app.domain.manuscript_writing.execution import run_manuscript_writing_task
    from app.maintenance.database_audit import audit_database
    root,bundle,path,auth,task=create_live(client)
    assert run_manuscript_writing_task(task['id'],task['revision'],provider=LiveFixture())['status']=='succeeded'
    with database_connection() as db:
        result=audit_database(db)
        assert result['ok'],result['schema_issues'] or [c for c in result['data_checks'] if c['invalid']]

def test_runtime_cannot_modify_frozen_bundle_or_authorized_task(client):
    from tests.api.test_manuscript_writing_live import create_live
    root,bundle,path,auth,task=create_live(client)
    for sql in ("UPDATE manuscript_writing_bundles SET bundle_sha256='"+'0'*64+"'",'DELETE FROM manuscript_writing_authorized_tasks'):
        with pytest.raises(Exception):
            with database_connection(write=True) as db: db.execute(sql)
    with pytest.raises(Exception):
        with database_connection(write=True) as db: db.execute('UPDATE manuscript_writing_authorizations SET cap_micro_usd=1')
