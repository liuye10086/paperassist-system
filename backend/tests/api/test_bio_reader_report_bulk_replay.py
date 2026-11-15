"""A selected enrichment replot keeps its explicit choice through round-trip."""
from tests.api.test_projects import client
from tests.api.test_bio_reader_reports import service_for


def test_bulk_enrichment_replot_replays_explicit_selection_without_parent(client, monkeypatch, tmp_path):
    from app.domain.bio_insights.bulk_delivery import BulkDeliveryService
    from tests.helpers.bio_report_contexts import published_bulk
    from tests.helpers.bio_report_bulk_enrichment import publish_enrichment_replot

    base, _, comparison = published_bulk(client, monkeypatch, tmp_path)
    enrichment, replot = publish_enrichment_replot(client, monkeypatch, tmp_path, base, comparison)
    project = base.rsplit('/', 1)[-1]
    service = service_for(project)
    native = BulkDeliveryService(service.assets)
    chosen = dict(comparison_version_id=comparison['id'], language='en', result_version_ids=[replot['id']])
    facts = native.facts(project, **chosen)
    assert facts['selected_result_version_ids'] == [replot['id']]
    assert facts['result_version_ids'] == [enrichment['id'], replot['id']]
    body = dict(title='Fixed enrichment selection', language='en',
                selection=dict(kind='bulk', delivery=chosen | {'facts_digest': facts['facts_digest']}))
    first, status = service.prepare(project, body, 'one-explicit-replot')
    assert status == 201
    assert first['selection']['delivery']['result_version_ids'] == [replot['id']]
    replay, status = service.prepare(project, body | {'selection': first['selection']}, 'replayed-explicit-replot')
    assert status == 200 and replay == first
    fixed = first['source']['supporting_sources'][0]
    assert fixed['delivery'] == first['selection']['delivery']
    assert fixed['facts']['result_version_ids'] == [enrichment['id'], replot['id']]
    material = {k:v for k,v in fixed['delivery'].items() if k != 'facts_digest'}
    assert native.facts(project, **material)['facts_digest'] == fixed['delivery']['facts_digest']
