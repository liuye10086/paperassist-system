"""0046 populated history survives additive 0047 without destructive downgrade."""
import pytest
from alembic import command
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_journal_format import manuscript,guide,target
from tests.api.test_journals import post,profile,request
from tests.maintenance.test_literature_evidence_migration import fingerprints
from app.db.database import migration_connection,database_connection,alembic_config,get_migration_database_config
from app.domain.tasks.execution import run_task

def test_0047_retains_populated_0046_rows_indexes_and_controlled_downgrade(client):
    path,m=manuscript(client);base=path.removesuffix('/manuscripts')+'/journals'
    p=post(client,base+'/profiles',profile(),'p').json()
    r=post(client,base+'/recommendations',request(),'r').json();run_task(r['task']['id'],1)
    g=post(client,base+'/guides',guide(p),'g').json();t=post(client,base+'/targets',target(p,r,g),'t').json()
    c=post(client,base+'/checks',dict(target_id=t['id'],manuscript=dict(id=m['id'],revision=1)),'c').json();run_task(c['task']['id'],1)
    cfg=alembic_config()
    with migration_connection(write=True) as db:
        cfg.attributes.update(connection=db.raw_connection,database_config=get_migration_database_config())
        command.downgrade(cfg,'0046_journal_format_checks')
        tables=[r['tablename'] for r in db.execute('SELECT tablename FROM pg_tables WHERE schemaname=current_schema()') if r['tablename']!='alembic_version']
        before=fingerprints(db,tables)
        indexes={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        command.upgrade(cfg,'0047_journal_adaptations')
        assert fingerprints(db,tables)==before
        after={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        assert all(after.get(k)==v for k,v in indexes.items())
    assert client.get(base+'/checks/'+c['id']).status_code==200
    event=post(client,base+'/submission-events',dict(target_id=t['id'],status='submitted',event_date='2026-10-23'),'event');assert event.status_code==201,event.text
    with pytest.raises(RuntimeError,match='refusing destructive downgrade'):
        with migration_connection(write=True) as db:
            cfg.attributes.update(connection=db.raw_connection,database_config=get_migration_database_config());command.downgrade(cfg,'0046_journal_format_checks')
    from app.maintenance.database_audit import audit_database
    with database_connection() as db:report=audit_database(db)
    assert report['ok'],report['schema_issues'] or [c for c in report['data_checks'] if c['invalid']]
