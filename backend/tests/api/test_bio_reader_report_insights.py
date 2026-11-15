"""Actual native rendering/enrichment over synthetic published source records."""
import pytest

from tests.api.test_projects import client
from tests.api.test_bio_reader_reports import service_for
from tests.api.test_bio_reader_report_annotation import freeze


def execute_plan(client, base, body, key, tmp_path):
    from app.domain.bio_insights.execution import run_bio_insight_task
    from app.adapters.bio_insights_engine.pipeline import run as pipeline
    plan = client.post(base + '/bio-insight-plans', json=body | {'name': key, 'decision': 'confirmed', 'expected_revision': 0}, headers={'Idempotency-Key': key + '-plan'})
    assert plan.status_code == 201, plan.text
    plan = plan.json()
    run = client.post(base + '/bio-insight-runs', json=dict(plan_version_id=plan['id'], expected_plan_revision=1,
        source_digest=plan['source_digest']), headers={'Idempotency-Key': key + '-run'})
    assert run.status_code == 202, run.text
    run = run.json()
    failures = []
    def engine(payload, output):
        try:
            return pipeline(payload | {'output_directory': str(output)})
        except Exception:
            import traceback
            failures.append(traceback.format_exc())
            raise
    done = run_bio_insight_task(run['task_id'], run['task_revision'], task_type=run['task']['task_type'],
        engine=engine, staging_directory=tmp_path / key)
    assert done['status'] == 'succeeded', (done, failures)
    return client.get(base + '/bio-insight-results/' + done['result_bio_insight_result_version_id']).json()


def test_insight_replots_keep_requested_order_and_do_not_expand_tables(client, monkeypatch, tmp_path):
    from tests.api.test_bio_insight_research_bridge import published
    from app.core.exceptions import StorageError
    from pathlib import Path
    from matplotlib import font_manager
    from app.adapters.bio_insights_engine import figures
    font = font_manager.findfont('DejaVu Sans')
    monkeypatch.setattr(figures, 'Path', lambda value: Path(font) if value == '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc' else Path(value))
    project, result, _ = published(client, monkeypatch, tmp_path)
    base = f'/api/v1/projects/{project}'
    def figure(key, title):
        return execute_plan(client, base, dict(kind='figure', sources=[dict(source_kind='bio_insight_result_version',
            source_id=result['id'], sha256=result['manifest_sha256'], role='result')], config=dict(kind='figure',
            result_source_id=result['id'], figure_type='volcano', formats=['png'], title=title, output_language='en')), key, tmp_path)
    first, second = figure('first', 'First volcano'), figure('second', 'Second volcano')
    url = base + '/bio-insight-results/' + result['id'] + '/figures'
    available = client.get(url)
    assert available.status_code == 200, available.text
    assert [(item['id'], item['figure_type'], item['source_sha256']) for item in available.json()['items']] == [
        (second['id'], 'volcano', result['manifest_sha256']), (first['id'], 'volcano', result['manifest_sha256'])]
    svc = service_for(project)
    request = dict(title='Exact insight figures', language='en', selection=dict(kind='insight', result_version_id=result['id'],
        figure_version_ids=[second['id'], first['id']]))
    view, _ = svc.prepare(project, request, 'insight-replots')
    fixed, _, payload = freeze(svc, project, view)
    assert [f['native_source']['result_version_id'] for f in fixed['figures']] == [second['id'], first['id']]
    assert [f['config']['title'] for f in fixed['figures']] == ['Second volcano', 'First volcano']
    assert {t['source']['result_version_id'] for t in fixed['tables']} == {result['id']}
    for image, selected in zip(payload['figures'], [second, first]):
        member = next(m for m in selected['members'] if m['key'] == 'figure_png')
        assert image['raw'] == client.get(member['download_url']).content
    # A figure result is not a source-compatible replacement for the comparison.
    with pytest.raises(StorageError):
        svc.prepare(project, request | {'selection': request['selection'] | {'result_version_id': first['id']}}, 'wrong-source')
    from app.core.config import get_data_dir

    with svc.store.connection() as db:
        member = db.execute("""SELECT o.object_key FROM bio_insight_result_members m JOIN storage_objects o
            ON o.id=m.storage_object_id WHERE m.result_version_id=%s AND m.key='figure_png'""", (second['id'],)).fetchone()
    png = get_data_dir() / member['object_key']
    raw = png.read_bytes()
    try:
        png.write_bytes(b'damaged saved picture')
        remaining = client.get(url)
        assert remaining.status_code == 200, remaining.text
        assert [item['id'] for item in remaining.json()['items']] == [first['id']]
    finally:
        png.write_bytes(raw)


def test_enrichment_keeps_only_full_selected_result_tables(client, monkeypatch, tmp_path):
    from tests.api.test_projects import create_project
    from tests.api.test_bio_insight_plans import source_file, import_plan
    from tests.api.test_bio_insight_publication import runtime
    from app.domain.bio_insights.execution import run_bio_insight_task
    from app.adapters.bio_insights_engine.pipeline import run as pipeline
    runtime(monkeypatch)
    project = create_project(client)['id']
    base = f'/api/v1/projects/{project}'
    source = source_file(client, project)
    body = import_plan(source, 'confirmed')
    body['config']['complete_tested_universe'] = True
    result = execute_plan(client, base, body, 'complete-import', tmp_path)
    uploaded = client.post(base + '/bio-resource-files', files={'file': ('sets.gmt', b't1\tSynthetic set\tg1\tg2\n')}, headers={'Idempotency-Key': 'gmt'}).json()
    resource = client.post(base + '/bio-resources', json=dict(kind='gene_sets', title='Synthetic sets', species_taxon_id=9606,
        namespace='Ensembl', release='v1', source=dict(institution='test', name='synthetic', description='Engineering fixture'),
        usage=dict(basis='project use', scope='project', redistribution_allowed=False),
        files=[dict(file_id=uploaded['file_id'], sha256=uploaded['sha256'], role='gmt', format='gmt')]), headers={'Idempotency-Key': 'resource'})
    assert resource.status_code == 202, resource.text
    resource = resource.json()
    done = run_bio_insight_task(resource['task_id'], resource['task']['revision'], task_type='bio_resource_import',
        engine=lambda payload, output: pipeline(payload | {'output_directory': str(output)}), staging_directory=tmp_path / 'resource')
    assert done['status'] == 'succeeded', done
    resource = client.get(base + '/bio-resources/' + resource['id']).json()
    result = execute_plan(client, base, dict(kind='ora', sources=[dict(source_kind='bio_insight_result_version', source_id=result['id'],
        sha256=result['manifest_sha256'], role='result'), dict(source_kind='bio_resource_version', source_id=resource['id'],
        sha256=resource['manifest_sha256'], role='gene_sets')], config=dict(kind='ora', result_source_ids=[result['id']],
        resource_source_ids=[resource['id']], contrast_ids=['c'], q_column='original_q')), 'ora', tmp_path)
    svc = service_for(project)
    view, _ = svc.prepare(project, dict(title='Full enrichment', language='en', selection=dict(kind='insight', result_version_id=result['id'], figure_version_ids=[])), 'enrichment')
    fixed, _, payload = freeze(svc, project, view)
    tables = [m for m in result['members'] if m['format'] in ('csv', 'tsv')]
    assert {t['key'] for t in fixed['tables']} == {m['key'] for m in tables}
    assert {t['source']['result_version_id'] for t in fixed['tables']} == {result['id']}
    assert all(raw == client.get(next(m for m in tables if m['key'] == table['key'])['download_url']).content for table, raw in zip(fixed['tables'], payload['table_raws']))
