"""Incremental configuration/collection schema preserves the legacy artifact lane."""
from app.db.database import database_connection
import pytest


def seed_legacy_artifacts(db):
    from tests.db.test_task_schema import seed_owner
    seed_owner(db)
    db.execute("""INSERT INTO files(id,project_id,filename,file_type,size_bytes,sha256,uploaded_at,parse_status)
        VALUES ('f','p','synthetic.xlsx','xlsx',123,%s,'2026-10-15T00:00:00Z','parsed')""", ('a'*64,))
    db.execute("""INSERT INTO analysis_runs(id,file_id,setup_revision,engine_version,completed_at,result_json)
        VALUES ('r','f',1,'historical','2026-10-15T00:00:00Z',%s)""", ('{"original": "001 mg", "n": 5}',))
    db.execute("INSERT INTO figures(id,analysis_run_id,renderer_version,figure_json) VALUES ('g','r','renderer',%s)", ('{"id":"g", "title":"Figure 1", "sha256":"original"}',))
    db.execute("INSERT INTO explanations(id,analysis_run_id,figure_id,engine_version,explanation_json) VALUES ('e','r','g','explain',%s)", ('{"original":"preserve exact spaces"}',))
    db.execute("INSERT INTO reports(id,analysis_run_id,explanation_id,renderer_version,report_json,input_json) VALUES ('w','r','e','word',%s,%s)", ('{"original":"word"}', '{"frozen": true}'))


def test_figures_have_separate_legacy_and_configuration_identity(postgres_schema):
    with database_connection() as db:
        columns = {r['column_name']: r for r in db.execute(
            'SELECT column_name,is_nullable FROM information_schema.columns '
            "WHERE table_schema=%s AND table_name='figures'", (postgres_schema.schema,))}
        assert 'figure_config_version_id' in columns
        assert columns['figure_config_version_id']['is_nullable'] == 'YES'
        indexes = [r['indexdef'] for r in db.execute(
            "SELECT indexdef FROM pg_indexes WHERE schemaname=%s AND tablename='figures'",
            (postgres_schema.schema,))]
        assert any('UNIQUE' in definition and 'figure_config_version_id IS NULL' in definition for definition in indexes)
        assert any('UNIQUE' in definition and 'figure_config_version_id IS NOT NULL' in definition for definition in indexes)


def test_collection_storage_does_not_replace_legacy_report_table(postgres_schema):
    with database_connection() as db:
        names = {r['table_name'] for r in db.execute(
            'SELECT table_name FROM information_schema.tables WHERE table_schema=%s', (postgres_schema.schema,))}
        assert {'reports','report_collections','report_collection_versions','report_collection_items',
                'report_build_requests','collection_reports'}.issubset(names)
        legacy = db.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=%s "
                            "AND table_name='reports' ORDER BY ordinal_position", (postgres_schema.schema,)).fetchall()
        assert [r['column_name'] for r in legacy] == ['id','analysis_run_id','explanation_id','renderer_version','report_json','input_json']


def test_0026_keeps_every_original_value_and_only_replaces_whitelisted_index(postgres_migration_config):
    from alembic import command
    from app.db.database import migration_connection, alembic_config
    with migration_connection(config=postgres_migration_config) as db:
        config=alembic_config(); config.attributes.update(connection=db.raw_connection,database_config=postgres_migration_config)
        command.downgrade(config,'0025_correlation_planning')
        seed_legacy_artifacts(db)
        columns={r['table_name']: [] for r in db.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema() AND table_name<>'alembic_version'")}
        for row in db.execute('SELECT table_name,column_name FROM information_schema.columns WHERE table_schema=current_schema() ORDER BY ordinal_position'):
            if row['table_name'] in columns: columns[row['table_name']].append(row['column_name'])
        before={name:[dict(r) for r in db.execute('SELECT '+','.join('"'+c+'"' for c in names)+' FROM '+name)] for name,names in columns.items()}
        indexes={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        command.upgrade(config,'0026_figure_report_versions')
        after={name:[dict(r) for r in db.execute('SELECT '+','.join('"'+c+'"' for c in names)+' FROM '+name)] for name,names in columns.items()}
        assert after == before
        assert db.execute('SELECT figure_config_version_id FROM figures').fetchone()['figure_config_version_id'] is None
        newindexes={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        assert set(indexes)-set(newindexes)=={'figures_input_key'}
        assert all(newindexes[name]==value for name,value in indexes.items() if name!='figures_input_key')
        assert {'figures_legacy_input_key','figures_config_input_key'} <= set(newindexes)


def test_0026_refuses_downgrade_with_pending_new_task(postgres_migration_config):
    from alembic import command
    from sqlalchemy.exc import DBAPIError
    from app.db.database import migration_connection,alembic_config
    from tests.db.test_task_schema import seed_owner,insert_row,task_row
    with database_connection(write=True) as db:
        seed_owner(db); insert_row(db,'tasks',task_row(task_type='collection_word_report'))
    with pytest.raises(DBAPIError):
        with migration_connection(config=postgres_migration_config) as db:
            config=alembic_config(); config.attributes.update(connection=db.raw_connection,database_config=postgres_migration_config)
            command.downgrade(config,'0025_correlation_planning')
    with database_connection() as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()['version_num']=='0029_statistics_execution'
        assert db.execute('SELECT count(*) AS n FROM tasks').fetchone()['n']==1
