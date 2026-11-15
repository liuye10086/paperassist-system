"""Native Bulk proof and shortcut retain selected thresholds, tables and image order."""
import pytest

from tests.api.test_projects import client
from tests.api.test_bio_reader_reports import service_for
from tests.api.test_bio_reader_report_annotation import freeze


def test_bulk_preparation_uses_native_delivery_digest_and_shortcut(client, monkeypatch, tmp_path):
    from tests.helpers.bio_report_contexts import published_bulk
    from app.domain.bio_insights.bulk_delivery import BulkDeliveryService
    from app.core.exceptions import StorageError
    base, processed, result = published_bulk(client, monkeypatch, tmp_path)
    project = base.rsplit('/', 1)[-1]
    svc = service_for(project)
    delivery = dict(comparison_version_id=result['id'], language='en', result_version_ids=[],
                    selections=[dict(contrast_id='B_A', direction='up', minimum_absolute_effect=1.0, q_threshold=.05)])
    facts = BulkDeliveryService(svc.assets).facts(project, **delivery)
    body = dict(title='Bulk RNA report', language='en', selection=dict(kind='bulk', delivery=delivery | {'facts_digest': facts['facts_digest']}))
    view, _ = svc.prepare(project, body, 'bulk')
    fixed, _, payload = freeze(svc, project, view)
    assert [f['document_image']['sha256'] for f in fixed['figures']] == [f['png']['sha256'] for f in facts['figures'] if f['png']]
    assert all(f['native_source']['source_kind'] == 'bio_analysis_artifact' for f in fixed['figures'])
    assert {'comparison_results', 'selected_B_A'} <= {table['key'] for table in fixed['tables']}
    with svc.store.connection() as db:
        content = svc.require(db, 'bio_report_context_versions', project, view['id'])['content_json']
        assert content['scientific']['summary']['selections'] == facts['selections']
        assert content['supporting_sources'][0]['facts'] == facts
    with pytest.raises(StorageError):
        svc.prepare(project, body | {'selection': {'kind': 'bulk', 'delivery': delivery | {'facts_digest': 'f'*64}}}, 'wrong-preview')
    shortcut, _ = svc.prepare(project, dict(title='Bulk shortcut', language='en', selection=dict(kind='insight', result_version_id=result['id'], figure_version_ids=[])), 'shortcut')
    short, _, _ = freeze(svc, project, shortcut)
    assert [t['sha256'] for t in short['tables']] == [t['sha256'] for t in fixed['tables']]
    default_delivery = dict(comparison_version_id=result['id'], language='en', result_version_ids=[])
    default_facts = BulkDeliveryService(svc.assets).facts(project, **default_delivery)
    explicit, status = svc.prepare(project, dict(title='Bulk shortcut', language='en', selection=dict(kind='bulk',
        delivery=default_delivery | {'facts_digest': default_facts['facts_digest']})), 'explicit-default')
    assert status == 200 and explicit == shortcut
    assert all('generated' not in blob for blob in content['table_blobs'])
