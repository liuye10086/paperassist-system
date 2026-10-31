"""A real 0059 -> 0060 upgrade in a newly created, disposable test schema."""
import importlib.util
import re
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.pool import NullPool
from psycopg.types.json import Jsonb

from app.db.database import (DatabaseConfig, alembic_config, get_database_config,
    get_migration_database_config, migration_connection, database_connection, verify_runtime_permissions)


@pytest.fixture(autouse=True)
def postgres_schema(monkeypatch,tmp_path):
    from app.core.config import local_config
    schema='pa_test_'+uuid4().hex
    config=DatabaseConfig('test',local_config()['PAPERASSIST_TEST_DATABASE_URL'],schema)
    monkeypatch.setenv('PAPERASSIST_ENV','test')
    monkeypatch.setenv('PAPERASSIST_DB_SCHEMA',schema)
    monkeypatch.setenv('PAPERASSIST_DATA_DIR',str(tmp_path/'data'))
    migration=get_migration_database_config()
    engine=create_engine(migration.url,poolclass=NullPool)
    with engine.begin() as conn:
        assert conn.exec_driver_sql('SELECT current_database()').scalar_one()=='paperassist_system_test'
        conn.exec_driver_sql(f'CREATE SCHEMA {schema}')
    try:
        with migration_connection(write=True) as db:
            cfg=alembic_config()
            cfg.attributes.update(connection=db.raw_connection,database_config=migration)
            command.upgrade(cfg,'0059_bio_spatial_analysis')
        yield config
    finally:
        assert re.fullmatch(r'pa_test_[0-9a-f]{32}',schema)
        with engine.begin() as conn:
            assert conn.exec_driver_sql('SELECT current_database()').scalar_one()=='paperassist_system_test'
            conn.exec_driver_sql(f'DROP SCHEMA {schema} CASCADE')
        engine.dispose()


def upgrade():
    with migration_connection(write=True) as db:
        cfg=alembic_config()
        cfg.attributes.update(connection=db.raw_connection,database_config=get_migration_database_config())
        command.upgrade(cfg,'head')


def seed():
    with migration_connection(write=True) as db:
        db.execute("INSERT INTO users(id,email,password_hash,role,active,created_at,updated_at) VALUES('u','u@example.invalid','unused','user',true,0,0)")
        for ident,kind in [('p','research'),('q','research'),('sci','sci'),('thesis','thesis')]:
            db.execute('INSERT INTO projects(id,name,research_topic,project_type,created_at,updated_at,owner_id) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                       (ident,ident,'topic',kind,'2026-10-30T00:00:00Z','2026-10-30T00:00:00Z','u'))
            db.execute('INSERT INTO research_intakes(project_id,owner_id,created_at,updated_at) VALUES(%s,%s,now(),now())',(ident,'u'))
            db.execute("INSERT INTO research_deliveries(id,project_id,kind,name,origin,created_at,updated_at) VALUES(%s,%s,'sci_draft','SCI','user_selected',now(),now())",(ident+'-delivery',ident))
        for ident in ('p','q'):
            db.execute("INSERT INTO files(id,project_id,filename,file_type,size_bytes,sha256,uploaded_at,parse_status) VALUES(%s,%s,'same.png','png',1,%s,'2026-10-30T00:00:00Z','stored')",(ident+'-file',ident,'a'*64))
        for ident in ('sci','thesis'):
            db.execute("INSERT INTO manuscripts(id,project_id,user_id,idempotency_key,request_json,request_digest,current_revision,title,created_at,updated_at) VALUES(%s,%s,'u',%s,'{}',%s,1,'old title',now(),now())",(ident+'-m',ident,ident+'-key','b'*64))


def finding(project='p',ident='v',key='save'):
    with database_connection(write=True) as db:
        db.execute("INSERT INTO research_finding_sets(id,project_id,user_id,title,created_at,updated_at) VALUES(%s,%s,'u','set',now(),now())",(ident+'-set',project))
        db.execute("INSERT INTO research_finding_versions(id,project_id,user_id,set_id,revision,content_json,content_sha256,request_key,request_digest,created_at) VALUES(%s,%s,'u',%s,1,'{}',%s,%s,%s,now())",(ident,project,ident+'-set','a'*64,key,'b'*64))


def test_upgrade_preserves_every_old_column_value_and_runtime_grants(tmp_path):
    seed()
    seed_b02()
    import hashlib
    asset=tmp_path/'old-b02-synthetic-asset.txt'
    asset.write_bytes(b'preserve original B02 synthetic asset\n')
    asset_sha=hashlib.sha256(asset.read_bytes()).hexdigest()
    with migration_connection() as db:
        tables=[r['tablename'] for r in db.execute("SELECT tablename FROM pg_tables WHERE schemaname=current_schema() AND tablename<>'alembic_version'")]
        columns={t:[r['column_name'] for r in db.execute('SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=%s ORDER BY ordinal_position',(t,))] for t in tables}
        before={t:db.execute('SELECT '+','.join(columns[t])+' FROM '+t+' ORDER BY '+columns[t][0]).fetchall() for t in tables}
    upgrade()
    with database_connection() as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()['version_num']=='0060_research_results_bridge'
        for t in tables:
            assert db.execute('SELECT '+','.join(columns[t])+' FROM '+t+' ORDER BY '+columns[t][0]).fetchall()==before[t], t
        verify_runtime_permissions(db.raw_connection,get_database_config())
        from app.maintenance.database_audit import audit_database
        audit=audit_database(db)
        if audit['schema_issues']:
            from app.maintenance.database_audit import _check_signature
            from sqlalchemy import inspect, CheckConstraint
            from app.db.schema import metadata
            actual={x['name']:x['sqltext'] for x in inspect(db.raw_connection).get_check_constraints('tasks')}
            expected={x.name:str(x.sqltext) for x in metadata.tables['tasks'].constraints if isinstance(x,CheckConstraint)}
            mismatch={k:(expected[k],actual.get(k)) for k in expected if _check_signature(expected[k])!=_check_signature(actual.get(k))}
            assert not audit['schema_issues'],(audit['schema_issues'],mismatch)
    assert hashlib.sha256(asset.read_bytes()).hexdigest()==asset_sha


def test_typed_project_bindings_reject_wrong_kind_double_id_and_cross_project():
    seed();upgrade();finding()
    sql="""INSERT INTO research_source_bindings(id,project_id,user_id,parent_kind,finding_version_id,source_kind,
           source_id,file_id,external_evidence_version_id,locator_json,source_sha256,role,created_at)
           VALUES(%s,'p','u','finding','v',%s,%s,%s,%s,'{}',%s,'user_results',now())"""
    with database_connection(write=True) as db:
        db.execute(sql,('good','original_file','p-file','p-file',None,'a'*64))
    for ident,kind,source,file,evidence in [('cross','original_file','q-file','q-file',None),
                                         ('kind','bio_figure_version','p-file','p-file',None),
                                         ('double','original_file','p-file','p-file','missing')]:
        with pytest.raises(IntegrityError):
            with database_connection(write=True) as db:
                db.execute(sql,(ident,kind,source,file,evidence,'a'*64))
    with pytest.raises(IntegrityError):
        finding(ident='duplicate',key='save')
    with pytest.raises(SQLAlchemyError):
        with database_connection(write=True) as db:
            db.execute("UPDATE research_finding_versions SET content_json='{}' WHERE id='v'")
    with pytest.raises(SQLAlchemyError):
        with migration_connection(write=True) as db:
            db.execute("DELETE FROM research_finding_versions WHERE id='v'")


def task(db,ident='t',kind='research_fact_draft',project='p'):
    workflow='research_results_methods_v1' if kind=='research_fact_draft' else kind+'_v1'
    snapshot=dict(schema_version=1,kind=kind,project_id=project,real_model_calls=False,real_network_calls=False)
    if kind=='bio_import':
        snapshot.update(workflow_version=workflow,files=[{'file_id':'p-file'}],settings={})
    elif kind in ('bio_analysis','bio_figure'):
        snapshot.update(workflow_version=workflow,engine_version='visium_explore_v1.0.0',environment_digest='a'*64,code_digest='b'*64,limits={})
    db.execute("""INSERT INTO tasks(id,project_id,user_id,task_type,idempotency_key,input_digest,input_snapshot,
               workflow_version,status,phase,revision,current_attempt,created_at,updated_at)
               VALUES(%s,%s,'u',%s,%s,%s,%s,%s,'queued','write',1,0,now(),now())""",
               (ident,project,kind,ident,'a'*64,Jsonb(snapshot),workflow))


def seed_b02():
    """A synthetic but real FK-closed legacy processed dataset, never B02 acceptance data."""
    from datetime import datetime,timezone
    from app.db.schema import metadata
    now=datetime.now(timezone.utc)
    def insert(db,table_name,**values):
        db.raw_connection.execute(metadata.tables[table_name].insert(),values)
    with migration_connection(write=True) as db:
        for ident,kind in [('raw-task','bio_import'),('analysis-task','bio_analysis'),('figure-task','bio_figure')]:
            task(db,ident,kind)
        insert(db,'storage_objects',id='b02-object',namespace='synthetic',object_key='b02/manifest.json',size_bytes=2,sha256='a'*64,state='present')
        insert(db,'storage_references',object_id='b02-object',project_id='p',owner_id='u',kind='bio_analysis')
        insert(db,'bio_datasets',id='dataset',project_id='p',name='synthetic',assay='visium',revision=1,created_by='u',created_at=now,updated_at=now)
        insert(db,'bio_imports',id='import',project_id='p',dataset_id='dataset',task_id='raw-task',request_key='import',request_digest='a'*64,parser_version='synthetic',input_sha256='a'*64,expected_dataset_revision=1,settings_json={},created_at=now)
        insert(db,'bio_import_files',import_id='import',file_id='p-file',project_id='p',declared_role='bundle',source_sha256='a'*64,source_size_bytes=1)
        insert(db,'bio_dataset_versions',id='raw',dataset_id='dataset',project_id='p',version=1,import_id='import',task_id='raw-task',manifest_object_id='b02-object',manifest_sha256='a'*64,parser_version='synthetic',shape_json={},checks_json={},created_by='u',created_at=now)
        common=dict(project_id='p',created_by='u',created_at=now)
        insert(db,'bio_analysis_setups',id='setup',raw_dataset_version_id='raw',name='legacy setup',updated_at=now,**common)
        insert(db,'bio_analysis_recipe_versions',id='recipe',setup_id='setup',version=1,raw_dataset_version_id='raw',request_key='recipe',request_digest='a'*64,recipe_code='visium_explore_v1',params_json={},default_figures_json={},engine_contract_version='synthetic',**common)
        insert(db,'bio_analysis_runs',id='run',raw_dataset_version_id='raw',recipe_version_id='recipe',task_id='analysis-task',source_digest='a'*64,execution_snapshot_object_id='b02-object',execution_snapshot_sha256='a'*64,expected_setup_revision=1,request_key='run',request_digest='a'*64,**common)
        insert(db,'bio_processed_dataset_versions',id='processed',raw_dataset_version_id='raw',run_id='run',task_id='analysis-task',recipe_version_id='recipe',manifest_object_id='b02-object',manifest_sha256='a'*64,shape_json={},steps_json={},environment_digest='a'*64,code_digest='b'*64,engine_version='visium_explore_v1.0.0',**common)
        insert(db,'bio_analysis_artifacts',id='artifact',processed_dataset_version_id='processed',key='summary',role='table',format='json',storage_object_id='b02-object',size_bytes=2,sha256='a'*64,shape_json={},**common)
        insert(db,'bio_figure_versions',id='bio-figure',root_id='bio-figure',version=1,processed_dataset_version_id='processed',task_id='figure-task',config_json={},config_sha256='a'*64,renderer_version='synthetic',manifest_object_id='b02-object',manifest_sha256='a'*64,request_key='figure',request_digest='a'*64,**common)
        insert(db,'bio_figure_members',id='bio-member',figure_version_id='bio-figure',key='png',format='png',storage_object_id='b02-object',size_bytes=2,sha256='a'*64,**common)
        db.execute("UPDATE tasks SET status='succeeded',result_bio_dataset_version_id='raw' WHERE id='raw-task'")
        db.execute("UPDATE tasks SET status='succeeded',result_bio_processed_dataset_version_id='processed' WHERE id='analysis-task'")
        db.execute("UPDATE tasks SET status='succeeded',result_bio_figure_version_id='bio-figure' WHERE id='figure-task'")
        db.execute("UPDATE bio_analysis_runs SET processed_dataset_version_id='processed' WHERE id='run'")


def test_candidate_first_draft_pairing_and_task_backed_results():
    seed();upgrade()
    sql="""INSERT INTO research_manuscript_candidates(id,project_id,user_id,delivery_id,manuscript_id,base_version_id,
           expected_revision,task_id,scope_json,request_key,request_digest,created_at)
           VALUES(%s,'p','u','p-delivery',%s,%s,%s,%s,'{}',%s,%s,now())"""
    with database_connection(write=True) as db:
        task(db)
        db.execute(sql,('candidate',None,None,0,'t','candidate','a'*64))
        task(db,'t2')
    with pytest.raises(IntegrityError):
        with database_connection(write=True) as db:
            db.execute(sql,('bad','sci-m',None,1,'t2','bad','a'*64))
    with pytest.raises(IntegrityError):
        with database_connection(write=True) as db:
            db.execute("UPDATE tasks SET result_research_candidate_id='candidate' WHERE id='t'")
    with pytest.raises(IntegrityError):
        with database_connection(write=True) as db:
            db.execute("UPDATE tasks SET status='succeeded',result_research_candidate_id='candidate' WHERE id='t2'")
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET status='succeeded',result_research_candidate_id='candidate' WHERE id='t'")


def test_existing_candidate_rejects_a_base_from_another_manuscript_and_wrong_revision():
    seed();upgrade()
    with database_connection(write=True) as db:
        for ident in ('m1','m2'):
            task(db,ident+'-task','manuscript_draft')
            db.execute("""INSERT INTO manuscripts(id,project_id,user_id,idempotency_key,request_json,request_digest,
                current_revision,title,created_at,updated_at,delivery_id,document_kind)
                VALUES(%s,'p','u',%s,'{}',%s,1,'research draft',now(),now(),'p-delivery','sci')""",(ident,ident,'a'*64))
            db.execute("""INSERT INTO manuscript_versions(id,project_id,user_id,idempotency_key,request_json,request_digest,
                manuscript_id,revision,task_id,snapshot_json,snapshot_sha256,created_at)
                VALUES(%s,'p','u',%s,'{}',%s,%s,1,%s,'{}',%s,now())""",(ident+'-version',ident,'a'*64,ident,ident+'-task','b'*64))
        task(db,'candidate-task')
    for base,revision in [('m2-version',1),('m1-version',2)]:
        with pytest.raises(IntegrityError):
            with database_connection(write=True) as db:
                db.execute("""INSERT INTO research_manuscript_candidates(id,project_id,user_id,delivery_id,
                    manuscript_id,base_version_id,expected_revision,task_id,scope_json,request_key,request_digest,created_at)
                    VALUES('candidate','p','u','p-delivery','m1',%s,%s,'candidate-task','{}','candidate',%s,now())""",(base,revision,'a'*64))
    with database_connection(write=True) as db:
        db.execute("""INSERT INTO research_manuscript_candidates(id,project_id,user_id,delivery_id,
            manuscript_id,base_version_id,expected_revision,task_id,scope_json,request_key,request_digest,created_at)
            VALUES('candidate','p','u','p-delivery','m1','m1-version',1,'candidate-task','{}','candidate',%s,now())""",('a'*64,))
    with pytest.raises(SQLAlchemyError):
        with database_connection(write=True) as db:
            db.execute("UPDATE research_manuscript_candidates SET candidate_json='{}',candidate_sha256=%s,published_version_id='m2-version',publish_key='publish' WHERE id='candidate'",('a'*64,))


def test_new_research_manuscripts_require_same_project_delivery_and_matching_kind():
    seed();upgrade()
    sql="""INSERT INTO manuscripts(id,project_id,user_id,idempotency_key,request_json,request_digest,
           current_revision,title,created_at,updated_at,delivery_id,document_kind)
           VALUES('new','p','u','new','{}',%s,1,'draft',now(),now(),%s,%s)"""
    for delivery,kind in [(None,None),('q-delivery','sci'),('p-delivery','thesis'),('p-delivery',None)]:
        with pytest.raises(SQLAlchemyError):
            with database_connection(write=True) as db:
                db.execute(sql,('a'*64,delivery,kind))
    with database_connection(write=True) as db:
        db.execute(sql,('a'*64,'p-delivery','sci'))


def test_report_and_figure_result_columns_are_exact_task_and_source_scoped():
    seed();upgrade();finding()
    with database_connection(write=True) as db:
        task(db,'figure-task','research_figure')
        task(db,'other-figure-task','research_figure')
        task(db,'report-task','research_report')
        db.execute("""INSERT INTO research_figure_versions(id,project_id,user_id,root_id,revision,task_id,
            config_json,config_sha256,request_key,request_digest,created_at)
            VALUES('figure','p','u','figure',1,'figure-task','{}',%s,'figure',%s,now())""",('a'*64,'b'*64))
        db.execute("""INSERT INTO research_report_versions(id,project_id,user_id,root_id,revision,task_id,
            finding_version_id,language,content_json,content_sha256,request_key,request_digest,created_at)
            VALUES('report','p','u','report',1,'report-task','v','zh-CN','{}',%s,'report',%s,now())""",('a'*64,'b'*64))
    for sql in ("UPDATE tasks SET status='succeeded',result_research_figure_version_id='figure' WHERE id='other-figure-task'",
                "UPDATE tasks SET status='succeeded',result_research_figure_version_id='figure' WHERE id='report-task'",
                "UPDATE tasks SET result_research_report_version_id='report' WHERE id='report-task'"):
        with pytest.raises(IntegrityError):
            with database_connection(write=True) as db:
                db.execute(sql)
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET status='succeeded',result_research_figure_version_id='figure' WHERE id='figure-task'")
        db.execute("UPDATE tasks SET status='succeeded',result_research_report_version_id='report' WHERE id='report-task'")


def test_research_output_intent_cannot_bind_a_task_of_another_user():
    seed();upgrade()
    with migration_connection(write=True) as db:
        db.execute("INSERT INTO users(id,email,password_hash,role,active,created_at,updated_at) VALUES('other','other@example.invalid','unused','user',true,0,0)")
        task(db,'other-task','research_figure')
        db.execute("UPDATE tasks SET user_id='other' WHERE id='other-task'")
    with pytest.raises(IntegrityError):
        with database_connection(write=True) as db:
            db.execute("""INSERT INTO research_figure_versions(id,project_id,user_id,root_id,revision,task_id,
                config_json,config_sha256,request_key,request_digest,created_at)
                VALUES('figure','p','u','figure',1,'other-task','{}',%s,'figure',%s,now())""",('a'*64,'b'*64))
