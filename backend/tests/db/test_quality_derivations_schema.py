from sqlalchemy import inspect
import pytest
from app.db.database import database_connection, verify_runtime_permissions
from app.db.schema import metadata
from tests.api.test_analysis import client

def test_additive_quality_table_and_runtime_permissions(postgres_schema):
    with database_connection() as db:
        inspector=inspect(db.raw_connection)
        assert 'prepared_dataset_derivations' in inspector.get_table_names()
        assert 'prepared_dataset_derivations' in metadata.tables
        assert len(inspector.get_foreign_keys('prepared_dataset_derivations'))==2
        assert any(f['referred_table']=='dataset_versions' for f in inspector.get_foreign_keys('prepared_dataset_versions'))
        verify_runtime_permissions(db.raw_connection,postgres_schema)
        import os,json
        from pathlib import Path
        if os.environ.get('BATCH07_SCHEMA_FIXTURE'):
            columns=[dict(r) for r in db.execute("""SELECT column_name,data_type,udt_name,is_nullable,column_default,ordinal_position
                FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='prepared_dataset_derivations' ORDER BY ordinal_position""")]
            indexes=[dict(r) for r in db.execute("""SELECT c.relname AS name,t.relname AS table_name,
                pg_get_indexdef(i.indexrelid) AS definition,i.indisvalid AS valid,i.indisready AS ready
                FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_class t ON t.oid=i.indrelid
                JOIN pg_namespace n ON n.oid=t.relnamespace
                WHERE n.nspname=current_schema() AND t.relname='prepared_dataset_derivations' ORDER BY c.relname""")]
            constraints=[dict(r) for r in db.execute("""SELECT t.relname AS table_name,c.conname,c.contype,c.convalidated,pg_get_constraintdef(c.oid) AS definition
                FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace
                WHERE n.nspname=current_schema() AND t.relname='prepared_dataset_derivations' ORDER BY c.conname""")]
            body=json.dumps(dict(revision='0027_quality_derivations',parent_revision='0026_figure_report_versions',
                table='prepared_dataset_derivations',columns=columns,indexes=indexes,constraints=constraints,
                new_indexes={r['name']:r for r in indexes},new_constraints=constraints),ensure_ascii=False,indent=2)
            Path(os.environ['BATCH07_SCHEMA_FIXTURE']).write_text(body.replace(postgres_schema.schema,'public'),encoding='utf-8')

def test_0027_preserves_all_legacy_rows_columns_indexes_and_prepared_json(client,postgres_migration_config):
    from alembic import command
    from tests.helpers.historical_migration import historical_workflow
    from tests.integration.test_batch07_quality_pipeline import published
    base,parent=published(client)
    before_bytes=client.get(parent['download_url']).content
    with historical_workflow(postgres_migration_config, '0026_figure_report_versions') as (db, settings):
        saved = db.execute('SELECT * FROM prepared_dataset_versions WHERE id=%s', (parent['id'],)).fetchone()
        from app.adapters.prepared_dataset_objects import PreparedDatasetObjects
        from app.core.config import get_data_dir
        objects = PreparedDatasetObjects(get_data_dir())
        assert objects.read(saved)[0] == before_bytes
        inspector=inspect(db.raw_connection)
        names=[n for n in inspector.get_table_names() if n!='alembic_version']
        columns={n:[{**c,'type':str(c['type'])} for c in inspector.get_columns(n)] for n in names}
        rows={n:[dict(r) for r in db.execute('SELECT * FROM '+n)] for n in names}
        indexes={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        command.upgrade(settings,'0027_quality_derivations')
        inspector=inspect(db.raw_connection)
        assert {n:[dict(r) for r in db.execute('SELECT * FROM '+n)] for n in names}==rows
        assert {n:[{**c,'type':str(c['type'])} for c in inspector.get_columns(n)] for n in names}==columns
        after={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        assert all(after[n]==value for n,value in indexes.items())
        migrated = db.execute('SELECT * FROM prepared_dataset_versions WHERE id=%s', (parent['id'],)).fetchone()
        assert objects.read(migrated)[0] == before_bytes
    assert client.get(parent['download_url']).content==before_bytes
    assert client.get(base+'/prepared-dataset-versions/'+parent['id']).json()==parent

@pytest.mark.initial_revision('0027_quality_derivations')
def test_0027_blocks_downgrade_for_pending_quality_task(postgres_migration_config):
    from alembic import command
    from app.db.database import migration_connection,alembic_config
    from tests.db.test_task_schema import insert_row, seed_owner, task_row
    with database_connection(write=True) as db:
        seed_owner(db)
        insert_row(db, 'tasks', task_row(task_type='prepare_dataset', workflow_version='dataset_preparation_v2'))
        pending = dict(db.execute('SELECT * FROM tasks').fetchone())
        assert db.execute('SELECT count(*) AS n FROM prepared_dataset_derivations').fetchone()['n'] == 0
    with pytest.raises(RuntimeError,match='quality history'):
        with migration_connection(config=postgres_migration_config) as db:
            settings=alembic_config(); settings.attributes.update(connection=db.raw_connection,database_config=postgres_migration_config)
            command.downgrade(settings,'0026_figure_report_versions')
    with database_connection() as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()['version_num']=='0027_quality_derivations'
        assert dict(db.execute('SELECT * FROM tasks').fetchone()) == pending
