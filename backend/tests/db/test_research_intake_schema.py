from app.db.schema import metadata
import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from app.db.database import database_connection, migration_connection, alembic_config
from alembic import command


def test_intake_and_bio_tables_are_registered():
    expected = {'research_intakes', 'research_deliveries', 'research_requirement_versions',
                'research_design_versions', 'research_material_refs', 'bio_datasets',
                'bio_imports', 'bio_import_files', 'bio_dataset_versions', 'bio_dataset_members'}
    assert expected <= set(metadata.tables)
    assert 'result_bio_dataset_version_id' in metadata.tables['tasks'].c
    assert 'profile' in metadata.tables['file_upload_batches'].c


def test_current_metadata_and_runtime_permissions_match_database():
    from app.maintenance.database_audit import audit_database
    from app.db.database import verify_runtime_permissions, get_database_config
    with database_connection() as db:
        result=audit_database(db)
        verify_runtime_permissions(db.raw_connection,get_database_config())
    assert not result['schema_issues'], result['schema_issues']


def test_legacy_backfill_preserves_values_and_creates_no_versions(postgres_migration_config):
    with migration_connection() as db:
        settings=alembic_config()
        settings.attributes.update(connection=db.raw_connection,database_config=postgres_migration_config)
        command.downgrade(settings,'0057_request_task_operation')
        db.execute("INSERT INTO projects(id,name,research_topic,project_type,created_at,updated_at) VALUES('old','原项目','主题','thesis','2026-10-01T00:00:00Z','2026-10-01T00:00:00Z')")
        before=dict(db.execute("SELECT * FROM projects WHERE id='old'").fetchone())
        command.upgrade(settings,'head')
        after=dict(db.execute("SELECT * FROM projects WHERE id='old'").fetchone())
        assert before==after
        root=db.execute("SELECT * FROM research_intakes WHERE project_id='old'").fetchone()
        assert root['owner_id'] is None and root['current_requirement_version_id'] is None
        delivery=db.execute("SELECT * FROM research_deliveries WHERE project_id='old'").fetchone()
        assert delivery['kind']=='thesis_draft' and delivery['origin']=='legacy_inferred'
        assert db.execute('SELECT count(*) AS n FROM research_requirement_versions').fetchone()['n']==0


def test_immutable_snapshot_and_scoped_material_constraints(tmp_path):
    from app.auth.service import create_user
    from app.adapters.storage import ProjectStore
    from app.domain.research_intake.contracts import RequirementWrite
    from app.domain.research_intake.service import write_version
    user=create_user('intake-db@example.invalid','isolated-password-2026')
    store=ProjectStore(tmp_path,owner_id=user['id'])
    first=store.create_project('one','topic','research',delivery_kinds=['analysis'],idempotency_key='one')
    second=store.create_project('two','topic','research',delivery_kinds=['analysis'],idempotency_key='two')
    saved=write_version(store,first['id'],'requirements',RequirementWrite.model_validate({'expected_revision':1,'operation':'save','content':{'schema_version':1,'services':['analysis']}}),'save-one')
    version_id=saved['version']['id']
    with pytest.raises(SQLAlchemyError):
        with migration_connection() as db:
            db.execute('UPDATE research_requirement_versions SET operation=%s WHERE id=%s',('confirm',version_id))
    with pytest.raises(IntegrityError):
        with database_connection(write=True) as db:
            db.execute('UPDATE research_intakes SET current_requirement_version_id=%s WHERE project_id=%s',(version_id,second['id']))
    with pytest.raises(IntegrityError):
        with database_connection(write=True) as db:
            db.execute('''INSERT INTO research_material_refs(id,project_id,requirement_version_id,availability,purpose)
                VALUES('bad',%s,%s,'provided','raw_data')''',(first['id'],version_id))
