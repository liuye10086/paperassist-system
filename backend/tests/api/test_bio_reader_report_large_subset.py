"""Twenty thousand legitimate selected cells remain local, outside model text."""
from tests.api.test_projects import client
from tests.api.test_reader_report_narratives import reader_policy
from tests.api.test_bio_reader_reports import service_for
from tests.api.test_bio_reader_report_annotation import freeze


def test_twenty_thousand_cell_subset_passes_real_r1_preview_without_barcode_lists(client, monkeypatch, tmp_path):
    from tests.helpers.bio_report_topics import published_trajectory
    from app.domain.bioinformatics.analysis_execution import run_bio_analysis_task
    from app.domain.reader_reports.content import make_material, canonical
    f = published_trajectory(client, monkeypatch, tmp_path, cell_count=20000, processed_only=True)
    created = client.post(f['base'] + '/bio-single-cell-subsets', json=dict(name='Large explicit subset',
        parent_processed_source=f['source'], cluster_ids=['0','1'], params=dict(min_spots=1)), headers={'Idempotency-Key': 'large-subset'})
    assert created.status_code == 202, created.text
    task = created.json()['task']
    done = run_bio_analysis_task(task['id'], task['revision'], engine=f['engine'], staging_directory=f['stage'])
    assert done['status'] == 'succeeded', done
    project = f['source']['project_id']; svc = service_for(project)
    view, _ = svc.prepare(project, dict(title='Large fixed subset', language='en', selection=dict(kind='processed',
        processed_version_id=done['result_bio_processed_dataset_version_id'], annotation_version_id=None, figure_version_ids=[])), 'large-context')
    preview = client.post(f['base'] + '/research-report-narratives/preview', json=view['report'])
    assert preview.status_code == 200, preview.text
    fixed, _, payload = freeze(svc, project, view)
    material = make_material(fixed, [dict(f, content=f['raw']) for f in payload['figures']])
    assert 'AACCTTGG00000000-1' not in canonical(material)
    assert material['facts']['sources'][0]['content']['summary']['subset']['selected_cell_count'] == 20000
    assert len(payload['figures']) == 1
    with svc.store.connection() as db:
        content = svc.require(db, 'bio_report_context_versions', project, view['id'])['content_json']
        assert len(content['subset']['resolved_cell_ids']) == 20000
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0
