"""Only the fixture's pa_test schema is migrated; sealed old sources are untouched."""
import re
import pytest
from tests.api.test_analysis import client
from tests.api.test_manuscripts import setup,body
from tests.api.test_review_figure_adoptions import post
from app.db.database import database_connection

def test_0054_sources_and_request_hashes_survive_0055_without_resealing(client):
    from app.db.database import migration_connection,get_migration_database_config,alembic_config
    from alembic import command
    path,_,file=setup(client)
    data=body(sources=[dict(kind='original',id=file['id'],file_id=file['id'],role='methods')])
    response=post(client,path,data,'old-source');assert response.status_code==201,response.text
    version=response.json()['versions'][0];identity=version['id']
    query='SELECT request_json,request_digest,snapshot_json,snapshot_sha256 FROM manuscript_versions WHERE id=%s'
    with database_connection() as db:
        before=db.execute(query,(identity,)).fetchone()
        assert 'analysis_handoff_run_ids' not in before['request_json'] and 'analysis_handoff_run_ids' not in before['snapshot_json']
    config=get_migration_database_config()
    assert config.environment=='test' and config.url.database=='paperassist_system_test' and re.fullmatch(r'pa_test_[a-f0-9]{32}',config.schema)
    with migration_connection(write=True,config=config) as db:
        settings=alembic_config();settings.attributes.update(connection=db.raw_connection,database_config=config)
        command.downgrade(settings,'0054_review_figure_adoptions')
        assert db.execute(query,(identity,)).fetchone()==before
        tables={r['tablename'] for r in db.execute('SELECT tablename FROM pg_tables WHERE schemaname=%s',(config.schema,))}
        command.upgrade(settings,'0055_manuscript_analysis_reports')
        assert db.execute(query,(identity,)).fetchone()==before
        assert {r['tablename'] for r in db.execute('SELECT tablename FROM pg_tables WHERE schemaname=%s',(config.schema,))}==tables
        row=db.execute('SELECT analysis_report_id,collection_report_id FROM manuscript_sources WHERE version_id=%s',(identity,)).fetchone()
        assert row['analysis_report_id'] is None and row['collection_report_id'] is None
    replay=post(client,path,data|dict(analysis_handoff_run_ids=[]),'old-source')
    assert replay.status_code==200,replay.text
    assert replay.json()['versions'][0]['snapshot']==version['snapshot']
    # The two added typed references cannot point to missing reports.
    from sqlalchemy.exc import IntegrityError
    from psycopg.types.json import Jsonb
    for kind in ('analysis_report','collection_report'):
        with pytest.raises(IntegrityError) as rejected:
            with database_connection(write=True) as db:
                db.execute('INSERT INTO manuscript_sources(id,version_id,file_id,kind,source_id,role,source_json,sha256,'+kind+'_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    (kind+'-missing',identity,file['id'],kind,'missing-report','user_results',Jsonb({'kind':kind}),'a'*64,'missing-report'))
        assert rejected.value.orig.diag.constraint_name=='ms_'+kind+'_fk'
