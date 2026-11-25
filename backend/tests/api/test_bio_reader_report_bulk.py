"""Native Bulk proof and shortcut retain selected thresholds, tables and image order."""
from hashlib import sha256

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

    from app.domain.bio_insights import bulk_delivery
    from app.domain.delivery_packages.report_sources import reader_report_analysis_digest

    chinese_delivery = dict(delivery, language='zh')
    chinese_facts = BulkDeliveryService(svc.assets).facts(project, **chinese_delivery)
    chinese, _ = svc.prepare(project, dict(title='转录组分析报告', language='zh-CN', selection=dict(kind='bulk',
        delivery=chinese_delivery | {'facts_digest': chinese_facts['facts_digest']})), 'bulk-zh')
    assert chinese['report']['finding_version_id'] != view['report']['finding_version_id']
    # The frozen analysis equivalence should survive an update to display text.
    monkeypatch.setitem(bulk_delivery._LIMITS, 'en', ('Updated English presentation text.',))
    with svc.store.connection() as db:
        owner = svc.store.user_id
        en_key = reader_report_analysis_digest(db, project, owner, view['report']['finding_version_id'])
        zh_key = reader_report_analysis_digest(db, project, owner, chinese['report']['finding_version_id'])
        assert en_key and en_key == zh_key
        assert en_key != reader_report_analysis_digest(db, project, owner, shortcut['report']['finding_version_id'])


def test_bulk_preparation_keeps_report_tables_when_full_workbook_exceeds_budget(client, monkeypatch, tmp_path):
    from docx import Document
    from openpyxl import load_workbook
    from app.adapters import research_results_xlsx as workbook
    from app.adapters.research_report_render import render_report, stage_report_payload
    from app.domain.bio_insights.bulk_delivery import BulkDeliveryService
    from app.domain.bio_reader_reports.bulk import _workbook_metadata_cells
    from app.domain.bio_reader_reports.materials import table_cell_count
    from tests.helpers.bio_report_contexts import published_bulk
    from tests.helpers.research_report import sample_reader_record

    base, _, result = published_bulk(client, monkeypatch, tmp_path)
    project = base.rsplit('/', 1)[-1]
    service = service_for(project)
    delivery = dict(comparison_version_id=result['id'], language='en')
    facts = BulkDeliveryService(service.assets).facts(project, **delivery)
    body = dict(title='Bulk report', language='en',
                selection=dict(kind='bulk', delivery=delivery | {'facts_digest': facts['facts_digest']}))
    full, _ = service.prepare(project, body, 'full-workbook')
    full_snapshot, _, _ = freeze(service, project, full)
    full_tables = {table['key']: table for table in full_snapshot['tables']}
    assert {'comparison_results', 'selected_B_A', 'model_counts', 'model_normalized_counts'} <= full_tables.keys()

    comparison_keys = ('comparison_results', 'selected_B_A')
    cells = sum(table_cell_count(full_tables[key]) + 4 for key in comparison_keys)
    with service.store.connection() as db:
        full_content = service.require(db, 'bio_report_context_versions', project, full['id'])['content_json']
    monkeypatch.setattr(workbook, 'MAX_CELLS', _workbook_metadata_cells(full_content) + cells + 2)
    response = client.post(base + '/bio-reader-reports/prepare', json=body,
                           headers={'Idempotency-Key': 'limited-workbook'})
    assert response.status_code == 201, response.text
    view = response.json()
    assert view['workbook_limited'] is True
    snapshot, _, payload = freeze(service, project, view)
    tables = {table['key']: table for table in snapshot['tables']}
    assert tables == {key: full_tables[key] for key in comparison_keys}
    assert snapshot['figures'] == full_snapshot['figures']
    assert view['selection'] == full['selection']
    notice = next(text for text in snapshot['finding']['content']['warnings'] if 'workbook cell budget' in text)
    assert notice.startswith(f"{len(full_snapshot['tables']) - len(snapshot['tables'])} result table")
    snapshot['reader_report'] = sample_reader_record(snapshot)
    staging = tmp_path / 'report-input'
    staging.mkdir()
    output = tmp_path / 'report-output'
    output.mkdir()
    rendered = render_report(stage_report_payload(payload, staging), output)
    assert rendered['manifest']['row_counts']['total_cells'] <= workbook.MAX_CELLS
    assert notice in [paragraph.text for paragraph in Document(output / 'analysis.docx').paragraphs]
    with (output / 'results.xlsx').open('rb') as file:
        book = load_workbook(file, read_only=True)
        assert notice in [row[1] for row in book['Limitations'].values]
        book.close()
    member = full_tables['model_counts']['source']['source_id']
    original = client.get(f"{base}/bio-insight-results/{result['id']}/members/{member}/download")
    assert original.status_code == 200
    assert sha256(original.content).hexdigest() == full_tables['model_counts']['sha256']
    assert service.request_receipt(project, 'full-workbook') == full
