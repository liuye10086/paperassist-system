"""0038→0039 uses only the fixture's random TEST schema."""
import pytest
from alembic import command
from sqlalchemy.exc import SQLAlchemyError
from tests.api.test_analysis import client  # noqa:F401
from tests.api.test_layout_exports import prepared, layout_renderer, fake_renderer  # noqa:F401
from tests.maintenance.test_literature_evidence_migration import fingerprints
from app.db.database import alembic_config,get_migration_database_config,migration_connection,database_connection


def test_layout_migration_preserves_old_values_columns_indexes_and_constraints(client,monkeypatch):
    from types import SimpleNamespace
    from app.domain.tasks.execution import run_task
    path,source,_=prepared(client)
    pdf_path=path.replace('/layout-exports','/pdf-exports')
    old=client.post(pdf_path,json=dict(source_kind='manuscript_export',source_id=source['id'],request_key='old-pdf')).json()
    monkeypatch.setattr('app.domain.pdf_exports.execution.render_pdf',lambda raw:SimpleNamespace(content=b'%PDF-preserved-before-0039',manifest={'contract':'test-v1'}))
    assert run_task(old['task_id'],1)['status']=='succeeded'
    before_pdf=client.get(pdf_path+'/'+old['id']+'/download').content
    cfg=alembic_config()
    with migration_connection(write=True) as db:
        assert db.config.schema.startswith('pa_test_')
        assert db.execute('SELECT current_database() AS name').fetchone()['name']=='paperassist_system_test'
        cfg.attributes.update(connection=db.raw_connection,database_config=get_migration_database_config())
        command.downgrade(cfg,'0038_manuscript_review')
        tables=[r['tablename'] for r in db.execute('SELECT tablename FROM pg_tables WHERE schemaname=current_schema()') if r['tablename']!='alembic_version']
        before=fingerprints(db,tables)
        indexes={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        constraints={r['conname']:r['definition'] for r in db.execute("SELECT conname,pg_get_constraintdef(oid) AS definition FROM pg_constraint WHERE connamespace=current_schema()::regnamespace")}
        columns=list(db.execute("SELECT table_name,column_name,data_type,is_nullable FROM information_schema.columns WHERE table_schema=current_schema() ORDER BY table_name,ordinal_position"))
        command.upgrade(cfg,'0039_layout_exports')
        # Compare exactly the old columns, including nonempty old rows.
        quote=db.raw_connection.dialect.identifier_preparer.quote
        for table in tables:
            fields=[quote(c['column_name']) for c in columns if c['table_name']==table]
            old_rows=sorted(r['value'] for r in db.execute('SELECT to_jsonb(x)::text AS value FROM (SELECT '+','.join(fields)+' FROM '+quote(table)+') x'))
            import hashlib
            assert (len(old_rows),hashlib.sha256('\n'.join(old_rows).encode()).hexdigest())==before[table]
        after={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        assert all(after.get(k)==v for k,v in indexes.items())
        after_constraints={r['conname']:r['definition'] for r in db.execute("SELECT conname,pg_get_constraintdef(oid) AS definition FROM pg_constraint WHERE connamespace=current_schema()::regnamespace")}
        assert all(after_constraints.get(k)==v for k,v in constraints.items() if k not in ('tasks_type_check','pdf_typed_source_check'))
        after_columns=list(db.execute("SELECT table_name,column_name,data_type,is_nullable FROM information_schema.columns WHERE table_schema=current_schema() ORDER BY table_name,ordinal_position"))
        assert all(c in after_columns for c in columns)
    from app.maintenance.database_audit import audit_database
    with database_connection() as db:
        audit=audit_database(db)
    assert audit['ok'],audit['schema_issues']
    assert client.get(pdf_path+'/'+old['id']+'/download').content==before_pdf


def test_layout_typed_scope_snapshot_and_downgrade_guards(client):
    path,_,request=prepared(client)
    saved=client.post(path,json=request).json()
    clauses=[
        "source_kind='report'",
        "manuscript_export_id='missing',source_id='missing'",
        "parent_export_id='missing'",
        "layout_version='future'",
        "input_json=input_json-'layout'",
        "input_json=jsonb_set(input_json,'{layout}','{}')",
        "input_json=jsonb_set(input_json,'{output_language}','null')",
        "metadata_json='{}'",
    ]
    for clause in clauses:
        with pytest.raises(SQLAlchemyError):
            with database_connection(write=True) as db:
                db.execute('UPDATE layout_exports SET '+clause+' WHERE id=%s',(saved['id'],))
    cfg=alembic_config()
    with pytest.raises(RuntimeError,match='refusing destructive downgrade'):
        with migration_connection(write=True) as db:
            cfg.attributes.update(connection=db.raw_connection,database_config=get_migration_database_config())
            command.downgrade(cfg,'0038_manuscript_review')
