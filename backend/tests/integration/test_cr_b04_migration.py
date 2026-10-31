"""CR-B04 migration tests use only fresh, disposable PostgreSQL schemas."""
import re
import runpy
from pathlib import Path
from uuid import uuid4
import pytest
from alembic import command
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.pool import NullPool
from psycopg.types.json import Jsonb
from app.db.database import (DatabaseConfig, alembic_config, get_database_config,
    get_migration_database_config, migration_connection, database_connection, verify_runtime_permissions)

LEGACY = runpy.run_path(str(Path(__file__).with_name('test_cr_b03_migration.py')))
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
            command.upgrade(cfg,'0060_research_results_bridge')
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
        command.upgrade(cfg,'0061_bio_insights')


def test_upgrade_preserves_old_columns_and_matches_application_metadata():
    LEGACY['seed'](); LEGACY['seed_b02'](); LEGACY['finding']()
    with migration_connection() as db:
        tables=[r['tablename'] for r in db.execute("SELECT tablename FROM pg_tables WHERE schemaname=current_schema() AND tablename<>'alembic_version'")]
        columns={t:[r['column_name'] for r in db.execute('SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=%s ORDER BY ordinal_position',(t,))] for t in tables}
        before={t:db.execute('SELECT '+','.join(columns[t])+' FROM '+t+' ORDER BY '+columns[t][0]).fetchall() for t in tables}
    upgrade()
    with database_connection() as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()['version_num']=='0061_bio_insights'
        for t in tables:
            assert db.execute('SELECT '+','.join(columns[t])+' FROM '+t+' ORDER BY '+columns[t][0]).fetchall()==before[t],t
        verify_runtime_permissions(db.raw_connection,get_database_config())
        from app.maintenance.database_audit import audit_database
        from app.maintenance.database_audit import _check_signature
        from sqlalchemy import CheckConstraint, inspect
        from app.db.schema import metadata
        actual={c['name']:c['sqltext'] for c in inspect(db.raw_connection).get_check_constraints('tasks')}
        mismatches={c.name:(str(c.sqltext),actual.get(c.name)) for c in metadata.tables['tasks'].constraints
                    if isinstance(c,CheckConstraint) and _check_signature(str(c.sqltext))!=_check_signature(actual.get(c.name))}
        assert audit_database(db)['schema_issues']==[], mismatches


def insert(db, table_name, **values):
    from datetime import datetime, timezone
    from app.db.schema import metadata
    row = dict(project_id='p', user_id='u', created_at=datetime.now(timezone.utc))
    row.update(values)
    db.raw_connection.execute(metadata.tables[table_name].insert(), row)


def insight_task(db, ident, kind='bio_comparison', **snapshot):
    content=dict(schema_version=1,kind=kind,project_id='p',workflow_version=kind+'_v1',
                 output_language='zh-CN',real_model_calls=False,real_network_calls=False,**snapshot)
    db.execute("""INSERT INTO tasks(id,project_id,user_id,task_type,idempotency_key,input_digest,input_snapshot,
               workflow_version,status,phase,revision,current_attempt,created_at,updated_at)
               VALUES(%s,'p','u',%s,%s,%s,%s,%s,'queued','compute',1,0,now(),now())""",
               (ident,kind,ident,'a'*64,Jsonb(content),kind+'_v1'))


def setup(with_source=False):
    LEGACY['seed'](); LEGACY['seed_b02'](); LEGACY['finding'](); upgrade()
    from datetime import datetime,timezone
    now=datetime.now(timezone.utc)
    with database_connection(write=True) as db:
        insert(db,'bio_insight_plans',id='plan',kind='comparison',name='plan',updated_at=now,created_at=now)
        insert(db,'bio_insight_plan_versions',id='draft',plan_id='plan',version=1,kind='comparison',decision='draft',
               config_json={},config_sha256='a'*64,design_checks_json={},request_key='draft',request_digest='a'*64)
        db.execute("UPDATE bio_insight_plans SET current_version_id='draft' WHERE id='plan'")
        insert(db,'bio_insight_plan_versions',id='confirmed',plan_id='plan',version=2,parent_id='draft',kind='comparison',decision='confirmed',
               config_json={},config_sha256='a'*64,design_checks_json={},confirmed_by='u',confirmed_at=now,
               request_key='confirmed',request_digest='a'*64,created_at=now)
        if with_source:
            source(db)
        db.execute("UPDATE bio_insight_plans SET current_version_id='confirmed',revision=2 WHERE id='plan'")


def source(db, ident='source', **changes):
    row=dict(id=ident,plan_version_id='confirmed',source_kind='original_file',source_id='p-file',file_id='p-file',
             role='input',ordinal=0,source_sha256='a'*64,locator_json={})
    row.update(changes)
    insert(db,'bio_insight_plan_sources',**row)


def run(db, ident='insight-run', **changes):
    row=dict(id=ident,plan_version_id='confirmed',kind='comparison',decision='confirmed',task_id=ident+'-task',
             task_type='bio_comparison',source_digest='a'*64,execution_snapshot_object_id='b02-object',
             execution_snapshot_sha256='a'*64,expected_plan_revision=2,request_key=ident,request_digest='a'*64)
    row.update(changes)
    insight_task(db,ident+'-task',row['task_type'],run_id=ident,plan_version_id=row['plan_version_id'],source_digest='a'*64)
    insert(db,'bio_insight_runs',**row)


def test_confirmed_lineage_sources_and_runs_reject_wrong_identity():
    setup(with_source=True)
    for changes in [dict(file_id='q-file',source_id='q-file'),dict(source_kind='bio_resource_version'),
                    dict(processed_version_id='processed'),dict(parse_version_id='missing')]:
        with pytest.raises(IntegrityError):
            with database_connection(write=True) as db:
                insert(db,'bio_insight_plan_versions',id='third',plan_id='plan',version=3,parent_id='confirmed',kind='comparison',decision='draft',
                       config_json={},config_sha256='a'*64,design_checks_json={},request_key='third',request_digest='a'*64)
                source(db,'third-source',plan_version_id='third',**changes)
    for changes in [dict(plan_version_id='draft'),dict(kind='candidate'),dict(task_type='bio_candidate'),
                    dict(decision='draft'),dict(source_digest='b'*64)]:
        with pytest.raises(SQLAlchemyError):
            with database_connection(write=True) as db: run(db,**changes)
    with database_connection(write=True) as db:
        run(db)
    for sql in ["UPDATE bio_insight_plan_versions SET decision='confirmed' WHERE id='draft'",
                "UPDATE bio_insight_runs SET source_digest=repeat('b',64) WHERE id='insight-run'",
                "UPDATE bio_insight_plans SET revision=3,current_version_id='draft' WHERE id='plan'",
                "DELETE FROM bio_insight_plan_sources WHERE id='source'"]:
        with pytest.raises(SQLAlchemyError):
            with database_connection(write=True) as db: db.execute(sql)
    with pytest.raises(SQLAlchemyError):
        with database_connection(write=True) as db: source(db,'late',ordinal=1)


def test_results_have_exact_run_task_scope_and_immutable_members():
    setup(with_source=True)
    with database_connection(write=True) as db:
        run(db); run(db,'other-run')
    result=dict(id='result',run_id='insight-run',task_id='insight-run-task',plan_version_id='confirmed',kind='comparison',
                provenance='system_computed',inference_scope='spot_exploratory',manifest_object_id='b02-object',manifest_sha256='a'*64,
                summary_json={},methods_json={},environment_digest='a'*64,code_digest='a'*64)
    for changes in [dict(task_id='other-run-task'),dict(kind='candidate'),dict(manifest_sha256=None),dict(provenance='external_result')]:
        with pytest.raises(IntegrityError):
            with database_connection(write=True) as db: insert(db,'bio_insight_result_versions',**{**result,**changes})
    with database_connection(write=True) as db:
        insert(db,'bio_insight_result_versions',**result)
        insert(db,'bio_insight_result_members',id='member',result_version_id='result',key='table',role='table',format='tsv',
               storage_object_id='b02-object',size_bytes=2,sha256='a'*64,shape_json={})
        db.execute("UPDATE bio_insight_runs SET result_version_id='result' WHERE id='insight-run'")
    for ident in ('insight-run-task','other-run-task'):
        with pytest.raises(IntegrityError):
            with database_connection(write=True) as db:
                db.execute("UPDATE tasks SET result_bio_insight_result_version_id='result' WHERE id=%s",(ident,))
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET status='succeeded',result_bio_insight_result_version_id='result' WHERE id='insight-run-task'")
        db.execute("""INSERT INTO research_source_bindings(id,project_id,user_id,parent_kind,finding_version_id,source_kind,
           source_id,bio_insight_result_member_id,locator_json,source_sha256,role,created_at)
           VALUES('binding','p','u','finding','v','bio_insight_result_member','member','member','{}',%s,'computed_results',now())""",('a'*64,))
    for sql in ["UPDATE bio_insight_result_versions SET summary_json='{}' WHERE id='result'",
                "DELETE FROM bio_insight_result_members WHERE id='member'",
                "UPDATE bio_insight_runs SET result_version_id=NULL WHERE id='insight-run'"]:
        with pytest.raises(SQLAlchemyError):
            with database_connection(write=True) as db: db.execute(sql)
    with pytest.raises(SQLAlchemyError):
        with database_connection(write=True) as db:
            insert(db,'bio_insight_result_members',id='late',result_version_id='result',key='late',role='table',format='tsv',
                   storage_object_id='b02-object',size_bytes=2,sha256='a'*64,shape_json={})


def test_resource_publication_is_once_only_and_raw_members_need_no_parser():
    setup()
    with database_connection(write=True) as db:
        insight_task(db,'resource-task','bio_resource_import',resource_version_id='resource')
        insert(db,'bio_resource_versions',id='resource',root_id='resource',version=1,kind='gene_sets',title='Synthetic GMT',
               species_taxon_id=9606,namespace='Ensembl',release='synthetic',source_json={},usage_json={},config_json={},
               config_sha256='a'*64,task_id='resource-task',task_type='bio_resource_import',request_key='resource',request_digest='a'*64)
        insert(db,'bio_resource_members',id='resource-member',resource_version_id='resource',key='original',role='original',format='gmt',
               storage_object_id='b02-object',size_bytes=2,sha256='a'*64,shape_json={},original_file_id='p-file')
        db.execute("UPDATE bio_resource_versions SET manifest_object_id='b02-object',manifest_sha256=%s WHERE id='resource'",('a'*64,))
        db.execute("UPDATE tasks SET status='succeeded',result_bio_resource_version_id='resource' WHERE id='resource-task'")
    for sql in ["UPDATE bio_resource_versions SET manifest_sha256=repeat('b',64) WHERE id='resource'",
                "UPDATE bio_resource_versions SET config_json='{}' WHERE id='resource'",
                "DELETE FROM bio_resource_members WHERE id='resource-member'"]:
        if "config_json" in sql:
            sql=sql.replace("config_json='{}'", "config_json='{}',title='changed'")
        with pytest.raises(SQLAlchemyError):
            with database_connection(write=True) as db: db.execute(sql)
    with pytest.raises(SQLAlchemyError):
        with database_connection(write=True) as db:
            insert(db,'bio_resource_members',id='resource-late',resource_version_id='resource',key='late',role='original',format='gmt',
                   storage_object_id='b02-object',size_bytes=2,sha256='a'*64,shape_json={})


def test_all_six_task_snapshots_and_version_lineage_are_strict():
    setup()
    from app.db.bio_insights_schema import TASK_TYPES
    for kind in TASK_TYPES:
        payload=dict(resource_version_id='resource') if kind=='bio_resource_import' else dict(plan_version_id='confirmed',run_id='run',source_digest='a'*64)
        with database_connection(write=True) as db:
            insight_task(db,kind,kind,**payload)
        with pytest.raises(IntegrityError):
            with database_connection(write=True) as db:
                db.execute("UPDATE tasks SET input_snapshot='{}' WHERE id=%s",(kind,))
        with pytest.raises(IntegrityError):
            with database_connection(write=True) as db:
                db.execute("UPDATE tasks SET workflow_version='wrong' WHERE id=%s",(kind,))
    common=dict(id='next',plan_id='plan',version=4,parent_id='confirmed',kind='comparison',decision='draft',
                config_json={},config_sha256='a'*64,design_checks_json={},request_key='next',request_digest='a'*64)
    for changes in ({},dict(version=3,parent_id='missing'),dict(version=3,config_json=[]),dict(version=3,config_sha256='bad'),
                    dict(version=3,decision='confirmed')):
        with pytest.raises(SQLAlchemyError):
            with database_connection(write=True) as db:
                insert(db,'bio_insight_plan_versions',**{**common,**changes})
    with database_connection(write=True) as db:
        insert(db,'bio_insight_plan_versions',**{**common,'version':3})
    with pytest.raises(IntegrityError):
        with database_connection(write=True) as db:
            insert(db,'bio_insight_plan_versions',**{**common,'id':'duplicate-key','version':4,'parent_id':'next'})


def test_committed_confirmed_plan_cannot_accept_first_source_before_a_run():
    setup(with_source=True)
    with database_connection() as db:
        assert db.execute("SELECT count(*) AS n FROM bio_insight_runs").fetchone()['n']==0
    with pytest.raises(SQLAlchemyError):
        with database_connection(write=True) as db: source(db,'late-first',ordinal=1)


def test_sources_same_transaction_support_savepoints_and_override_spoofed_stamp():
    setup(with_source=True)
    def version(db, ident, number, parent):
        insert(db,'bio_insight_plan_versions',id=ident,plan_id='plan',version=number,parent_id=parent,kind='comparison',decision='draft',
               config_json={},config_sha256='a'*64,design_checks_json={},request_key=ident,request_digest='a'*64,
               sources_transaction_id='spoofed-client-transaction')
    with database_connection(write=True) as db:
        with db.raw_connection.begin_nested():
            version(db,'third',3,'confirmed')
        row=db.execute("SELECT sources_transaction_id=pg_current_xact_id()::text AS correct FROM bio_insight_plan_versions WHERE id='third'").fetchone()
        assert row['correct']
        source(db,'third-source',plan_version_id='third')
        db.execute("UPDATE bio_insight_plans SET revision=3,current_version_id='third' WHERE id='plan'")
    with database_connection(write=True) as db:
        version(db,'fourth',4,'third')
        source(db,'fourth-source',plan_version_id='fourth')
        db.execute("UPDATE bio_insight_plans SET revision=4,current_version_id='fourth' WHERE id='plan'")
    for ident in ('confirmed','third','fourth'):
        with pytest.raises(SQLAlchemyError):
            with database_connection(write=True) as db:
                source(db,'late-source',plan_version_id=ident,ordinal=1)
    with pytest.raises(SQLAlchemyError):
        with database_connection(write=True) as db:
            db.execute("UPDATE bio_insight_plan_versions SET sources_transaction_id=pg_current_xact_id()::text WHERE id='third'")


@pytest.mark.parametrize('mode',['run','resource'])
def test_bound_task_rejects_another_well_formed_snapshot_and_digest(mode):
    setup()
    with database_connection(write=True) as db:
        if mode=='run':
            run(db)
            ident='insight-run-task'
            changed=dict(run_id='different-run',plan_version_id='confirmed',source_digest='b'*64)
        else:
            insight_task(db,'resource-task','bio_resource_import',resource_version_id='resource')
            insert(db,'bio_resource_versions',id='resource',root_id='resource',version=1,kind='gene_sets',title='Synthetic GMT',
                   species_taxon_id=9606,namespace='Ensembl',release='synthetic',source_json={},usage_json={},config_json={},
                   config_sha256='a'*64,task_id='resource-task',task_type='bio_resource_import',request_key='resource',request_digest='a'*64)
            ident='resource-task'
            changed=dict(resource_version_id='different-resource')
    for mutation in ('snapshot','digest'):
        with pytest.raises(SQLAlchemyError):
            with database_connection(write=True) as db:
                if mutation=='snapshot':
                    db.execute('UPDATE tasks SET input_snapshot=input_snapshot||%s WHERE id=%s',(Jsonb(changed),ident))
                else:
                    db.execute('UPDATE tasks SET input_digest=%s WHERE id=%s',('b'*64,ident))
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET status='running',current_attempt=1,revision=2,updated_at=now() WHERE id=%s",(ident,))
        db.execute("INSERT INTO task_attempts(id,task_id,attempt_no,status,started_at,lease_owner,lease_expires_at,heartbeat_at) VALUES(%s,%s,1,'running',now(),'worker',now()+interval '2 minutes',now())",(ident+'-attempt',ident))
        db.execute("UPDATE task_attempts SET heartbeat_at=now(),lease_expires_at=now()+interval '3 minutes' WHERE task_id=%s",(ident,))
