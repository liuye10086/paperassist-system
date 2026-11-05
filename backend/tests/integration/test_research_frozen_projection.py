"""Historical source projections survive additive metadata, never byte changes."""
import hashlib

from tests.api.test_projects import client


def test_legacy_finding_report_remain_readable_after_layers_projection_added(client, monkeypatch, tmp_path):
    from tests.integration.test_research_lineage_phases import processed
    from tests.integration.test_research_validation_efficiency import report_service
    from app.domain.research_results.sources import ResearchSourceReader
    from app.domain.research_results.execution import run_research_report_task
    from app.adapters.research_report_render import render_report
    from app.adapters.bio_analysis_store import BioAnalysisStore

    base, value = processed(client, monkeypatch, tmp_path)
    original = ResearchSourceReader._bio
    def legacy(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        result['content'].pop('layers', None)
        return result
    with monkeypatch.context() as old:
        old.setattr(ResearchSourceReader, '_bio', legacy)
        response = client.post(base+'/research-findings', json=dict(title='Legacy fixed result', sources=[
            dict(source_kind='bio_processed_dataset_version', source_id=value['id'])]),
            headers={'Idempotency-Key':'legacy-finding'})
        assert response.status_code == 201, response.text
        finding = response.json()
        report = client.post(base+'/research-reports', json=dict(title='Legacy report', finding_version_id=finding['id']),
                             headers={'Idempotency-Key':'legacy-report'}).json()
        done = run_research_report_task(report['task_id'], report['task']['revision'], engine=render_report,
                                       staging_directory=tmp_path/'report-stage')
        assert done['status'] == 'succeeded', done
    finding_url = base+f"/research-findings/{finding['set_id']}/versions/{finding['id']}"
    read = client.get(finding_url)
    assert read.status_code == 200, read.text
    assert read.json() == finding
    listed = client.get(base+'/research-reports')
    assert listed.status_code == 200, listed.text
    saved = listed.json()['items'][0]
    member = next(m for m in saved['members'] if m['role'] == 'docx')
    downloaded = client.get(member['download_url'])
    assert downloaded.status_code == 200
    assert hashlib.sha256(downloaded.content).hexdigest() == member['sha256']
    project = base.rsplit('/', 1)[-1]
    service = report_service(project); store = BioAnalysisStore(service.assets)
    with store.store.connection() as db:
        _, _, members = store.raw(db, project, value['source']['raw_source'])
        path = store.raw_store.objects.path(members[0]['object_key'])
    path.write_bytes(path.read_bytes()+b'changed')
    assert client.get(finding_url).status_code == 409
    assert client.get(member['download_url']).status_code == 409


def test_legacy_bio_figure_task_projection_preserves_panel_caption_and_download(client, monkeypatch, tmp_path):
    from pathlib import Path
    from PIL import Image
    from tests.integration.test_research_lineage_phases import processed
    from tests.integration.test_bio_analysis_wait import payload_engine
    from app.domain.bioinformatics.analysis_execution import run_bio_figure_task
    from app.domain.research_results.execution import run_research_figure_task
    from app.adapters.research_figure_render import render_figure
    from app.domain.research_results.sources import ResearchSourceReader
    from app.core.config import get_data_dir
    from app.db.database import database_connection

    base, value = processed(client, monkeypatch, tmp_path)
    bio = client.post(base+'/bio-figures', json=dict(processed_source=value['source'], expected_version=0,
        config={'kind':'qc'}), headers={'Idempotency-Key':'legacy-bio-figure'})
    assert bio.status_code == 202, bio.text
    bio = bio.json()
    def image_engine(payload, output, mode):
        result = payload_engine(payload, output, mode)
        path = Path(output)/'fixture.png'; Image.new('RGB', (80,40), 'red').save(path)
        raw = path.read_bytes()
        result['outputs'].append(dict(key='fixture_png', role='figure_png', format='png', path=str(path),
            size_bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
        return result
    done = run_bio_figure_task(bio['task']['id'], bio['task']['revision'], engine=image_engine,
                              staging_directory=tmp_path/'bio-staging')
    assert done['status'] == 'succeeded', done
    source = dict(source_kind='bio_figure_version', source_id=bio['id'])
    original = ResearchSourceReader._bio_figure
    def legacy(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        for key in ('result_bio_resource_version_id', 'result_bio_insight_result_version_id'):
            assert result['content']['figure']['task'].pop(key) is None
        return result
    with monkeypatch.context() as old:
        old.setattr(ResearchSourceReader, '_bio_figure', legacy)
        response = client.post(base+'/research-figures', json=dict(mode='reuse', panels=[dict(source=source)],
            caption_sources=[source], width_mm=85.0, dpi=150, formats=['png']),
            headers={'Idempotency-Key':'legacy-research-figure'})
        assert response.status_code == 201, response.text
        figure = response.json()
        done = run_research_figure_task(figure['task_id'], figure['task']['revision'], engine=render_figure,
                                       staging_directory=tmp_path/'research-figure-stage')
        assert done['status'] == 'succeeded', done
    endpoint = base+'/research-figures/'+figure['id']
    read = client.get(endpoint); assert read.status_code == 200, read.text
    assert client.get(base+'/research-figures').status_code == 200
    for member in read.json()['members']:
        raw = client.get(member['download_url']); assert raw.status_code == 200
        assert hashlib.sha256(raw.content).hexdigest() == member['sha256']
    with database_connection() as db:
        key = db.execute('SELECT o.object_key FROM storage_objects o JOIN bio_figure_members m ON m.storage_object_id=o.id '
                         "WHERE m.figure_version_id=%s AND m.format='png'", (bio['id'],)).fetchone()['object_key']
    path = Path(get_data_dir())/key; path.write_bytes(path.read_bytes()+b'changed')
    assert client.get(endpoint).status_code == 409
    assert client.get(member['download_url']).status_code == 409
