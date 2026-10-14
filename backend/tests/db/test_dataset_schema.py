"""0016 preserves all old columns, JSON and indexes in a UUID test schema."""
import json
from alembic import command
from sqlalchemy import inspect
from app.db.database import alembic_config, migration_connection
from app.maintenance.database_audit import audit_database
from tests.db.test_task_schema import seed_owner, task_row, insert_row


def assert_preserved_indexes(inspector,name,old_indexes):
    expected_indexes=list(old_indexes)
    if name=='file_upload_batches':
        # 0023 adds exactly this frozen definition; historical indexes remain intact.
        expected_indexes.append({
            'name':'file_upload_batches_owner_created','unique':False,
            'column_names':['project_id','user_id','created_at','id'],
            'column_sorting':{'created_at':('desc',)},
            'dialect_options':{'postgresql_include':[]},
        })
    assert sorted(inspector.get_indexes(name),key=lambda index:index['name']) == sorted(
        expected_indexes,key=lambda index:index['name'])


def test_0016_preserves_old_tables_columns_json_and_indexes(postgres_schema,postgres_migration_config):
    with migration_connection(config=postgres_migration_config) as db:
        settings=alembic_config()
        settings.attributes.update(connection=db.raw_connection,database_config=postgres_migration_config)
        command.downgrade(settings,'0015_file_parsing')
        seed_owner(db)
        db.execute('''INSERT INTO files(id,project_id,filename,file_type,size_bytes,sha256,uploaded_at,
            parse_status,error_json,preview_json,uploader_id,object_key,metadata_revision,parse_revision)
            VALUES ('old','p','same.xlsx','xlsx',3,%s,'2026-10-08T00:00:00Z','parsed',NULL,%s,'u',NULL,4,7)''',
            ('a'*64,json.dumps({'preserved':['old',1,None]})))
        insert_row(db,'tasks',task_row(input_snapshot={'schema_version':1,'result':{'old':[None,1]}}))
        inspector=inspect(db.raw_connection)
        tables=[name for name in inspector.get_table_names() if name!='alembic_version']
        rows={name:[dict(row) for row in db.execute('SELECT * FROM '+name)] for name in tables}
        def normalized_columns(name):
            return [{**column,'type':str(column['type'].compile(dialect=db.raw_connection.dialect))}
                    for column in inspector.get_columns(name)]
        columns={name:normalized_columns(name) for name in tables}
        indexes={name:inspector.get_indexes(name) for name in tables}
        command.upgrade(settings,'head')
        inspector=inspect(db.raw_connection)
        for name in tables:
            assert [dict(row) for row in db.execute('SELECT * FROM '+name)]==rows[name]
            assert normalized_columns(name)==columns[name]
            assert_preserved_indexes(inspector,name,indexes[name])
        assert db.execute('SELECT count(*) AS n FROM file_structure_versions').fetchone()['n']==0
        assert db.execute('SELECT count(*) AS n FROM dataset_versions').fetchone()['n']==0
        result=audit_database(db)
        assert result['ok'],result['schema_issues']
