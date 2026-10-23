"""0040→0041 preserves the old database and seals new scoped history."""
import pytest
from alembic import command
from sqlalchemy.exc import SQLAlchemyError
from tests.api.test_analysis import client  # noqa:F401
from tests.api.test_school_templates import setup,parsed,post
from tests.maintenance.test_literature_evidence_migration import fingerprints
from app.db.database import alembic_config,get_migration_database_config,migration_connection,database_connection


def test_school_migration_preserves_existing_rows_columns_indexes_and_constraints(client):
    path,body=setup(client)
    original=client.get(path+'/files/'+body['template_file_id']+'/download').content
    cfg=alembic_config()
    with migration_connection(write=True) as db:
        assert db.config.schema.startswith('pa_test_')
        assert db.execute('SELECT current_database() AS name').fetchone()['name']=='paperassist_system_test'
        cfg.attributes.update(connection=db.raw_connection,database_config=get_migration_database_config())
        command.downgrade(cfg,'0040_manuscript_writing_live')
        tables=[r['tablename'] for r in db.execute('SELECT tablename FROM pg_tables WHERE schemaname=current_schema()') if r['tablename']!='alembic_version']
        before=fingerprints(db,tables)
        indexes={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        constraints={r['conname']:r['definition'] for r in db.execute('SELECT conname,pg_get_constraintdef(oid) AS definition FROM pg_constraint WHERE connamespace=current_schema()::regnamespace')}
        columns=list(db.execute('SELECT table_name,column_name,data_type,is_nullable FROM information_schema.columns WHERE table_schema=current_schema() ORDER BY table_name,ordinal_position'))
        command.upgrade(cfg,'0041_school_templates')
        assert fingerprints(db,tables)==before
        after={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        assert all(after.get(k)==v for k,v in indexes.items())
        after_constraints={r['conname']:r['definition'] for r in db.execute('SELECT conname,pg_get_constraintdef(oid) AS definition FROM pg_constraint WHERE connamespace=current_schema()::regnamespace')}
        assert all(after_constraints.get(k)==v for k,v in constraints.items() if k!='tasks_type_check')
        after_columns=list(db.execute('SELECT table_name,column_name,data_type,is_nullable FROM information_schema.columns WHERE table_schema=current_schema() ORDER BY table_name,ordinal_position'))
        assert all(c in after_columns for c in columns)
        command.upgrade(cfg,'head')
    assert client.get(path+'/files/'+body['template_file_id']+'/download').content==original
    from app.maintenance.database_audit import audit_database
    with database_connection() as db: result=audit_database(db)
    assert result['ok'],result['schema_issues'] or [c for c in result['data_checks'] if c['invalid']]


def test_school_history_seal_scope_fks_and_downgrade_guard(client):
    path,_,item=parsed(client)
    saved=post(client,path+'/school-templates/'+item['id']+'/confirm',dict(analysis_sha256=item['analysis_sha256'],decisions=[dict(conflict_id='conflict-1',option_id='text-2')],chapters=[dict(id='body',title='正文',level=1)])).json()
    for table,clause in [('school_template_versions',"analysis_json='{}'"),('school_template_sources',"sha256='"+'a'*64+"'"),('school_template_confirmations',"snapshot_json='{}'")]:
        for statement in ('UPDATE '+table+' SET '+clause,'DELETE FROM '+table):
            with pytest.raises(SQLAlchemyError):
                with database_connection(write=True) as db: db.execute(statement)
    other_path,other_body=setup(client);other_id=other_path.rsplit('/',1)[1]
    for sql,args in [
        ('''INSERT INTO school_template_sources(id,project_id,user_id,template_version_id,file_id,role,source_json,sha256,document_version_id)
            SELECT 'foreign-source',project_id,user_id,template_version_id,%s,role,source_json,sha256,NULL FROM school_template_sources LIMIT 1''',(other_body['template_file_id'],)),
        ('''INSERT INTO thesis_profiles(project_id,user_id,revision,school,department,major,degree_type,education_level,applicable_version,bound_confirmation_id,updated_at)
            SELECT %s,user_id,1,'','','','','','',id,clock_timestamp() FROM school_template_confirmations LIMIT 1''',(other_id,))]:
        with pytest.raises(SQLAlchemyError):
            with database_connection(write=True) as db:db.execute(sql,args)
    cfg=alembic_config()
    with pytest.raises(RuntimeError,match='refusing destructive downgrade'):
        with migration_connection(write=True) as db:
            cfg.attributes.update(connection=db.raw_connection,database_config=get_migration_database_config())
            command.downgrade(cfg,'0040_manuscript_writing_live')


def test_school_audit_and_file_lifecycle_cover_retained_sources(client):
    path,body,item=parsed(client)
    from app.maintenance.school_template_audit import audit_school_templates
    with database_connection() as db:
        checks=audit_school_templates(db,limit=10)
    assert checks and all(c['invalid']==0 for c in checks),checks
    assessment=client.get(path+'/files/'+body['template_file_id']+'/lifecycle/assessment')
    assert assessment.status_code==200,assessment.text
    assert assessment.json()['counts']['school_template_versions']==1
    assert any(r['code']=='school_template_history_retained' for r in assessment.json()['reasons'])


def test_school_audit_reports_corrupt_task_digest_with_bounded_counts(client):
    path,_,item=parsed(client)
    from app.maintenance.school_template_audit import audit_school_templates
    with database_connection(write=True) as db:db.execute('UPDATE tasks SET input_digest=%s WHERE id=%s',('a'*64,item['task']['id']))
    with database_connection() as db:checks=audit_school_templates(db,limit=1)
    assert next(c for c in checks if c['table']=='school_template_versions')['invalid']==1
    assert all(c['rows']<=1 for c in checks)
