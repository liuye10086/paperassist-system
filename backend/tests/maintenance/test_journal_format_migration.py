"""0045→0046 preserves populated history, with sealed scope and one publication."""
import pytest
from alembic import command
from sqlalchemy.exc import SQLAlchemyError
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_journal_format import candidate,guide,target,manuscript
from tests.api.test_journals import post,profile
from tests.maintenance.test_literature_evidence_migration import fingerprints
from app.db.database import migration_connection,database_connection,alembic_config,get_migration_database_config


def test_0046_preserves_populated_0045_and_freezes_schema(client):
    from app.db.database import SCHEMA_HEAD
    assert SCHEMA_HEAD=='0047_journal_adaptations'
    base,p,r=candidate(client)
    path,m=manuscript(client)
    file=client.get(path.removesuffix('/manuscripts')+'/files').json()[0]
    filebase=path.removesuffix('/manuscripts')+'/files/'+file['id']
    original=client.get(filebase+'/download').content
    material=dict(kind='original',id=file['id'],file_id=file['id'])
    saved=post(client,path.removesuffix('/manuscripts')+'/journals/profiles',profile(material=material),'source-profile')
    assert saved.status_code==201,saved.text
    cfg=alembic_config()
    with migration_connection(write=True) as db:
        cfg.attributes.update(connection=db.raw_connection,database_config=get_migration_database_config())
        command.downgrade(cfg,'0045_journal_recommendations')
        tables=[r['tablename'] for r in db.execute('SELECT tablename FROM pg_tables WHERE schemaname=current_schema()') if r['tablename']!='alembic_version']
        before=fingerprints(db,[t for t in tables if t!='journal_material_refs'])
        refs=[dict(r) for r in db.execute('SELECT * FROM journal_material_refs ORDER BY id')]
        indexes={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        command.upgrade(cfg,'0046_journal_format_checks')
        assert fingerprints(db,[t for t in tables if t!='journal_material_refs'])==before
        assert [{k:v for k,v in dict(row).items() if k!='guide_id'} for row in db.execute('SELECT * FROM journal_material_refs ORDER BY id')]==refs
        after={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        assert all(after.get(k)==v for k,v in indexes.items())
        command.upgrade(cfg,SCHEMA_HEAD)
    assert client.get(filebase+'/download').content==original
    assert client.get(path+'/'+m['id']+'/versions/1').status_code==200
    g=post(client,base+'/guides',guide(p),'guide').json()
    t=post(client,base+'/targets',target(p,r,g),'target').json()
    from tests.api.test_journals import setup
    other=setup(client).split('/projects/')[1].split('/')[0]
    with pytest.raises(SQLAlchemyError):
        with database_connection(write=True) as db:
            db.execute("""INSERT INTO journal_guides(id,project_id,user_id,idempotency_key,request_json,request_digest,snapshot_json,snapshot_sha256,created_at,profile_id,requirements_version) SELECT 'cross-project',%s,user_id,'cross',request_json,request_digest,snapshot_json,snapshot_sha256,created_at,profile_id,requirements_version FROM journal_guides WHERE id=%s""",(other,g['id']))
    for table in ('journal_guides','journal_targets'):
        with pytest.raises(SQLAlchemyError):
            with database_connection(write=True) as db:db.execute('DELETE FROM '+table)
    with pytest.raises(RuntimeError,match='refusing destructive downgrade'):
        with migration_connection(write=True) as db:
            cfg.attributes.update(connection=db.raw_connection,database_config=get_migration_database_config())
            command.downgrade(cfg,'0045_journal_recommendations')
    from app.maintenance.database_audit import audit_database
    with database_connection() as db:report=audit_database(db)
    assert report['ok'],report['schema_issues'] or [c for c in report['data_checks'] if c['invalid']]
