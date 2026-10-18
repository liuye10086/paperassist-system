def test_ocr_review_tables_and_type_constraints(postgres_schema):
    from app.db.database import database_connection
    with database_connection() as db:
        names = {r['table_name'] for r in db.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()")}
        assert {'ocr_review_decisions','ocr_review_versions'} <= names
        constraints = db.execute("SELECT pg_get_constraintdef(oid) AS definition FROM pg_constraint WHERE conname IN ('tasks_type_check','task_waits_kind_check') AND connamespace=(SELECT oid FROM pg_namespace WHERE nspname=current_schema())").fetchall()
        assert any('review_ocr' in r['definition'] for r in constraints)
        assert any('ocr_review_confirmation' in r['definition'] for r in constraints)


def test_0021_preserves_prior_rows_and_asset_references(postgres_schema,postgres_migration_config):
    from alembic import command
    from app.db.database import migration_connection,database_connection,alembic_config,verify_runtime_permissions
    from tests.db.test_task_schema import seed_owner,task_row,insert_row
    with migration_connection(config=postgres_migration_config) as db:
        config=alembic_config()
        config.attributes.update(connection=db.raw_connection,database_config=postgres_migration_config)
        command.downgrade(config,'0020_ocr_parsing')
        seed_owner(db)
        insert_row(db,'tasks',task_row(input_snapshot={'schema_version':1,'result':{'original':['001 mg',None]}}))
        old_tables=[r['table_name'] for r in db.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema() AND table_name<>'alembic_version'")]
        original={name:[dict(r) for r in db.execute('SELECT * FROM '+name)] for name in old_tables}
        command.upgrade(config,'head')
        upgraded={name:[dict(r) for r in db.execute('SELECT * FROM '+name)] for name in old_tables}
        # 0025 adds nullable diagnostic evidence; every pre-existing value stays identical.
        for row in upgraded['tasks']:
            assert row.pop('verification_failure') is None
        for row in upgraded['figures']:
            assert row.pop('figure_config_version_id') is None
        assert upgraded==original
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()['version_num']=='0029_statistics_execution'
    with database_connection() as db:
        verify_runtime_permissions(db.raw_connection,postgres_schema)
