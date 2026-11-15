"""Real source/storage checks in an isolated database; scientific fixtures are synthetic."""
import importlib.util

import pytest

from tests.api.test_projects import client, create_project


def service_for(project):
    assert importlib.util.find_spec('app.domain.bio_reader_reports') is not None, 'Native report context service is missing'
    from app.domain.bio_reader_reports import BioReaderReportService
    from app.adapters.storage import ProjectStore
    from app.core.config import get_data_dir
    from app.db.database import database_connection
    with database_connection() as db:
        owner = db.execute('SELECT owner_id FROM projects WHERE id=%s', (project,)).fetchone()['owner_id']
    return BioReaderReportService(ProjectStore(get_data_dir(), owner_id=owner))


def test_processed_context_reuses_identity_and_preserves_exact_table_and_figure_bytes(client, monkeypatch, tmp_path):
    from tests.api.test_bio_quantitative_lifecycle import processed_fixture
    from app.core.exceptions import StorageError
    from app.domain.research_results.contracts import ResearchReportRequest
    from app.domain.research_results.reports import ResearchReportService
    base, pid = processed_fixture(client, monkeypatch, tmp_path)
    project = base.rsplit('/', 1)[-1]
    svc = service_for(project)
    body = dict(title='Fixed proteomics', language='en', selection=dict(kind='processed',
                processed_version_id=pid, annotation_version_id=None, figure_version_ids=[]))
    view, status = svc.prepare(project, body, 'prepare')
    assert status == 201 and view['report']['figure_version_ids'] == []
    assert svc.prepare(project, body, 'prepare') == (view, 200)
    assert svc.prepare(project, body, 'alias') == (view, 200)
    assert svc.request_receipt(project, 'alias') == view
    assert svc.get(project, view['id']) == view
    with pytest.raises(StorageError) as error:
        svc.prepare(project, body | {'title': 'changed'}, 'alias')
    assert error.value.status == 409
    with pytest.raises(StorageError) as error:
        svc.get(create_project(client)['id'], view['id'])
    assert error.value.status == 404
    with svc.store.connection() as db:
        content, _, payload = ResearchReportService(svc.assets).freeze(db, project, ResearchReportRequest(**view['report']))
        assert content['figures'] and all(f['native_source']['source_kind'] == 'bio_analysis_artifact' for f in content['figures'])
        assert payload['table_raws'] and all(t['expected_rows'] > 0 for t in content['tables'])
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0
        assert db.execute('SELECT count(*) AS n FROM bio_report_context_files WHERE context_id=%s', (view['id'],)).fetchone()['n'] == 2
        from app.domain.research_results.source_changes import dependency_impact
        fid = db.execute('SELECT file_id FROM bio_report_context_files WHERE context_id=%s LIMIT 1', (view['id'],)).fetchone()['file_id']
        affected = dependency_impact(db, project, svc.store.user_id, 'original_file', fid)['affected']
        assert {('bio_report_context', view['id']), ('research_finding_version', view['report']['finding_version_id'])} <= {(r['source_kind'], r['source_id']) for r in affected}
        with pytest.raises(StorageError):
            ResearchReportService(svc.assets).freeze(db, project, ResearchReportRequest(**(view['report'] | {'figure_version_ids': ['unrelated']})))


def test_insight_context_exports_only_selected_result_complete_tables_and_reverse_impact(client, monkeypatch, tmp_path):
    from tests.api.test_bio_insight_research_bridge import published
    from app.domain.research_results.contracts import ResearchReportRequest
    from app.domain.research_results.reports import ResearchReportService
    from app.domain.research_results.source_changes import dependency_impact
    project, result, member = published(client, monkeypatch, tmp_path)
    svc = service_for(project)
    body = dict(title='External comparison', language='en', selection=dict(kind='insight', result_version_id=result['id'], figure_version_ids=[]))
    view, _ = svc.prepare(project, body, 'insight')
    from app.domain.research_results.catalog import ResearchCatalog
    catalog = ResearchCatalog(svc.assets).list(project, 'bio_report_context')
    assert [(item['source_id'], item['title'], item['sha256']) for item in catalog['items']] == [(view['id'], body['title'], view['source']['sha256'])]
    with svc.store.connection() as db:
        content, _, payload = ResearchReportService(svc.assets).freeze(db, project, ResearchReportRequest(**view['report']))
        assert [t['key'] for t in content['tables']] == [m['key'] for m in result['members'] if m['format'] in ('csv', 'tsv')]
        assert content['tables'][0]['expected_rows'] == 2
        assert b'g2\tg2\t\t0.2' in payload['table_raws'][0]
        impacted = dependency_impact(db, project, svc.store.user_id, 'bio_insight_result_version', result['id'])
        assert ('bio_report_context', view['id']) in {(r['source_kind'], r['source_id']) for r in impacted['affected']}
        from app.domain.file_lifecycle.research_results_references import read_groups
        from app.domain.file_lifecycle.metadata_summary import read_metadata_counts
        from app.maintenance.research_results_audit import validate_source
        file = dict(db.execute('SELECT * FROM files WHERE id=(SELECT file_id FROM bio_report_context_files WHERE context_id=%s LIMIT 1)', (view['id'],)).fetchone())
        groups = read_groups(db, file, svc.store.user_id)
        assert [r['id'] for r in groups['bio_report_context_versions']] == [view['id']]
        assert all(r['_integrity_valid'] for r in groups['bio_report_context_versions'])
        assert read_metadata_counts(db, file, svc.store.user_id)['bio_report_context_versions'] == 1
        validate_source(db, project, svc.store.user_id, view['source'])


def test_failed_finding_rolls_back_context_and_retry_uses_same_request(client, monkeypatch, tmp_path):
    from tests.api.test_bio_insight_research_bridge import published
    from app.domain.research_results.findings import ResearchFindingService
    project, result, _ = published(client, monkeypatch, tmp_path)
    svc = service_for(project)
    body = dict(title='Atomic selection', language='en', selection=dict(kind='insight', result_version_id=result['id'], figure_version_ids=[]))
    def failure(*args, **kwargs):
        raise RuntimeError('injected finding failure')
    with monkeypatch.context() as injected:
        injected.setattr(ResearchFindingService, '_create_in_transaction', failure)
        with pytest.raises(RuntimeError, match='injected finding failure'):
            svc.prepare(project, body, 'retry')
    with svc.store.connection() as db:
        assert db.execute('SELECT count(*) AS n FROM bio_report_context_versions').fetchone()['n'] == 0
        assert db.execute('SELECT count(*) AS n FROM bio_report_context_files').fetchone()['n'] == 0
        assert db.execute('SELECT count(*) AS n FROM bio_report_context_requests').fetchone()['n'] == 0
    view, status = svc.prepare(project, body, 'retry')
    assert status == 201 and svc.request_receipt(project, 'retry') == view
