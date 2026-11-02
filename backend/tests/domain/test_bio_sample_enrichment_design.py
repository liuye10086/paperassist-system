"""New sample-result admission uses the existing explicit enrichment gates."""
import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


@pytest.mark.parametrize('kind', ['ora', 'gsea_prerank'])
@pytest.mark.parametrize('scope', ['sample_inference', 'sample_exploratory'])
def test_sample_enrichment_admission_and_local_mapping_blocks(kind, scope):
    from app.domain.bio_insights.contracts import OraConfig, GseaPrerankConfig, CandidateConfig
    from app.domain.bio_insights.service import BioInsightsService
    config = (OraConfig(result_source_ids=['r'], resource_source_ids=['g'], contrast_ids=['c'])
              if kind == 'ora' else GseaPrerankConfig(result_source_id='r', resource_source_ids=['g'], contrast_id='c', ranking_column='statistic'))
    result = dict(source_kind='bio_insight_result_version', source_id='r', metadata=dict(
        kind='comparison', species_taxon_id=9606, namespace='fixture_gene', reference_version='fixed', inference_scope=scope,
        plan_config={'kind': 'comparison', 'schema_version': 2, 'contrasts': [{'contrast_id': 'c'}]}))
    resource = dict(source_kind='bio_resource_version', source_id='g', metadata=dict(
        kind='gene_sets', species_taxon_id=9606, namespace='fixture_gene'))
    design = lambda sources: BioInsightsService._design(None, config, sources)
    assert design([result, resource]).executable
    result['metadata']['species_taxon_id'] = None
    assert 'incompatible_species' in {r.code for r in design([result, resource]).blocking_reasons}
    candidate = CandidateConfig(result_source_ids=['r'], primary_result_source_id='r', source_contrasts={'r': 'c'},
        steps=[dict(operation='threshold', source_ids=['r'], q_column='q_within_contrast', q_threshold=.05, minimum_absolute_effect=0.)])
    assert BioInsightsService._design(None, candidate, [result]).executable
    result['metadata']['species_taxon_id'] = 9606
    resource['metadata']['namespace'] = 'other_gene'
    assert 'namespace_mapping_required' in {r.code for r in design([result, resource]).blocking_reasons}
    mapping = dict(source_kind='bio_resource_version', source_id='m', metadata=dict(kind='id_mapping',
        species_taxon_id=9606, namespace='fixture_gene', mapping_source_namespace='fixture_gene', mapping_target_namespace='other_gene'))
    config=config.model_copy(update={'mapping_source_ids':['m']})
    assert design([result, resource, mapping]).executable
