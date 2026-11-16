"""The R1 governed task consumes the native context, with synthetic model output only."""
import io
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from zipfile import ZipFile

import pytest

from tests.api.test_projects import client
from tests.api.test_bio_reader_reports import service_for
from tests.api.test_bio_reader_report_annotation import parent_result, native_figure, freeze
from tests.api.test_reader_report_narratives import reader_policy, authorize_user_and_project, worker


@pytest.mark.parametrize('versioned', [False, True], ids=['new-report', 'exact-version-request'])
def test_native_context_shares_real_r1_binding_exports_and_offline_rebuild(client, parent_result, monkeypatch, tmp_path, versioned):
    from app.adapters.research_report_render import render_report
    from app.domain.research_results.execution import run_research_report_task
    from app.domain.research_results.reports import ResearchReportService
    from tests.helpers.research_report import sample_reader_record
    from tests.api.test_school_rule_suggestions import Fixture
    f = parent_result
    project = f['source']['project_id']
    svc = service_for(project)
    figure, png = native_figure(client, f, monkeypatch, 'export-image', 'navy')
    request = dict(title='Selected cells', language='en', selection=dict(kind='processed',
        processed_version_id=f['source']['processed_dataset_version_id'], annotation_version_id=None, figure_version_ids=[figure]))
    view, _ = svc.prepare(project, request, 'prepare-export')
    snapshot, _, payload = freeze(svc, project, view)
    report_request = view['report'] | {'title': 'Customized single-cell report'}
    report_url = f['base'] + '/research-reports'
    if versioned:
        from app.adapters.task_execution_store import TaskExecutionStore
        from app.domain.reader_reports.service import ReaderReportService

        with monkeypatch.context() as patch:
            patch.setattr(ReaderReportService, 'record_for', lambda *args: sample_reader_record(args[-1]))
            parent = client.post(report_url, json=view['report'] | {'reader_narrative_id': 'prior-narrative'},
                                 headers={'Idempotency-Key': 'prior-report'})
        assert parent.status_code == 201, parent.text
        parent = parent.json()
        repo = TaskExecutionStore()
        lease = repo.claim(parent['task_id'], parent['task']['revision'], task_type='research_report')
        repo.fail(lease, 'research_source_conflict')
        report_request.update(root_id=parent['root_id'], expected_revision=parent['revision'])
        report_url += f"/{parent['root_id']}/versions"
    endpoint = f['base'] + '/research-report-narratives'
    preview = client.post(endpoint + '/preview', json=report_request)
    assert preview.status_code == 200, preview.text
    assert preview.json()['figures'][0]['number'] == 1
    response = client.post(endpoint, json=dict(report=report_request, bundle_sha256=preview.json()['bundle_sha256'],
        confirmed_external_processing=True), headers={'Idempotency-Key': 'native-narrative'})
    assert response.status_code == 202, response.text
    queued = response.json()
    workspace = client.get('/api/v1/tasks/' + queued['task']['id'] + '/workspace')
    assert workspace.status_code == 200, workspace.text
    assert workspace.json()['artifacts']['bio_reader_report_context_id'] == view['id']
    assert workspace.json()['artifacts']['bio_reader_report_request'] == report_request
    assert workspace.json()['task']['input_version'] == queued['task']['input_version']
    authorize_user_and_project(queued)
    sample = sample_reader_record(snapshot)
    provider = Fixture(dict(narrative=sample['narrative'], figures=[{k: v for k, v in figure.items() if k != 'caption'} for figure in sample['figures']]))
    done = worker(queued, provider)
    assert done['status'] == 'succeeded', done
    completed_workspace = client.get('/api/v1/tasks/' + queued['task']['id'] + '/workspace')
    assert completed_workspace.status_code == 200, completed_workspace.text
    assert completed_workspace.json()['artifacts']['bio_reader_report_context_id'] == view['id']
    recovered = completed_workspace.json()['artifacts']['bio_reader_report_request']
    assert len(provider.posts) == 1
    stale = client.post(report_url, json=report_request | {'title': view['title'], 'reader_narrative_id': queued['id']},
                        headers={'Idempotency-Key': 'default-title-does-not-match'})
    assert stale.status_code == 409, stale.text
    from app.core.exceptions import StorageError
    from app.domain.bio_reader_reports import exports

    monkeypatch.setattr(exports, 'PAGE_SIZE', 1)
    report_body = recovered | {'reader_narrative_id': queued['id']}
    catalog_url = f"{f['base']}/bio-reader-reports/{view['id']}/reports"

    def fail_render(_payload, _output):
        raise StorageError('research_source_conflict', 'Controlled source conflict', 422)

    failed_response = client.post(report_url, json=report_body, headers={'Idempotency-Key': 'native-report-failed'})
    assert failed_response.status_code == 201, failed_response.text
    failed = failed_response.json()
    failed_task = run_research_report_task(failed['task_id'], failed['task']['revision'], engine=fail_render,
                                           staging_directory=tmp_path / 'report')
    assert failed_task['status'] == 'failed', failed_task
    failed_workspace = client.get('/api/v1/tasks/' + failed['task_id'] + '/workspace').json()
    assert 'retry' not in failed_workspace['allowed_actions']
    failed_catalog = client.get(catalog_url).json()
    assert failed_catalog['export_state'] == 'available'
    assert [(item['id'], item['task']['status']) for item in failed_catalog['items']] == [(failed['id'], 'failed')]
    replay = client.post(report_url, json=report_body, headers={'Idempotency-Key': 'native-report-failed'})
    assert replay.status_code == 200 and replay.json()['id'] == failed['id'], replay.text

    def submit(key):
        return client.post(report_url, json=report_body, headers={'Idempotency-Key': key})

    with ThreadPoolExecutor(max_workers=2) as pool:
        submissions = list(pool.map(submit, ('native-report', 'native-report-duplicate')))
    assert sorted(item.status_code for item in submissions) == [200, 201], [item.text for item in submissions]
    created = next(item.json() for item in submissions if item.status_code == 201)
    assert created['id'] != failed['id']
    assert {item.json()['id'] for item in submissions} == {created['id']}
    if versioned:
        assert created['parent_id'] == failed['id'] and created['revision'] == failed['revision'] + 1
        stale = client.post(report_url, json=report_body | {'title': 'Another change'},
                            headers={'Idempotency-Key': 'stale-unrelated-request'})
        assert stale.status_code == 409 and stale.json()['detail']['code'] == 'research_revision_conflict', stale.text
    total = 3 if versioned else 2
    historical = client.get(catalog_url, params={'page': 2}).json()
    assert historical['export_state'] == 'active' and historical['total'] == total
    assert [item['id'] for item in historical['items']] == [failed['id']]
    done = run_research_report_task(created['task_id'], created['task']['revision'], engine=render_report, staging_directory=tmp_path / 'report')
    assert done['status'] == 'succeeded', done
    historical = client.get(catalog_url, params={'page': 2}).json()
    assert historical['export_state'] == 'completed' and historical['total'] == total
    assert [item['id'] for item in historical['items']] == [failed['id']]
    duplicate = submit('native-report-completed')
    assert duplicate.status_code == 200 and duplicate.json()['id'] == created['id'], duplicate.text
    saved = ResearchReportService(svc.assets).get(project, created['id'])
    assert saved['content']['title'] == report_request['title']
    assert saved['content']['reader_report']['provenance']['narrative_id'] == queued['id']
    wrapped = client.post(f['base'] + '/research-findings', json=dict(title='Wrapped native report', sources=[
        dict(source_kind='research_report_version', source_id=created['id'])]), headers={'Idempotency-Key': 'wrapped'})
    assert wrapped.status_code == 201, wrapped.text
    rejected = client.post(endpoint + '/preview', json=dict(title='Wrapped selection', language='en',
        finding_version_id=wrapped.json()['id'], figure_version_ids=[]))
    assert rejected.status_code == 422, rejected.text
    from app.domain.research_results.source_changes import dependency_impact
    with svc.store.connection() as db:
        affected = dependency_impact(db, project, svc.store.user_id, 'original_file', f['source']['raw_source']['source_file_ids'][0])['affected']
        assert {('bio_report_context', view['id']), ('research_finding_version', view['report']['finding_version_id']),
                ('research_report_version', created['id'])} <= {(r['source_kind'], r['source_id']) for r in affected}
    files = {m['role']: ResearchReportService(svc.assets).member(project, created['id'], m['id'])[1] for m in saved['members']}
    with ZipFile(io.BytesIO(files['zip'])) as archive:
        assert archive.read('analysis.docx') == files['docx']
        assert archive.read('results.xlsx') == files['xlsx']
        assert archive.read('figures/figure_01/selected_png.png') == png
        offline = tmp_path / 'offline'
        archive.extractall(offline)
    run = subprocess.run([sys.executable, str(offline / 'rebuild_report.py')], cwd=offline, capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stdout + run.stderr
    assert (offline / 'rebuilt' / 'analysis.docx').is_file()
    from app.adapters import research_report_render
    monkeypatch.setattr(research_report_render, 'renderer_identity', lambda: {'future_renderer': True})
    assert ResearchReportService(svc.assets).get(project, created['id'])['sha256'] == saved['sha256']
    for member in saved['members']:
        assert ResearchReportService(svc.assets).member(project, created['id'], member['id'])[1] == files[member['role']]
    assert len(provider.posts) == 1


def test_native_context_language_cannot_be_replaced_at_standard_r1_preview(client, parent_result):
    f = parent_result
    service = service_for(f['source']['project_id'])
    view, _ = service.prepare(f['source']['project_id'], dict(title='English selection', language='en', selection=dict(
        kind='processed', processed_version_id=f['source']['processed_dataset_version_id'], annotation_version_id=None,
        figure_version_ids=[])), 'fixed-language')
    catalog = client.get(f"{f['base']}/bio-reader-reports/{view['id']}/reports")
    assert catalog.status_code == 200, catalog.text
    assert catalog.json()['export_state'] == 'available'
    endpoint = f['base'] + '/research-report-narratives/preview'
    assert client.post(endpoint, json=view['report']).status_code == 200
    rejected = client.post(endpoint, json=view['report'] | {'language': 'zh-CN'})
    assert rejected.status_code == 422, rejected.text
