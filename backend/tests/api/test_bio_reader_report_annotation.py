"""Synthetic single-cell artifacts exercise real annotation, ownership and frozen bytes."""
import hashlib
import io

import pytest
from PIL import Image

from tests.api.test_projects import client, create_project
from tests.api.test_single_cell_batch4_flow import parent_result
from tests.api.test_bio_reader_reports import service_for


def labels(client, fixture, key='labels'):
    parent = fixture['source']
    body = dict(name='Reviewed labels', raw_source=parent['raw_source'],
                processed_dataset_version_id=parent['processed_dataset_version_id'], expected_revision=0,
                labels=[dict(id='T', name='T candidate', status='uncertain', cluster_ids=['0'])],
                evidence=[dict(label_id='T', kind='manual', note='Saved marker review; requires validation')])
    result = client.post(fixture['base'] + '/bio-annotation-sets', json=body, headers={'Idempotency-Key': key})
    assert result.status_code == 201, result.text
    return body, result.json()


def native_figure(client, fixture, monkeypatch, key, color, annotation=None):
    from app.domain.bioinformatics import analysis_execution
    from app.domain.tasks.execution import run_task
    body = dict(processed_source=fixture['source'], annotation_version_id=annotation,
                config=dict(kind='annotation' if annotation else 'umap'))
    response = client.post(fixture['base'] + '/bio-figures', json=body, headers={'Idempotency-Key': key})
    assert response.status_code == 202, response.text
    stream = io.BytesIO()
    Image.new('RGB', (32, 20), color).save(stream, format='PNG')
    png = stream.getvalue()
    def engine(payload, out, mode, **kwargs):
        path = out / 'selected.png'
        path.write_bytes(png)
        return dict(outputs=[dict(key='selected_png', role='figure', format='png', path=str(path.resolve()),
                    size_bytes=len(png), sha256=hashlib.sha256(png).hexdigest())],
                    manifest=dict(config=payload['config']), summary={}, steps=[], checks={})
    monkeypatch.setattr(analysis_execution, 'execute_bio_analysis', engine)
    task = response.json()['task']
    assert run_task(task['id'], task['revision'])['status'] == 'succeeded'
    return response.json()['id'], png


def freeze(service, project, view):
    from app.domain.research_results.contracts import ResearchReportRequest
    from app.domain.research_results.reports import ResearchReportService
    with service.store.connection() as db:
        return ResearchReportService(service.assets).freeze(db, project, ResearchReportRequest(**view['report']))


def test_annotation_and_order_stay_fixed_after_new_labels_and_later_figures(client, parent_result, monkeypatch):
    from app.core.exceptions import StorageError
    from app.domain.reader_reports.content import make_material
    f = parent_result
    project = f['source']['project_id']
    svc = service_for(project)
    annotation_body, old = labels(client, f)
    one, first_png = native_figure(client, f, monkeypatch, 'red', 'red', old['id'])
    two, second_png = native_figure(client, f, monkeypatch, 'blue', 'blue', old['id'])
    body = dict(title='Cell annotation', language='en', selection=dict(kind='processed',
                processed_version_id=f['source']['processed_dataset_version_id'], annotation_version_id=old['id'], figure_version_ids=[two, one]))
    view, _ = svc.prepare(project, body, 'selected-order')
    before, _, payload = freeze(svc, project, view)
    assert [image['raw'] for image in payload['figures']] == [second_png, first_png]
    assert [image['native_source']['source_id'] for image in before['figures']] == [two, one]
    assert 'annotation_assignments' in [table['key'] for table in before['tables']]
    material = make_material(before, [dict(image, content=image['raw']) for image in payload['figures']])
    annotation = material['facts']['sources'][0]['content']['summary']['annotation']
    assert annotation['assignment_counts'] == [dict(label_id='T', status='uncertain', count=1)]
    assert annotation['evidence'][0]['note'].startswith('Saved marker review')
    changed = client.post(f['base'] + f"/bio-annotation-sets/{old['set_id']}/versions",
        json=annotation_body | {'expected_revision': 1, 'labels': [dict(id='T', name='New name', status='confirmed', cell_ids=['c1'])]},
        headers={'Idempotency-Key': 'new-labels'})
    assert changed.status_code == 201, changed.text
    native_figure(client, f, monkeypatch, 'latest-green', 'green', changed.json()['id'])
    assert svc.get(project, view['id']) == view
    assert svc.prepare(project, body, 'same-old-choice') == (view, 200)
    after, _, latest_payload = freeze(svc, project, view)
    assert before == after and [x['raw'] for x in latest_payload['figures']] == [second_png, first_png]
    # Historical report validation may inspect exact old labels. Normal new
    # analysis validation must continue to reject those stale labels.
    from app.domain.bio_insights.sources import InsightSourceReader
    from app.domain.bioinformatics.contracts import digest
    with svc.store.connection() as db:
        row = db.execute('SELECT geometry_sha256,assignments_sha256 FROM bio_annotation_versions WHERE id=%s', (old['id'],)).fetchone()
        selected = dict(source_kind='bio_annotation_version', source_id=old['id'], sha256=digest(dict(row)))
        with pytest.raises(StorageError):
            InsightSourceReader(svc.assets).resolve(db, project, selected)
        reader = InsightSourceReader(svc.assets, allow_stale_labels=True)
        assert reader.resolve(db, project, selected)['sha256'] == selected['sha256']
    with pytest.raises(StorageError):
        svc.prepare(project, body | {'selection': body['selection'] | {'annotation_version_id': changed.json()['id']}}, 'wrong-label-figure')
    with pytest.raises(StorageError):
        svc.prepare(create_project(client)['id'], body, 'foreign')


def test_native_original_mode_never_picks_latest_replot(client, parent_result, monkeypatch):
    from app.domain.research_results.findings import ResearchFindingService
    from app.domain.research_results.contracts import FindingVersionRequest
    from app.core.exceptions import StorageError
    f = parent_result
    project = f['source']['project_id']
    svc = service_for(project)
    body = dict(title='Original cells', language='zh-CN', selection=dict(kind='processed',
        processed_version_id=f['source']['processed_dataset_version_id'], annotation_version_id=None, figure_version_ids=[]))
    view, _ = svc.prepare(project, body, 'originals')
    before, _, payload = freeze(svc, project, view)
    later, _ = native_figure(client, f, monkeypatch, 'later', 'green')
    assert freeze(svc, project, view)[0] == before
    assert all(f['native_source']['source_kind'] == 'bio_analysis_artifact' for f in before['figures'])
    mixed, _ = ResearchFindingService(svc.assets).create(project, FindingVersionRequest(title='Mixed', sources=[
        dict(source_kind='bio_report_context', source_id=view['id']),
        dict(source_kind='bio_processed_dataset_version', source_id=f['source']['processed_dataset_version_id'])]), 'mixed')
    with pytest.raises(StorageError):
        freeze(svc, project, view | {'report': view['report'] | {'finding_version_id': mixed['id']}})


def test_subset_context_preserves_parent_selection_and_only_subset_tables(client, parent_result, monkeypatch):
    from app.domain.bioinformatics import analysis_execution
    from app.domain.tasks.execution import run_task
    f = parent_result
    engine = analysis_execution.execute_bio_analysis
    def subset_engine(payload, out, mode, **kwargs):
        value = engine(payload, out, mode, **kwargs)
        value['manifest']['subset'] = payload['subset']
        return value
    monkeypatch.setattr(analysis_execution, 'execute_bio_analysis', subset_engine)
    created = client.post(f['base'] + '/bio-single-cell-subsets', json=dict(name='Subset report',
        parent_processed_source=f['source'], cluster_ids=['0'], params=dict(min_spots=1)), headers={'Idempotency-Key': 'subset-report'})
    assert created.status_code == 202, created.text
    task = created.json()['task']
    done = run_task(task['id'], task['revision'])
    assert done['status'] == 'succeeded', done
    result = client.get(f['base'] + '/bio-analysis-runs/' + created.json()['id']).json()['result_source']
    svc = service_for(f['source']['project_id'])
    view, _ = svc.prepare(f['source']['project_id'], dict(title='Subset', language='en', selection=dict(kind='processed',
        processed_version_id=result['processed_dataset_version_id'], annotation_version_id=None, figure_version_ids=[])), 'subset-context')
    fixed, _, _ = freeze(svc, f['source']['project_id'], view)
    summary = fixed['finding']['content']['sources'][0]['content']['summary']
    assert summary['subset']['parent_processed_source'] == f['source']
    assert summary['subset']['selected_cell_count'] == 1
    assert 'resolved_cell_ids' not in summary['subset']
    with svc.store.connection() as db:
        assert svc.require(db, 'bio_report_context_versions', f['source']['project_id'], view['id'])['content_json']['subset']['resolved_cell_ids'] == ['c1']
    assert all(table['source']['processed_version_id'] == result['processed_dataset_version_id'] for table in fixed['tables'])


def test_candidate_annotation_retains_all_published_scores_and_candidates(client, parent_result, monkeypatch):
    from tests.api.test_single_cell_batch4_flow import test_single_r_task_publishes_downloadable_candidates_and_replays
    test_single_r_task_publishes_downloadable_candidates_and_replays(client, parent_result, monkeypatch)
    f = parent_result
    result = client.get(f['base'] + '/bio-requests/single-r?kind=annotation_run').json()
    annotation = client.get(f['base'] + '/bio-single-cell-annotation-runs/' + result['id']).json()['result']
    annotation = client.get(f['base'] + f"/bio-annotation-sets/{annotation['set_id']}/versions/{annotation['version_id']}").json()
    svc = service_for(f['source']['project_id'])
    view, _ = svc.prepare(f['source']['project_id'], dict(title='Candidate annotations', language='en', selection=dict(kind='processed',
        processed_version_id=f['source']['processed_dataset_version_id'], annotation_version_id=annotation['id'], figure_version_ids=[])), 'candidate-context')
    fixed, _, payload = freeze(svc, f['source']['project_id'], view)
    for member in annotation['members']:
        if member['format'] != 'tsv':
            continue
        index = next(i for i, table in enumerate(fixed['tables']) if table['key'] == member['key'])
        assert payload['table_raws'][index] == client.get(member['download_url']).content
