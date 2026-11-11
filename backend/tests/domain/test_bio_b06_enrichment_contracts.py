import pytest
from pydantic import ValidationError

from app.domain.bio_insights.contracts import FigureConfig, GseaPrerankConfig, InsightPlanRequest, OraConfig, ResourceImportRequest
from app.domain.bio_insights.service import BioInsightsService


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


DECLARATION = {'source_taxon_id': 9606, 'taxon_evidence': 'Bioconductor airway source metadata'}
ORA = dict(kind='ora', result_source_ids=['fixed'], contrast_ids=['a_vs_b'], resource_source_ids=['reactome'])
GSEA = dict(kind='gsea_prerank', result_source_id='fixed', contrast_id='a_vs_b', ranking_column='wald_statistic',
            resource_source_ids=['reactome'])


def frozen_result(**metadata):
    return dict(source_id='fixed', source_kind='bio_insight_result_version', members={'comparison_results': {}},
                metadata=dict(kind='comparison', namespace='Ensembl gene ID', reference_version='airway package release data',
                              summary_json={'tested_universe_complete': True},
                              plan_config={'mode': 'bulk_counts', 'bulk_model': 'shared_wald_v1',
                                           'contrasts': [{'contrast_id': 'a_vs_b'}]}) | metadata)


def local_resource(**metadata):
    return dict(source_id='reactome', source_kind='bio_resource_version', members={'resource': {}},
                metadata=dict(kind='gene_sets', namespace='ensembl_gene_id', species_taxon_id=9606, release='98') | metadata)


def preview(config, *sources):
    return BioInsightsService._design(None, config, list(sources))


def test_fixed_bulk_ora_accepts_native_q_and_preserves_generic_wire():
    assert 'bulk_enrichment' not in OraConfig.model_validate(ORA).model_dump(mode='json')
    options = ORA | {'q_column': 'original_method_adjustment', 'bulk_enrichment': DECLARATION}
    assert OraConfig.model_validate(options).model_dump(mode='json')['bulk_enrichment'] == DECLARATION
    for invalid in ({'bulk_enrichment': None}, {'q_column': 'original_q'}, {'foreground_member_key': 'top'},
                    {'background_source_id': 'bg', 'background_member_key': 'genes'},
                    {'result_source_ids': ['fixed', 'another']}):
        with pytest.raises(ValidationError):
            OraConfig.model_validate(options | invalid)


def test_bulk_gsea_requires_fixed_wald_ranking_and_declaration_evidence():
    assert 'bulk_enrichment' not in GseaPrerankConfig.model_validate(GSEA).model_dump(mode='json')
    assert GseaPrerankConfig.model_validate(GSEA | {'bulk_enrichment': {}}).ranking_column == 'wald_statistic'
    with pytest.raises(ValidationError):
        GseaPrerankConfig.model_validate(GSEA | {'bulk_enrichment': DECLARATION, 'ranking_column': 'effect_value'})
    with pytest.raises(ValidationError):
        GseaPrerankConfig.model_validate(GSEA | {'bulk_enrichment': {'source_taxon_id': 9606}})


def test_preview_accepts_explicit_missing_taxon_without_guessing_or_changing_frozen_result():
    source = frozen_result()
    refused = preview(OraConfig.model_validate(ORA | {'bulk_enrichment': {}}), source, local_resource())
    assert not refused.executable
    assert {reason.code for reason in refused.blocking_reasons} == {'bulk_source_taxon_required'}
    accepted = preview(OraConfig.model_validate(ORA | {'bulk_enrichment': DECLARATION}), source, local_resource())
    assert accepted.executable
    record = accepted.model_dump(mode='json')['enrichment_compatibility']
    assert record['source']['taxon_origin'] == 'explicit_plan_declaration'
    assert record['source']['species_taxon_id'] == 9606
    assert record['source']['namespace'] == 'ensembl_gene_id'
    assert record['resources'][0]['reference_status'] == 'stable_id_resource_no_assembly_declared'
    assert 'species_taxon_id' not in source['metadata']


@pytest.mark.parametrize(('source', 'resource', 'code'), [
    (frozen_result(species_taxon_id=10090), local_resource(), 'bulk_source_taxon_conflict'),
    (frozen_result(), local_resource(species_taxon_id=10090), 'incompatible_species'),
    (frozen_result(), local_resource(plan_config={'reference_version': 'GRCh38'}), 'bulk_reference_version_mismatch'),
    (frozen_result(), local_resource(namespace='entrez_gene_id'), 'namespace_mapping_required'),
    (frozen_result(summary_json={'tested_universe_complete': False}), local_resource(), 'bulk_complete_comparison_required'),
])
def test_bulk_enrichment_preflight_blocks_incompatible_frozen_inputs(source, resource, code):
    config = GseaPrerankConfig.model_validate(GSEA | {'bulk_enrichment': DECLARATION})
    checked = preview(config, source, resource)
    assert not checked.executable
    assert code in {reason.code for reason in checked.blocking_reasons}


def test_enrichment_plan_requires_exact_fixed_result_and_resource_objects():
    def selection(key, kind, role, locator=None):
        return dict(source_id=key, source_kind=kind, role=role, locator=locator or {'kind': 'object'}, sha256='a' * 64)

    fixed = selection('fixed', 'bio_insight_result_version', 'result')
    resource = selection('reactome', 'bio_resource_version', 'gene_sets')
    request = dict(kind='gsea_prerank', name='Fixed Bulk GSEA', expected_revision=0,
                   config=GSEA | {'bulk_enrichment': DECLARATION}, sources=[fixed, resource])
    assert InsightPlanRequest.model_validate(request).config.result_source_id == 'fixed'
    with pytest.raises(ValidationError):
        InsightPlanRequest.model_validate(request | {'sources': [fixed, resource,
            selection('other', 'bio_insight_result_version', 'result')]})


def test_saved_enrichment_curve_and_local_resource_opt_in_to_offline_runtime():
    figure = FigureConfig(result_source_id='fixed', figure_type='gsea', term_row_key='row', bulk_enrichment_render=True)
    assert figure.model_dump(mode='json')['bulk_enrichment_render'] is True
    with pytest.raises(ValidationError):
        FigureConfig(result_source_id='fixed', figure_type='volcano', bulk_enrichment_render=True)
    request = dict(kind='gene_sets', title='Reactome', species_taxon_id=9606, namespace='ensembl_gene_id', release='98',
                   source={'name': 'Reactome', 'institution': 'Reactome', 'description': 'Fixed collection'},
                   usage={'basis': 'CC0', 'redistribution_allowed': True, 'scope': 'redistributable'},
                   files=[{'file_id': 'gmt', 'sha256': 'a' * 64, 'role': 'gmt', 'format': 'gmt'}])
    legacy = ResourceImportRequest.model_validate(request).model_dump(mode='json')
    assert not {'offline_enrichment', 'reference_version'} & legacy.keys()
    local = ResourceImportRequest.model_validate(request | {'offline_enrichment': True, 'reference_version': 'GRCh38'})
    assert local.model_dump(mode='json')['reference_version'] == 'GRCh38'


def test_bulk_ora_figure_preview_disables_an_uncomputed_contrast():
    saved = dict(source_id='fixed', source_kind='bio_insight_result_version', members={'enrichment_results': {}},
        metadata={'kind': 'ora', 'plan_config': {'bulk_enrichment': {}, 'contrast_ids': ['ab', 'ba']},
                  'methods_json': {'bulk_enrichment': {'coverage': [
                      {'contrast_id': 'ab', 'eligible_term_count': 0},
                      {'contrast_id': 'ba', 'eligible_term_count': 5},
                  ]}}})
    figure = FigureConfig(result_source_id='fixed', figure_type='enrichment', bulk_enrichment_render=True,
                          enrichment_order='adjusted_metric_term_id', contrast_id='ab')
    blocked = preview(figure, saved)
    assert {reason.code for reason in blocked.blocking_reasons} == {'bulk_enrichment_figure_contrast_unavailable'}
    assert preview(figure.model_copy(update={'contrast_id': 'ba'}), saved).executable


def test_reviewed_bulk_uses_fixed_entry_for_new_plans_with_legacy_run_compatibility():
    service = object.__new__(BioInsightsService)
    legacy = GseaPrerankConfig.model_validate(GSEA | {'ranking_column': 'effect_value'})
    sources = [frozen_result(species_taxon_id=9606, namespace='ensembl_gene_id'), local_resource()]
    assert service._design(legacy, sources).executable
    blocked = service._authoring_design(legacy, sources)
    assert {reason.code for reason in blocked.blocking_reasons} == {'bulk_enrichment_use_fixed_entry'}


def test_bulk_gsea_figure_binds_the_term_to_its_frozen_comparison(tmp_path):
    table = tmp_path / 'enrichment_results.tsv'
    table.write_text('row_key\tcontrast_id\nterm-row\ta_vs_b\n', encoding='utf-8')
    saved = dict(source_id='fixed', source_kind='bio_insight_result_version',
        members={'enrichment_results': {'format': 'tsv', 'path': str(table), 'size_bytes': table.stat().st_size},
                 'gsea_curves': {}, 'gsea_ranking': {}},
        metadata={'kind': 'gsea_prerank', 'plan_config': {'bulk_enrichment': {}, 'contrast_id': 'a_vs_b'}})
    curve = FigureConfig(result_source_id='fixed', figure_type='gsea', term_row_key='term-row',
                         contrast_id='a_vs_b', bulk_enrichment_render=True)
    assert preview(curve, saved).executable
    assert not preview(curve.model_copy(update={'contrast_id': 'b_vs_a'}), saved).executable
