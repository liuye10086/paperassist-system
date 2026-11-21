"""Additive 0028 migration, historical byte preservation and downgrade guards."""
from tests.helpers.legacy_plans import seed_legacy_plan
import hashlib
import json
import os
from pathlib import Path
import pytest
from sqlalchemy import inspect
from alembic import command
from app.db.database import database_connection,verify_runtime_permissions
from tests.helpers.historical_migration import historical_workflow
from tests.api.test_analysis import client

NEW_TABLES=('external_evidence_versions','prepared_dataset_derivations_v3')


def test_0028_schema_and_minimal_runtime_permissions(postgres_schema):
    from app.maintenance.database_audit import audit_database
    with database_connection() as db:
        verify_runtime_permissions(db.raw_connection,postgres_schema)
        assert audit_database(db)['ok']
        inspector=inspect(db.raw_connection)
        assert all(table in inspector.get_table_names() for table in NEW_TABLES)
        assert len(inspector.get_foreign_keys('external_evidence_versions'))==6
        assert len(inspector.get_foreign_keys('prepared_dataset_derivations_v3'))==2
        if os.environ.get('BATCH09_SCHEMA_FIXTURE'):
            columns=[dict(r) for r in db.execute("""SELECT table_name,column_name,data_type,udt_name,is_nullable,column_default,ordinal_position
                FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=ANY(%s) ORDER BY table_name,ordinal_position""",(list(NEW_TABLES),))]
            indexes=[dict(r) for r in db.execute("""SELECT c.relname AS name,t.relname AS table_name,pg_get_indexdef(i.indexrelid) AS definition,i.indisvalid AS valid,i.indisready AS ready
                FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_class t ON t.oid=i.indrelid JOIN pg_namespace n ON n.oid=t.relnamespace
                WHERE n.nspname=current_schema() AND t.relname=ANY(%s) ORDER BY c.relname""",(list(NEW_TABLES),))]
            constraints=[dict(r) for r in db.execute("""SELECT t.relname AS table_name,c.conname,c.contype,c.convalidated,pg_get_constraintdef(c.oid) AS definition
                FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace
                WHERE n.nspname=current_schema() AND t.relname=ANY(%s) ORDER BY c.conname""",(list(NEW_TABLES),))]
            body=json.dumps(dict(revision='0028_research_materials',parent_revision='0027_quality_derivations',
                columns=columns,indexes=indexes,constraints=constraints,new_indexes={r['name']:r for r in indexes},new_constraints=constraints),ensure_ascii=False,indent=2)
            Path(os.environ['BATCH09_SCHEMA_FIXTURE']).write_text(body.replace(postgres_schema.schema,'public'),encoding='utf-8')


def test_0028_preserves_all_previous_rows_columns_indexes_and_report_assets(client,monkeypatch,postgres_migration_config):
    from tests.integration.test_batch05_collection_pipeline import complete_collection
    repository,project,result,state,_,_=complete_collection(client,monkeypatch)
    request=state['versions'][0]['requests'][0]
    report,word=repository.download(project,state['id'],request['report']['id'])
    with historical_workflow(postgres_migration_config, '0027_quality_derivations') as (db, settings):
        saved = db.execute('SELECT * FROM collection_reports WHERE id=%s', (report['id'],)).fetchone()
        assert saved['report_json'] == report and saved['sha256'] == hashlib.sha256(word).hexdigest()
        inspector=inspect(db.raw_connection)
        names=[n for n in inspector.get_table_names() if n!='alembic_version']
        columns={n:[{**c,'type':str(c['type'])} for c in inspector.get_columns(n)] for n in names}
        rows={n:[dict(r) for r in db.execute('SELECT * FROM '+n)] for n in names}
        indexes={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        command.upgrade(settings,'0028_research_materials')
        inspector=inspect(db.raw_connection)
        assert {n:[dict(r) for r in db.execute('SELECT * FROM '+n)] for n in names}==rows
        assert {n:[{**c,'type':str(c['type'])} for c in inspector.get_columns(n)] for n in names}==columns
        after={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        assert all(after[n]==value for n,value in indexes.items())
    assert repository.download(project,state['id'],request['report']['id'])[1]==word


@pytest.mark.parametrize('history',['evidence','requirement','filter'])
def test_0028_blocks_downgrade_if_new_history_exists(client,postgres_migration_config,history):
    if history=='evidence':
        from tests.integration.test_batch09_external_evidence import saved
        saved(client)
    elif history=='requirement':
        from tests.helpers.analysis_plan import prepared_sample
        from tests.integration.test_research_plan import research
        base,file,prepared=prepared_sample(client)
        response=seed_legacy_plan(client, base+'/analysis-plans',json=dict(schema_version=4,input_kind='data',file_id=file['id'],dataset_id=prepared['id'],
            expected_setup_revision=0,selection=None,research_request=research(),evidence_version_ids=[]),headers={'Idempotency-Key':'guard'})
        assert response.status_code==202,response.text
    else:
        from tests.integration.test_batch09_filter_pipeline import filtering
        from tests.integration.test_batch07_quality_pipeline import published
        base,parent=published(client)
        filtering(client,base,parent)
    with historical_workflow(postgres_migration_config, '0028_research_materials') as (db, settings):
        if history == 'evidence':
            before = db.execute('SELECT * FROM external_evidence_versions').fetchall()
        else:
            workflow = 'analysis_plan_v4' if history == 'requirement' else 'dataset_preparation_v3'
            before = db.execute('SELECT * FROM tasks WHERE workflow_version=%s', (workflow,)).fetchall()
        assert before
        with pytest.raises(RuntimeError, match='history or v4 workflow state'):
            with db.raw_connection.begin_nested():
                command.downgrade(settings, '0027_quality_derivations')
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()['version_num'] == '0028_research_materials'
        if history == 'evidence':
            assert db.execute('SELECT * FROM external_evidence_versions').fetchall() == before
        else:
            assert db.execute('SELECT * FROM tasks WHERE workflow_version=%s', (workflow,)).fetchall() == before
