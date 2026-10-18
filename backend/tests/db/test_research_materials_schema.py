"""Additive 0028 migration, historical byte preservation and downgrade guards."""
from tests.helpers.legacy_plans import seed_legacy_plan
import json
import os
from pathlib import Path
import pytest
from sqlalchemy import inspect
from alembic import command
from app.db.database import database_connection,migration_connection,alembic_config,verify_runtime_permissions
from tests.api.test_analysis import client

NEW_TABLES=('external_evidence_versions','prepared_dataset_derivations_v3')


def config(db,migration):
    settings=alembic_config()
    settings.attributes.update(connection=db.raw_connection,database_config=migration)
    return settings


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
    _,word=repository.download(project,state['id'],request['report']['id'])
    with migration_connection(config=postgres_migration_config) as db:
        settings=config(db,postgres_migration_config)
        command.downgrade(settings,'0027_quality_derivations')
        inspector=inspect(db.raw_connection)
        names=[n for n in inspector.get_table_names() if n!='alembic_version']
        columns={n:[{**c,'type':str(c['type'])} for c in inspector.get_columns(n)] for n in names}
        rows={n:[dict(r) for r in db.execute('SELECT * FROM '+n)] for n in names}
        indexes={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        command.upgrade(settings,'head')
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
    with pytest.raises(RuntimeError,match='history|workflow state'):
        with migration_connection(config=postgres_migration_config) as db:
            command.downgrade(config(db,postgres_migration_config),'0027_quality_derivations')
    with database_connection() as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()['version_num']=='0029_statistics_execution'
