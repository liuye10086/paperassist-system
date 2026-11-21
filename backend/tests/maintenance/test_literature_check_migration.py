"""0032 -> 0033 only adds independent history, with frozen migration semantics."""
from app.db.database import SCHEMA_HEAD
from tests.helpers.historical_migration import historical_workflow, assert_saved_history_blocks
from alembic import command
from alembic.script import ScriptDirectory
from app.db.database import alembic_config,migration_connection,get_migration_database_config,database_connection
from tests.api.test_analysis import client
from tests.api.test_literature_citations import seeded
from tests.api.test_literature_evidence import post
from tests.maintenance.test_literature_evidence_migration import fingerprints


def test_check_upgrade_preserves_rows_indexes_assets_and_head(client):
    _,lit,_,refs=seeded(client)
    url=refs[0]['source']['source_download_url'];raw=client.get(url).content
    cfg=alembic_config()
    assert ScriptDirectory.from_config(cfg).get_heads()==[SCHEMA_HEAD]
    with historical_workflow(get_migration_database_config(), '0032_literature_citations') as (db, cfg):
        assert db.execute("SELECT 1 FROM project_references WHERE id=%s", (refs[0]['id'],)).fetchone()
        tables=[r['tablename'] for r in db.execute('SELECT tablename FROM pg_tables WHERE schemaname=current_schema()') if r['tablename']!='alembic_version']
        before=fingerprints(db,tables)
        indexes={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        command.upgrade(cfg,'0033_literature_checks')
        assert fingerprints(db,tables)==before
        after={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        assert all(after.get(k)==v for k,v in indexes.items())
        now={r['tablename'] for r in db.execute('SELECT tablename FROM pg_tables WHERE schemaname=current_schema()') if r['tablename']!='alembic_version'}
        assert now-set(tables)=={'literature_check_receipts'}
        command.upgrade(cfg,'head')
    assert client.get(url).content==raw
    with database_connection() as db:
        from app.maintenance.database_audit import audit_database
        assert audit_database(db)['ok']


def test_readonly_audit_rejects_frozen_result_and_refuses_history_downgrade(client):
    from app.maintenance.literature_check_audit import audit_literature_checks
    from psycopg.types.json import Jsonb
    _,lit,task,refs=seeded(client)
    path=lit+'/checks/references/'+refs[0]['id']
    r=post(client,path+'/receipts',dict(kind='saved_record',search_id=task['id']),'saved')
    assert r.status_code==201,r.text
    with database_connection() as db:
        before=fingerprints(db,['literature_check_receipts'])
        assert all(c['invalid']==0 for c in audit_literature_checks(db))
        assert fingerprints(db,['literature_check_receipts'])==before
    assert_saved_history_blocks('0033_literature_checks', 'Cannot remove saved literature check history')
    with database_connection(write=True) as db:
        row=db.execute('SELECT * FROM literature_check_receipts').fetchone()
        db.execute('UPDATE literature_check_receipts SET snapshot_json=%s WHERE id=%s',(Jsonb({**row['snapshot_json'],'output_language':'en'}),row['id']))
    with database_connection() as db:
        assert any(c['invalid'] for c in audit_literature_checks(db))
