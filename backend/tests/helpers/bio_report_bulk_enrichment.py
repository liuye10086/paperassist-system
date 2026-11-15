"""Publish a real ORA and saved replot over the synthetic Bulk comparison.

Uses the normal resource import, plan/run APIs, source validation, numerical
ORA, plotting and publication. Only the caller's upstream estimator is synthetic.
"""
from pathlib import Path


def publish_enrichment_replot(client, monkeypatch, tmp_path, base, comparison):
    from matplotlib import font_manager
    from app.adapters.bio_insights_engine import figures
    from app.adapters.bio_insights_engine.pipeline import run as pipeline
    from app.domain.bio_insights.execution import run_bio_insight_task
    from tests.api.test_bio_reader_report_insights import execute_plan

    # Production uses the locked Linux font. The Windows engineering fixture
    # uses a locally available font without changing rendering/selection logic.
    font = font_manager.findfont('DejaVu Sans')
    monkeypatch.setattr(figures, 'Path', lambda value: Path(font)
        if value == '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc' else Path(value))
    response = client.post(base + '/bio-resource-files', files={'file': (
        'fixed-sets.gmt', b'term_a\tSynthetic A\tf1\tf2\nterm_b\tSynthetic B\tf2\tf3\n')},
        headers={'Idempotency-Key': 'bulk-replot-gmt'})
    assert response.status_code == 201, response.text
    uploaded = response.json()
    response = client.post(base + '/bio-resources', json=dict(kind='gene_sets', title='Synthetic fixed sets',
        species_taxon_id=9606, namespace='ensembl', release='fixed', offline_enrichment=True,
        source=dict(institution='test', name='synthetic', description='Engineering fixture'),
        usage=dict(basis='Synthetic test data', scope='redistributable', redistribution_allowed=True),
        files=[dict(file_id=uploaded['file_id'], sha256=uploaded['sha256'], role='gmt', format='gmt')]),
        headers={'Idempotency-Key': 'bulk-replot-resource'})
    assert response.status_code == 202, response.text
    resource = response.json()
    done = run_bio_insight_task(resource['task_id'], resource['task']['revision'], task_type='bio_resource_import',
        engine=lambda payload, output: pipeline(payload | {'output_directory': str(output)}),
        staging_directory=tmp_path / 'bulk-replot-resource')
    assert done['status'] == 'succeeded', done
    response = client.get(base + '/bio-resources/' + resource['id'])
    assert response.status_code == 200, response.text
    resource = response.json()
    enrichment = execute_plan(client, base, dict(kind='ora', sources=[
        dict(source_kind='bio_insight_result_version', source_id=comparison['id'],
             sha256=comparison['manifest_sha256'], role='result'),
        dict(source_kind='bio_resource_version', source_id=resource['id'],
             sha256=resource['manifest_sha256'], role='gene_sets')],
        config=dict(kind='ora', result_source_ids=[comparison['id']], resource_source_ids=[resource['id']],
                    contrast_ids=['B_A'], q_column='original_method_adjustment', min_size=1, max_size=10,
                    bulk_enrichment=dict(source_taxon_id=9606, taxon_evidence='Explicit synthetic fixture origin'))),
        'bulk-report-ora', tmp_path)
    replot = execute_plan(client, base, dict(kind='figure', sources=[
        dict(source_kind='bio_insight_result_version', source_id=enrichment['id'],
             sha256=enrichment['manifest_sha256'], role='result')],
        config=dict(kind='figure', result_source_id=enrichment['id'], figure_type='enrichment',
                    bulk_enrichment_render=True, enrichment_order='adjusted_metric_term_id',
                    contrast_id='B_A', formats=['png'], title='Selected enrichment replot', output_language='en')),
        'bulk-report-ora-replot', tmp_path)
    return enrichment, replot
