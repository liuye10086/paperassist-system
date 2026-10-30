from app.db.database import database_connection
from app.maintenance.database_audit import audit_database
from tests.api.test_projects import client


def test_database_audit_aggregates_research_and_bio_checks():
    with database_connection() as db:
        result=audit_database(db)
    checks={(check['table'],check['column']) for check in result['data_checks']}
    assert ('research_intakes','owner_current_versions') in checks
    assert ('bio_imports','frozen_inputs_task_candidate') in checks
    assert ('bio_dataset_versions','manifest_members_task') in checks
    assert result['ok'],(result['schema_issues'],[c for c in result['data_checks'] if c['invalid']])


def test_research_hash_corruption_is_detected_without_leaking_content(client):
    from app.db.database import migration_connection
    from app.maintenance.research_intake_audit import audit_research_intakes
    from tests.api.test_research_intake import research
    project=research(client)
    response=client.post(f"/api/v1/projects/{project['id']}/requirements",headers={'Idempotency-Key':'audit-save'},json={
        'expected_revision':1,'operation':'save','content':{'schema_version':1,'services':['analysis'],'notes':'private notes'}})
    assert response.status_code==201,response.text
    with database_connection() as db:
        assert not any(check['invalid'] for check in audit_research_intakes(db))
    with migration_connection() as db:
        db.execute('ALTER TABLE research_requirement_versions DISABLE TRIGGER research_snapshot_seal')
        db.execute('UPDATE research_requirement_versions SET sha256=%s',('b'*64,))
        db.execute('ALTER TABLE research_requirement_versions ENABLE TRIGGER research_snapshot_seal')
    with database_connection() as db:
        checks=audit_research_intakes(db)
    assert sum(check['invalid'] for check in checks)==1
    assert 'private notes' not in str(checks)


def test_published_bio_audit_and_file_lifecycle_detect_corrupt_members(client):
    from tests.integration.test_bio_import_publication import create_import,run,read,confirm
    from app.maintenance.bio_dataset_audit import audit_bio_datasets
    from app.core.config import get_data_dir
    from app.adapters.bio_objects import BioObjects
    from app.domain.file_lifecycle.references import read_references
    base,created,file_id,_=create_import(client)
    waiting=run(created['task'])
    assert waiting['status']=='waiting_confirmation',waiting
    view=read(client,base,created)
    queued=confirm(client,base,created,view)
    assert queued.status_code==202,queued.text
    done=run(queued.json())
    assert done['status']=='succeeded',done
    with database_connection() as db:
        checks=audit_bio_datasets(db)
        assert not any(check['invalid'] for check in checks),checks
        file=dict(db.execute('SELECT * FROM files WHERE id=%s',(file_id,)).fetchone())
        user=db.execute('SELECT owner_id FROM projects WHERE id=%s',(file['project_id'],)).fetchone()['owner_id']
        refs=read_references(db,file,user)
        assert refs['counts']['bio_dataset_versions']==1
        assert refs['counts']['bio_imports']==1
        assert 'bio_history_retained' in refs['reasons']
        assert 'integrity_unknown' not in refs['reasons'],refs['reasons']
        member=db.execute('SELECT o.* FROM bio_dataset_members m JOIN storage_objects o ON o.id=m.object_id LIMIT 1').fetchone()
    path=BioObjects(get_data_dir()).path(member['object_key'])
    path.write_bytes(b'x'*member['size_bytes'])
    with database_connection() as db:
        checks=audit_bio_datasets(db)
    assert any(check['invalid'] for check in checks)
