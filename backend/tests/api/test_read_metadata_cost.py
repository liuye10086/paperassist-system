"""Navigation reads must not execute full lineage/deletion audits."""
from tests.api.test_projects import client  # noqa: F401


def test_file_details_do_not_run_full_retention_audit(client, monkeypatch):
    from tests.api.test_document_versions import uploaded_docx
    from app.domain.file_lifecycle import references

    project, _, _, item, content = uploaded_docx(client)
    # Another file's queued parse must not be counted for the selected file.
    from tests.api.test_file_batches import register
    base, batch, other, _ = register(client, project, content, 'other.docx', 'other-batch')
    uploaded = client.post(base+'/'+batch['id']+'/items/'+other['client_id'], files={'file':('other.docx', content)})
    assert uploaded.status_code == 202, uploaded.text

    def expensive_audit(*args, **kwargs):
        raise AssertionError('File metadata must not run deletion/source audits')

    monkeypatch.setattr(references, 'read_references', expensive_audit)
    response = client.get(f"/api/v1/projects/{project['id']}/files/{item['file_id']}/details")
    assert response.status_code == 200, response.text
    assert response.json()['references']['tasks'] == 1
    assert response.json()['references']['active_tasks'] == 1


def assert_display_counts_match_assessment(client, base):
    audited = client.get(base+'/lifecycle/assessment')
    assert audited.status_code == 200, audited.text
    details = client.get(base+'/details')
    assert details.status_code == 200, details.text
    for key in ('tasks', 'active_tasks', 'external_evidence_versions', 'prepared_dataset_derivations_v3'):
        assert details.json()['references'][key] == audited.json()['counts'][key], key


def test_display_counts_include_legacy_active_job(client):
    import json
    from app.db.database import database_connection
    from tests.api.test_projects import create_project, upload
    project = create_project(client)
    file = upload(client, project['id']).json()['file']
    base = f"/api/v1/projects/{project['id']}/files/{file['id']}"
    with database_connection(write=True) as db:
        # A historical metadata fixture; no numerical execution is claimed.
        db.execute('INSERT INTO analysis_runs(id,file_id,setup_revision,engine_version,completed_at,result_json) VALUES (%s,%s,1,%s,%s,%s)',
                   ('display-old-run', file['id'], 'legacy', '2026-10-10T00:00:00Z', '{}'))
        db.execute('INSERT INTO figure_jobs(id,analysis_run_id,renderer_version,created_at,job_json) VALUES (%s,%s,%s,%s,%s)',
                   ('display-old-job', 'display-old-run', 'legacy', '2026-10-10T00:00:00Z', json.dumps({'status':'uncertain'})))
    details = client.get(base+'/details')
    assert details.status_code == 200, details.text
    assert details.json()['references']['active_tasks'] == 1
    assert details.json()['references']['legacy_jobs'] == 1


def test_display_counts_preserve_bio_multifile_producers(client, monkeypatch, tmp_path):
    from tests.integration.test_research_lineage_phases import processed
    base, _ = processed(client, monkeypatch, tmp_path)
    files = client.get(base+'/files').json()
    for file in files:
        assert_display_counts_match_assessment(client, base+'/files/'+file['id'])


def test_report_list_reads_metadata_but_access_still_checks_original(client, tmp_path, monkeypatch):
    from tests.api.test_research_findings import selected_cell
    from app.domain.research_results.execution import run_research_task
    from app.adapters.research_report_render import render_report
    from app.domain.research_results.sources import ResearchSourceReader
    from app.adapters.research_objects import ResearchObjects
    from app.db.database import database_connection
    from app.core.config import get_data_dir
    from pathlib import Path

    base, source = selected_cell(client)
    finding = client.post(base+'/research-findings', json={'title':'Read costs','sources':[source]},
                          headers={'Idempotency-Key':'read-cost-finding'}).json()
    report = client.post(base+'/research-reports', json={'title':'Read costs','finding_version_id':finding['id']},
                         headers={'Idempotency-Key':'read-cost-report'}).json()
    done = run_research_task(report['task_id'], report['task']['revision'], task_type='research_report',
                            engine=render_report, staging_directory=tmp_path/'stage')
    assert done['status'] == 'succeeded'
    original_read = ResearchObjects.read

    def metadata_only(objects, record):
        assert record['object_key'].endswith('.json'), 'List read an export payload'
        return original_read(objects, record)

    def no_source_audit(*args, **kwargs):
        raise AssertionError('List traversed source bytes')

    with monkeypatch.context() as patch:
        patch.setattr(ResearchSourceReader, 'read_source', no_source_audit)
        patch.setattr(ResearchObjects, 'read', metadata_only)
        response = client.get(base+'/research-reports')
        assert response.status_code == 200, response.text
    saved = response.json()['items'][0]
    assert saved['id'] == report['id'] and saved['content']['title'] == 'Read costs'
    member = next(m for m in saved['members'] if m['role'] == 'docx')
    assert client.get(member['download_url']).status_code == 200
    with database_connection() as db:
        key = db.execute('SELECT object_key FROM files WHERE id=%s', (source['source_id'],)).fetchone()['object_key']
    path = Path(get_data_dir()) / key
    path.write_bytes(path.read_bytes()+b'changed')
    assert client.get(base+'/research-reports/'+report['id']).status_code == 409
    assert client.get(member['download_url']).status_code == 409


def test_file_counts_do_not_follow_manuscript_parent_after_sources_change(client):
    from tests.api.test_projects import upload
    from tests.api.test_manuscripts import setup, body
    from tests.api.test_literature_evidence import post

    path, file_path, file_a = setup(client)
    project = file_path.split('/')[4]
    uploaded = upload(client, project, filename='other.xlsx')
    assert uploaded.status_code == 201, uploaded.text
    file_b = uploaded.json()['file']

    def source(file):
        return dict(kind='original', id=file['id'], file_id=file['id'], role='methods')

    first = post(client, path, body(sources=[source(file_a)]), 'first')
    assert first.status_code == 201, first.text
    first = first.json()
    second = post(client, path + '/' + first['id'] + '/versions',
                  body(sources=[source(file_b)], expected_revision=1), 'second')
    assert second.status_code == 201, second.text
    assert second.json()['versions'][0]['parent_version_id'] == first['versions'][0]['id']

    for file in (file_a, file_b):
        details = client.get(f"/api/v1/projects/{project}/files/{file['id']}/details")
        assert details.status_code == 200, details.text
        refs = details.json()['references']
        assert refs['tasks'] == 1
        assert refs['active_tasks'] == 1


def test_display_counts_preserve_fixed_review_and_document_export_links(client):
    from tests.api.test_review_documents import completed_revision, create_document
    from app.domain.tasks.execution import run_task
    from app.db.database import database_connection

    url, revision = completed_revision(client)
    document = create_document(client, url, revision)
    response = client.post(url+'/documents/'+document['id']+'/exports', json={}, headers={'Idempotency-Key':'display-export'})
    assert response.status_code == 202, response.text
    assert run_task(response.json()['task_id'], 1)['status'] == 'succeeded'
    project = url.split('/')[4]
    with database_connection() as db:
        file_ids = [r['id'] for r in db.execute('SELECT id FROM files WHERE project_id=%s', (project,))]
    assert file_ids
    for file_id in file_ids:
        assert_display_counts_match_assessment(client, f'/api/v1/projects/{project}/files/{file_id}')
