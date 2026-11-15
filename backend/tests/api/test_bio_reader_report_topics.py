"""Frozen topic reports use real lifecycle/projection over a synthetic R bridge."""
import hashlib

from tests.api.test_projects import client
from tests.api.test_bio_reader_reports import service_for
from tests.api.test_bio_reader_report_annotation import freeze


def test_trajectory_report_preserves_complete_tables_and_native_figure(client, monkeypatch, tmp_path):
    from tests.helpers.bio_report_topics import published_trajectory
    from tests.api.test_bio_reader_report_insights import execute_plan
    from app.adapters.bio_insights_engine import figures
    from matplotlib import font_manager
    from pathlib import Path
    base, processed, result = published_trajectory(client, monkeypatch, tmp_path)
    project = base.rsplit('/',1)[-1]
    service = service_for(project)
    request = dict(title='Synthetic trajectory report', language='en', selection=dict(kind='insight',
                   result_version_id=result['id'], figure_version_ids=[]))
    view, _ = service.prepare(project, request, 'trajectory-report')
    content, _, payload = freeze(service, project, view)
    tables = [item for item in result['members'] if item['format'] in ('tsv','csv')]
    assert {table['key'] for table in content['tables']} == {table['key'] for table in tables}
    assert next(t['expected_rows'] for t in content['tables'] if t['key'] == 'trajectory_results') == 4
    image = next(item for item in result['members'] if item['key'] == 'topic_plot')
    assert len(content['figures']) == 1
    assert content['figures'][0]['document_image']['sha256'] == image['sha256']
    assert hashlib.sha256(payload['figures'][0]['raw']).hexdigest() == image['sha256']
    assert payload['figures'][0]['raw'] == client.get(image['download_url']).content
    assert service.prepare(project, request, 'trajectory-reuse') == (view, 200)
    font = font_manager.findfont('DejaVu Sans')
    monkeypatch.setattr(figures, 'Path', lambda value: Path(font)
        if value == '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc' else Path(value))
    replot = execute_plan(client, base, dict(kind='figure', sources=[dict(source_kind='bio_insight_result_version',
        source_id=result['id'], sha256=result['manifest_sha256'], role='result')], config=dict(kind='figure',
        result_source_id=result['id'], figure_type='topic_slingshot', formats=['png'],
        title='Saved trajectory view', output_language='en')), 'trajectory-replot', tmp_path)
    available = client.get(base + '/bio-insight-results/' + result['id'] + '/figures')
    assert available.status_code == 200, available.text
    listed, = available.json()['items']
    assert listed['id'] == replot['id'] and listed['figure_type'] == 'topic_slingshot'
    changed, _ = service.prepare(project, request | {'selection': request['selection'] |
        {'figure_version_ids':[replot['id']]}}, 'trajectory-selected-figure')
    selected, _, selected_payload = freeze(service, project, changed)
    assert changed['id'] != view['id']
    assert selected['tables'] == content['tables']
    assert selected['figures'][0]['native_source']['result_version_id'] == replot['id']
    selected_image = next(m for m in replot['members'] if m['key'] == 'figure_png')
    assert selected_payload['figures'][0]['raw'] == client.get(selected_image['download_url']).content
    assert freeze(service, project, view)[0] == content
