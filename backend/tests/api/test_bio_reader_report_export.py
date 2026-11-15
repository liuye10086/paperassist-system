"""The R1 governed task consumes the native context, with synthetic model output only."""
import io
import subprocess
import sys
from zipfile import ZipFile

from tests.api.test_projects import client
from tests.api.test_bio_reader_reports import service_for
from tests.api.test_bio_reader_report_annotation import parent_result, native_figure, freeze
from tests.api.test_reader_report_narratives import reader_policy, authorize_user_and_project, worker


def test_native_context_shares_real_r1_binding_exports_and_offline_rebuild(client, parent_result, monkeypatch, tmp_path):
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
    endpoint = f['base'] + '/research-report-narratives'
    preview = client.post(endpoint + '/preview', json=view['report'])
    assert preview.status_code == 200, preview.text
    assert preview.json()['figures'][0]['number'] == 1
    response = client.post(endpoint, json=dict(report=view['report'], bundle_sha256=preview.json()['bundle_sha256'],
        confirmed_external_processing=True), headers={'Idempotency-Key': 'native-narrative'})
    assert response.status_code == 202, response.text
    queued = response.json()
    workspace = client.get('/api/v1/tasks/' + queued['task']['id'] + '/workspace')
    assert workspace.status_code == 200, workspace.text
    assert workspace.json()['artifacts']['bio_reader_report_context_id'] == view['id']
    assert workspace.json()['task']['input_version'] == queued['task']['input_version']
    authorize_user_and_project(queued)
    sample = sample_reader_record(snapshot)
    provider = Fixture(dict(narrative=sample['narrative'], figures=[{k: v for k, v in figure.items() if k != 'caption'} for figure in sample['figures']]))
    done = worker(queued, provider)
    assert done['status'] == 'succeeded', done
    completed_workspace = client.get('/api/v1/tasks/' + queued['task']['id'] + '/workspace')
    assert completed_workspace.status_code == 200, completed_workspace.text
    assert completed_workspace.json()['artifacts']['bio_reader_report_context_id'] == view['id']
    assert len(provider.posts) == 1
    report = client.post(f['base'] + '/research-reports', json=view['report'] | {'reader_narrative_id': queued['id']},
                        headers={'Idempotency-Key': 'native-report'})
    assert report.status_code == 201, report.text
    created = report.json()
    done = run_research_report_task(created['task_id'], created['task']['revision'], engine=render_report, staging_directory=tmp_path / 'report')
    assert done['status'] == 'succeeded', done
    saved = ResearchReportService(svc.assets).get(project, created['id'])
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
    endpoint = f['base'] + '/research-report-narratives/preview'
    assert client.post(endpoint, json=view['report']).status_code == 200
    rejected = client.post(endpoint, json=view['report'] | {'language': 'zh-CN'})
    assert rejected.status_code == 422, rejected.text
