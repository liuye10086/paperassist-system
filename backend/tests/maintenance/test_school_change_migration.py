"""0044 only adds relationships and sealed inputs; prior nonempty rows survive."""
import pytest
from alembic import command
from sqlalchemy.exc import SQLAlchemyError
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_school_changes import base,upload_return
from tests.api.test_school_templates import post
from app.db.database import migration_connection,database_connection,alembic_config,get_migration_database_config


def test_0044_preserves_nonempty_templates_manuscripts_tasks_and_indexes(client):
    path,template,request,root,endpoint=base(client)
    original=client.get(path+'/files/'+template['template_file_id']+'/download').content
    cfg=alembic_config()
    with migration_connection(write=True) as db:
        assert db.config.schema.startswith('pa_test_')
        cfg.attributes.update(connection=db.raw_connection,database_config=get_migration_database_config())
        command.downgrade(cfg,'0043_school_exports')
        tables=['school_template_versions','school_template_sources','school_template_confirmations','thesis_profiles','manuscripts','manuscript_versions','tasks']
        columns={t:[r['column_name'] for r in db.execute('SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=%s ORDER BY ordinal_position',(t,))] for t in tables}
        before={t:list(db.execute('SELECT '+','.join(columns[t])+' FROM '+t+' ORDER BY '+columns[t][0])) for t in tables}
        indexes={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        command.upgrade(cfg,'0044_school_changes')
        assert {t:list(db.execute('SELECT '+','.join(columns[t])+' FROM '+t+' ORDER BY '+columns[t][0])) for t in tables}==before
        after={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        assert all(after.get(k)==v for k,v in indexes.items())
        assert db.execute('SELECT previous_version_id FROM school_template_versions').fetchone()['previous_version_id'] is None
    assert client.get(path+'/files/'+template['template_file_id']+'/download').content==original
    assert client.get(endpoint+'/versions/1').json()['snapshot']==root['versions'][0]['snapshot']
    from app.maintenance.database_audit import audit_database
    with database_connection() as db:audit=audit_database(db)
    assert audit['ok'],audit['schema_issues'] or [c for c in audit['data_checks'] if c['invalid']]


def test_school_change_seal_lifecycle_and_readonly_audit(client):
    path,_,_,root,endpoint=base(client)
    source=upload_return(client,path,root['versions'][0]['snapshot'])
    change=post(client,endpoint+'/versions/1/school-changes',source,'input').json()
    with pytest.raises(SQLAlchemyError):
        with database_connection(write=True) as db:db.execute("UPDATE manuscript_school_changes SET input_json='{}' WHERE id=%s",(change['id'],))
    with pytest.raises(SQLAlchemyError):
        with database_connection(write=True) as db:db.execute('DELETE FROM manuscript_school_changes WHERE id=%s',(change['id'],))
    assessment=client.get(path+'/files/'+source['file_id']+'/lifecycle/assessment')
    assert assessment.status_code==200,assessment.text
    assert assessment.json()['counts']['manuscript_school_changes']==1
    assert any(r['code']=='school_change_history_retained' for r in assessment.json()['reasons'])
    from app.maintenance.database_audit import audit_database
    with database_connection() as db:audit=audit_database(db)
    assert audit['ok'],audit['schema_issues'] or [c for c in audit['data_checks'] if c['invalid']]
