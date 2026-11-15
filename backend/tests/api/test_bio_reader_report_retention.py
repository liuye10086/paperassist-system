"""Owner and delegated account deletion follows the actual context FK graph."""
import pytest

from tests.api.test_projects import client, create_project
from tests.api.test_bio_reader_reports import service_for


def test_context_only_protects_source_and_typed_bindings_reject_cross_project(client, monkeypatch, tmp_path):
    from tests.api.test_bio_insight_research_bridge import published
    from app.domain.bio_reader_reports.materials import prepare_material
    from app.domain.bio_reader_reports import BioReportPrepareRequest
    from app.adapters.research_results_store import base, identity, insert
    from app.domain.bioinformatics.contracts import digest
    from app.domain.file_lifecycle.research_results_references import read_groups
    from app.db.database import migration_connection
    project, result, _ = published(client, monkeypatch, tmp_path)
    svc = service_for(project)
    request = BioReportPrepareRequest(title='Standalone source protection', language='en',
        selection=dict(kind='insight', result_version_id=result['id'], figure_version_ids=[]))
    # Simulate a durable standalone context using the same checked material.
    # It has no finding/task; its own file edge must be sufficient protection.
    with svc.store.connection(write=True) as db:
        content = prepare_material(svc.assets, db, project, request)
        cid = identity(project, 'standalone', 'test')
        insert(db, 'bio_report_context_versions', base(cid, project, svc.store.user_id) | {'content_json': content, 'content_sha256': digest(content)})
        fid = content['source_file_ids'][0]
        file = dict(db.execute('SELECT * FROM files WHERE id=%s', (fid,)).fetchone())
        insert(db, 'bio_report_context_files', dict(id=identity(project, 'edge', 'test'), context_id=cid, file_id=fid,
            sha256=file['sha256'], project_id=project, user_id=svc.store.user_id))
    with svc.store.connection() as db:
        groups = read_groups(db, file, svc.store.user_id)
        assert [row['id'] for row in groups['bio_report_context_versions']] == [cid]
        assert groups['research_finding_versions'] == []
    response = client.get(f'/api/v1/projects/{project}/files/{fid}/lifecycle/assessment', params={'action': 'delete'})
    assert response.status_code == 200, response.text
    value = response.json()
    assert 'research_results_history_retained' in [reason['code'] for reason in value['reasons']]
    assert value['physical_deletion_available'] is False
    view, _ = svc.prepare(project, request, 'normal')
    foreign = create_project(client)['id']
    with migration_connection(write=True) as db:
        insert(db, 'bio_report_context_versions', base('foreign', foreign, svc.store.user_id) | {'content_json': {}, 'content_sha256': digest({})})
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError) as rejected:
        with migration_connection(write=True) as db:
            db.execute("INSERT INTO research_source_bindings(id,project_id,user_id,created_at,schema_version,parent_kind,finding_version_id,source_kind,source_id,bio_report_context_id,locator_json,source_sha256,role) VALUES('bad',%s,%s,now(),1,'finding',%s,'bio_report_context','foreign','foreign','{}',%s,'supporting')", (project, svc.store.user_id, view['report']['finding_version_id'], digest({})))
    assert rejected.value.orig.sqlstate == '23503'


def test_deleting_delegate_preserves_context_and_deleting_owner_erases_it(client, monkeypatch, tmp_path):
    from app.auth.service import create_user
    from app.domain.account_deletion import delete_account
    from app.db.database import database_connection
    from tests.api.test_bio_insight_research_bridge import published
    from tests.api.test_admin_operations import PASSWORD
    project, result, _ = published(client, monkeypatch, tmp_path)
    svc = service_for(project)
    view, _ = svc.prepare(project, dict(title='Retained owner content', language='en',
        selection=dict(kind='insight', result_version_id=result['id'], figure_version_ids=[])), 'retained')
    delegate = create_user('native-delegate@test.example', PASSWORD, 'analyst')
    operator = create_user('native-operator@test.example', PASSWORD, 'admin')
    # A real assignment makes this the delegated-account deletion path.
    # API/permission registration is Task 2; lifecycle deletion uses exact FKs.
    with database_connection(write=True) as db:
        db.execute("INSERT INTO project_assignments(project_id,owner_id,analyst_id,revision,updated_by,updated_at) VALUES(%s,%s,%s,1,%s,now())", (project, svc.store.user_id, delegate['id'], operator['id']))
    assert delete_account(operator['id'], delegate['id'], 1)['deleted']
    assert svc.get(project, view['id']) == view
    assert delete_account(operator['id'], svc.store.user_id, 1)['deleted']
    with database_connection() as db:
        for table in ('bio_report_context_versions', 'bio_report_context_files', 'bio_report_context_requests'):
            assert not db.execute('SELECT 1 FROM ' + table + ' WHERE project_id=%s', (project,)).fetchone()


def test_formal_audit_scans_prepare_only_context_and_detects_damaged_source(client, monkeypatch, tmp_path):
    from tests.api.test_bio_insight_research_bridge import published
    from app.maintenance.research_results_audit import audit_research_task_sources
    from pathlib import Path
    project, result, _ = published(client, monkeypatch, tmp_path)
    svc = service_for(project)
    view, _ = svc.prepare(project, dict(title='Prepared only', language='en', selection=dict(kind='insight',
        result_version_id=result['id'], figure_version_ids=[])), 'audit-only')
    with svc.store.connection() as db:
        checks = audit_research_task_sources(db, limit=1)
        context = next((c for c in checks if c['table'] == 'bio_report_context_versions'), None)
        assert context is not None
        assert context['rows'] == context['total'] == 1 and context['invalid'] == 0
        assert checks[0]['rows'] == 0
        file = db.execute('SELECT f.* FROM files f JOIN bio_report_context_files c ON c.file_id=f.id WHERE c.context_id=%s LIMIT 1', (view['id'],)).fetchone()
    path = Path(svc.assets.directory) / file['object_key']
    raw = path.read_bytes()
    try:
        path.write_bytes(raw + b'changed')
        with svc.store.connection() as db:
            context = next(c for c in audit_research_task_sources(db, limit=1) if c['table'] == 'bio_report_context_versions')
            assert context['invalid'] == 1
    finally:
        path.write_bytes(raw)
