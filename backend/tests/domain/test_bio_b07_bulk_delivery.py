from contextlib import nullcontext
from datetime import datetime, timezone
from io import BytesIO
import json
import re
from types import SimpleNamespace
from uuid import uuid4
from zipfile import ZipFile

from docx import Document
from PIL import Image
import pytest

from app.adapters.bio_analysis_store import BioAnalysisStore
from app.adapters.bio_insights_store import BioInsightsObjects
from app.adapters.task_store import TaskStore
from app.core.exceptions import StorageError
from app.domain.bioinformatics.contracts import digest
from app.domain.bio_insights.service import BioInsightsService
from tests.domain.test_bio_b05_selection import write_comparisons


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


@pytest.fixture
def published(monkeypatch, tmp_path):
    records, inputs = {}, {}
    assets = SimpleNamespace(owner_id='owner', db_config=object(), directory=tmp_path)
    insights = BioInsightsObjects(tmp_path)
    analysis = BioAnalysisStore(assets)
    def stored(objects, content):
        identifier = str(uuid4())
        data = json.dumps(content, ensure_ascii=False).encode() if isinstance(content, (dict, list)) else content
        record = objects.describe(identifier, data, json=isinstance(content, (dict, list)))
        objects.write(record, data)
        return {'id': identifier, **record}

    def member(objects, key, format, role, content):
        record = stored(objects, content)
        records['storage_objects', (record['id'], 'project', 'owner')] = record
        return {**record, 'storage_object_id': record['id'], 'key': key, 'role': role, 'format': format, 'shape_json': {}}

    def publish(identifier, kind, config, sources, members, *, summary=None, methods=None, resource=None):
        summary, methods = summary or {}, methods or {}
        resources = resource is not None
        manifest = dict(members=members, engine_version='bio_insights_v1.0.0', identity={'code_digest': 'code'},
                        summary=summary, methods=methods)
        if resources:
            manifest['input_snapshot_sha256'] = members[0]['sha256']
        ref = stored(insights, manifest)
        row = dict(id=identifier, kind=kind, provenance='system_computed', inference_scope='sample_inference',
                   manifest_object_id=ref['id'], manifest_sha256=ref['sha256'], task_id=identifier,
                   run_id=identifier + '-run', plan_version_id=identifier + '-plan') | (resource or {})
        version_table = 'bio_resource_versions' if resources else 'bio_insight_result_versions'
        member_table = 'bio_resource_members' if resources else 'bio_insight_result_members'
        records[version_table, (identifier, 'project', 'owner')] = row
        records[member_table, (identifier, 'project', 'owner')] = members
        records['storage_objects', (ref['id'], 'project', 'owner')] = ref
        records['tasks', (identifier, 'owner', 'owner')] = {'id': identifier, 'status': 'succeeded'}
        inputs[identifier] = {'config': config, 'sources': sources}
        return {'source_id': identifier, 'source_kind': 'bio_resource_version' if resources else 'bio_insight_result_version',
                'sha256': ref['sha256']}

    qc_sample = dict(sample_id='sample_A', condition='A', batch='batch_1', donor='donor_1', biological_unit_id='u_1',
                     library_size=42, detected_features=6, missing_count=0, zero_fraction=0, kept=True,
                     exclusion_reason='', outlier_advisory='')
    qc_table = '\t'.join(qc_sample) + '\n' + '\t'.join(map(str, qc_sample.values())) + '\n'
    png = BytesIO()
    Image.new('RGB', (100, 70), '#552288').save(png, format='PNG')
    qc_png = member(analysis.objects, 'qc_missing_png', 'png', 'figure', png.getvalue())
    qc_members = [member(analysis.objects, 'sample_qc', 'tsv', 'table', qc_table.encode()), qc_png]
    raw_members = [member(analysis.raw_store.objects, 'sample_mapping', 'json', 'sample_mapping',
                          dict(source={'file_id': 'sample-table'}, mapping={'sample_id': 'Sample'},
                               rows=[{'sample_id': 'sample_A', 'source_row': 2}]))]
    qc_manifest = dict(assay='bulk_rna_counts', summary=dict(raw_observations=1, retained_observations=1,
                       excluded_observations=0, raw_features=7, retained_features=7, excluded_features=0),
                       steps=[{'key': 'qc', 'status': 'completed'}], params={}, methods={'name': 'tabular_quantitative_v1'},
                       raw_source={'dataset_id': 'raw-dataset', 'dataset_version_id': 'raw', 'source_file_ids': ['sample-table']})
    qc = {'source_id': 'qc', 'source_kind': 'bio_processed_dataset_version', 'sha256': 'a' * 64,
          'raw': {'manifest': {'source_files': [{'id': 'sample-table', 'filename': 'samples.tsv', 'sha256': 'b' * 64}]}},
          'metadata': {'manifest': qc_manifest, 'assay': 'bulk_rna_counts'}}
    comparison_path = tmp_path / 'comparison.tsv'
    write_comparisons(comparison_path)
    comparison_table = member(insights, 'comparison_results', 'tsv', 'table', comparison_path.read_bytes())
    design = dict(executable=True, bulk_model=dict(formula='~ condition', condition_reference='B', rank=2,
                  residual_degrees_freedom=4, terms=[], design_columns=['Intercept', 'condition[T.A]'],
                  samples=[{k: qc_sample[k] for k in ('sample_id', 'condition', 'batch', 'donor', 'biological_unit_id')}
                           | {'processed_version_id': 'qc'}]), actual_units=[], exclusions=[])
    config = dict(kind='comparison', mode='bulk_counts', bulk_model='shared_wald_v1', output_language='en',
                  namespace='Ensembl gene ID', contrasts=[dict(contrast_id='ab', groups=[{'label': 'A'}, {'label': 'B'}]),
                                                          dict(contrast_id='ba', groups=[{'label': 'B'}, {'label': 'A'}])])
    comparison_members = [comparison_table, member(insights, 'comparison_design', 'json', 'metadata', design)]
    comparison = publish('comparison', 'comparison', config, [qc], comparison_members,
                         summary={'tested_universe_complete': True, 'row_count': 8}, methods={'name': 'Wald'})
    records['bio_insight_plan_versions', ('comparison-plan', 'project', 'owner')] = dict(
        id='comparison-plan', plan_id='plan-root', decision='confirmed', confirmed_by='owner',
        confirmed_at=datetime(2026, 11, 10, 8, tzinfo=timezone.utc),
        design_checks_json={'reviewed_design_sha256': 'c' * 64})
    other = publish('other-comparison', 'comparison', config, [qc], comparison_members)
    resources = [member(insights, 'input_snapshot', 'json', 'input_snapshot', {'source': 'local'}),
                 member(insights, 'resource', 'json', 'resource', {'kind': 'gene_sets'})]
    resource = publish('collection', 'gene_sets', {}, [], resources, resource=dict(species_taxon_id=9606,
                       namespace='ensembl_gene_id', release='v1', usage_json={}, source_json={}))
    ora_config = dict(kind='ora', bulk_enrichment={'source_taxon_id': 9606, 'taxon_evidence': 'Declared input origin'},
                      contrast_ids=['ab'], resource_source_ids=['collection'], mapping_source_ids=[],
                      q_threshold=0.01, minimum_absolute_effect=2, direction='up')
    ora_methods = dict(name='ORA_hypergeometric_right_tail', bulk_enrichment=dict(
        source_reference=dict(species_taxon_id=9606, namespace='ensembl_gene_id', reference_version=None,
                              taxon_origin='explicit_plan_declaration', taxon_evidence='Declared input origin'),
        resource_references={'collection': {'release': 'v1', 'reference_version': None}},
        coverage=[dict(contrast_id='ab', resource_id='collection', direction='up', not_applicable_reason='empty_foreground',
                       background={'original_count': 5, 'effective_count': 4}, foreground={'original_count': 0, 'effective_count': 0})]))
    ora_summary = dict(enrichment_status='not_applicable', not_applicable_reason='empty_foreground', row_count=0, significant_terms=0)
    ora_members = [member(insights, 'enrichment_results', 'tsv', 'table', b'term_id\tterm_name\tq_value\n')]
    enrichment = publish('ora', 'ora', ora_config, [comparison, resource], ora_members, summary=ora_summary, methods=ora_methods)
    other_enrichment = publish('unrelated-ora', 'ora', ora_config, [other, resource], ora_members,
                               summary=ora_summary, methods=ora_methods)
    figure_member = member(insights, 'figure_png', 'png', 'figure', png.getvalue())
    for identifier, source, figure_type in [('bulk-figure', comparison, 'bulk_volcano'),
                                            ('ora-figure', enrichment, 'enrichment'),
                                            ('unrelated-figure', other_enrichment, 'enrichment')]:
        figure_config = dict(kind='figure', figure_type=figure_type, title='Fixture title', result_source_id=source['source_id'],
                             bulk_enrichment_render=figure_type == 'enrichment')
        publish(identifier, 'figure', figure_config, [source], [figure_member], methods=dict(
            figure_type=figure_type, config=figure_config, source_id=source['source_id'], source_sha256=source['sha256'],
            analysis_recomputed=False))

    records['projects', ('project', 'owner')] = {'id': 'project'}
    def execute(query, parameters):
        table = re.search(r'\bFROM (\w+)', query).group(1)
        value = records.get((table, parameters))
        return SimpleNamespace(fetchone=lambda: value, fetchall=lambda: value)

    monkeypatch.setattr(TaskStore, 'connection', lambda self: nullcontext(SimpleNamespace(execute=execute)))
    monkeypatch.setattr(BioInsightsService, '_require_sources_in_phase', lambda self, db, task, *, phase, runtime: inputs[task['id']])
    monkeypatch.setattr(BioAnalysisStore, '_processed_lineage_in_phase', lambda self, db, project, identifier, *, phase:
                        ({'id': identifier, 'task_id': 'qc', 'manifest_sha256': qc['sha256']}, qc_manifest, qc_members))
    monkeypatch.setattr(BioAnalysisStore, '_raw_lineage_in_phase', lambda self, db, project, source, *, phase:
                        ({'id': 'raw'}, qc['raw']['manifest'], raw_members))
    records['tasks', ('qc', 'owner', 'owner')] = {'id': 'qc', 'status': 'succeeded'}
    return SimpleNamespace(assets=assets, inputs=inputs, records=records, comparison=comparison)


def service(published, monkeypatch):
    from app.domain.bio_insights import bulk_delivery

    monkeypatch.setattr(bulk_delivery, 'VerificationPhase', lambda *args: nullcontext(None))
    return bulk_delivery.BulkDeliveryService(published.assets)


def test_facts_freeze_fixed_counts_and_selections_for_every_direction(published, monkeypatch):
    delivery = service(published, monkeypatch)
    selection = dict(contrast_id='ab', direction='up')
    facts = delivery.facts('project', 'comparison', selections=[selection])
    ab, ba = facts['contrasts']
    assert (ab['numerator'], ab['denominator'], ba['numerator'], ba['denominator']) == ('A', 'B', 'B', 'A')
    assert ab['counts'] == dict(total=7, tested=6, excluded=1, not_computable=1, missing_metric=1,
                                deg=3, up=2, down=1, selected=2)
    assert [row['feature_id'] for row in ab['top_rows']] == ['gA', 'gB']
    assert [row['q_within_contrast'] for row in ab['top_rows']] == ['0', '0']
    assert ba['counts']['down'] == 1
    assert facts['design']['species_taxon_id'] is None and facts['design']['reference_version'] is None
    assert facts['design']['confirmation'] == dict(plan_version_id='comparison-plan', plan_id='plan-root',
        confirmed_by='owner', confirmed_at='2026-11-10T08:00:00+00:00', reviewed_design_sha256='c' * 64)
    assert facts['qc']['samples'][0]['sample_id'] == 'sample_A'
    assert facts['qc']['sample_mapping']['rows'][0]['source_row'] == 2
    assert facts['processed_version_ids'] == ['qc']
    assert facts['facts_digest'] == digest({k: v for k, v in facts.items() if k != 'facts_digest'})
    assert delivery.facts('project', 'comparison', selections=[selection]) == facts
    assert delivery.facts('project', 'comparison')['facts_digest'] != facts['facts_digest']


def test_facts_check_attachment_lineage_even_through_enrichment_figure(published, monkeypatch):
    delivery = service(published, monkeypatch)
    with pytest.raises(StorageError) as project_error:
        delivery.facts('other-project', 'comparison')
    assert project_error.value.status == 404
    with pytest.raises(StorageError) as source_error:
        delivery.facts('project', 'comparison', result_version_ids=['unrelated-figure'])
    assert source_error.value.status == 409
    facts = delivery.facts('project', 'comparison', result_version_ids=['ora-figure'])
    assert facts['selected_result_version_ids'] == ['ora-figure']
    assert set(facts['result_version_ids']) == {'ora', 'ora-figure'}
    assert facts['resource_version_ids'] == ['collection']
    assert facts['enrichments'][0]['status'] == 'not_applicable'
    assert facts['enrichments'][0]['coverage'][0]['foreground']['original_count'] == 0
    assert facts['enrichments'][0]['source_reference']['taxon_origin'] == 'explicit_plan_declaration'
    published.inputs['ora-figure']['sources'][0] |= {'sha256': 'f' * 64}
    with pytest.raises(StorageError) as binding_error:
        delivery.facts('project', 'comparison', result_version_ids=['ora-figure'])
    assert binding_error.value.status == 409


def test_docx_uses_bulk_language_and_frozen_figures_and_rejects_rehashed_changes(published, monkeypatch):
    delivery = service(published, monkeypatch)
    evidence = [{'kind': 'independent_analysis', 'source_id': 'separate-run',
                 'classification': 'independent_computational_analysis', 'verification_status': 'saved_execution_verified',
                 'independence_status': 'unverified', 'shared_processed_source_ids': ['qc'], 'sha256': 'd' * 64}]
    facts = delivery.facts('project', 'comparison', result_version_ids=['bulk-figure', 'ora'], language='en', evidence=evidence)
    content = delivery.docx('project', facts)
    doc = Document(BytesIO(content))
    with ZipFile(BytesIO(content)) as docx:
        assert any(name.startswith('word/media/') for name in docx.namelist())
    assert len(doc.inline_shapes) == 2
    all_text = '\n'.join(p.text for p in doc.paragraphs) + '\n' + '\n'.join(
        c.text for t in doc.tables for r in t.rows for c in r.cells)
    for literal in ('Bulk RNA-seq', 'A vs B', 'B vs A', 'sample_A', 'gA', 'empty_foreground', 'Fixture title'):
        assert literal in all_text
    assert 'Biological independence status unverified' in all_text
    assert 'Shared processed source versions qc' in all_text
    assert 'single-cell' not in all_text.casefold()
    facts['contrasts'][0]['numerator'] = 'altered'
    facts['facts_digest'] = digest({k: v for k, v in facts.items() if k != 'facts_digest'})
    with pytest.raises(StorageError) as tamper_error:
        delivery.docx('project', facts)
    assert tamper_error.value.status == 409
