"""Facts retain exact saved values, stable row identities and scientific limits."""
from copy import deepcopy

import pytest

from app.domain.research_results.contracts import FrozenResearchSource


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def source(**changes):
    value = dict(source_kind='bio_processed_dataset_version',source_id='processed1',
                 project_id='project1',sha256='a'*64,title='Synthetic spatial result',
                 provenance='public_reanalysis',source_file_ids=['file1'],content={
        'summary': {'raw_features':7,'raw_observations':4,'retained_features':3,
                    'retained_observations':3,'excluded_features':4,'excluded_observations':1,
                    'shape':[3,3],'clusters':2,'hvg':2,'pca_components':2,
                    'statistical_unit':'spot_exploratory',
                    'replicate_consistency':{'status':'not_computable','reason':'independent_donor_design_not_confirmed'},
                    'mitochondrial_reason':'mitochondrial_rule_unconfirmed'},
        'steps':[{'key':'filter','status':'completed','params':{'min_gene_spots':1}},
                 {'key':'markers','status':'not_computable','reason':'insufficient_groups','params':{}}],
        'params':{'target_sum':10000.0,'seed':0},'engine_version':'synthetic-v1',
        'code_digest':'b'*64,'environment_digest':'c'*64})
    value.update(changes)
    return FrozenResearchSource.model_validate(value)


def test_saved_shape_and_exclusions_are_bound_without_donor_inference():
    from app.domain.research_results.bio_projection import project_bio_facts
    catalog=project_bio_facts(source())
    facts={f.locator.field_path:f for f in catalog.facts}
    assert facts['summary.retained_observations'].raw_value==3
    assert facts['summary.retained_observations'].observation_level=='spot'
    assert facts['summary.retained_features'].raw_value==3
    assert all(f.source_sha256=='a'*64 for f in catalog.facts)
    assert not any(f.observation_level=='donor' for f in catalog.facts)
    assert any('donor' in s for s in catalog.gaps)
    assert any('探索性' in s for s in catalog.limitations)


def test_tabular_facts_use_sample_units_and_preserve_complete_method_recipe():
    from app.domain.research_results.bio_projection import project_bio_facts
    value=source().model_dump();value['content'].update(observation_level='sample',assay='proteomics',methods={'name':'tabular_quantitative_v1','params':{'transform':'none'},'input_scale':{'kind':'intensity','unit':'AU'}})
    catalog=project_bio_facts(FrozenResearchSource.model_validate(value))
    fact=next(f for f in catalog.facts if f.locator.field_path=='summary.retained_observations')
    assert fact.observation_level=='sample' and fact.unit=='samples'
    assert any(m.parameters.get('params')=={'transform':'none'} for m in catalog.methods)
    assert not any('spot' in item for item in catalog.limitations)


def test_sample_table_facts_keep_sample_stable_row_keys():
    from app.domain.research_results.bio_projection import project_bio_facts
    value=source(source_kind='bio_analysis_artifact',content={'table_key':'sample_qc','rows':[{'sample_id':'S1','missing_count':'0'}],'total_rows':1,'observation_level':'sample'})
    catalog=project_bio_facts(value)
    assert catalog.facts[0].locator.row_key=={'sample_id':'S1'} and catalog.facts[0].observation_level=='sample'


@pytest.mark.parametrize('key,value', [('excluded_features',2),('retained_observations',5),('clusters',True)])
def test_inconsistent_or_boolean_counts_cannot_be_published_as_facts(key,value):
    from app.domain.research_results.bio_projection import project_bio_facts
    original=source().model_dump();original['content']['summary'][key]=value
    with pytest.raises(ValueError):
        project_bio_facts(FrozenResearchSource.model_validate(original))


def test_failed_step_is_never_described_as_completed_and_real_parameters_are_preserved():
    from app.domain.research_results.bio_projection import project_bio_facts
    catalog=project_bio_facts(source())
    assert len(catalog.methods)==2
    assert catalog.methods[0].executed is True
    assert catalog.methods[0].parameters['min_gene_spots']==1
    assert catalog.methods[1].executed is False
    assert 'insufficient_groups' in catalog.methods[1].description
    assert catalog.source.content['params']['target_sum']==10000.0


def test_marker_decimal_na_and_duplicate_symbols_keep_feature_id_identity():
    from app.domain.research_results.bio_projection import project_bio_facts
    rows=[{'cluster':'0','feature_id':'ENSG1','symbol':'SAME','pval':'0.00000000000000012345','padj':'NA','log2fc':'0'},
          {'cluster':'0','feature_id':'ENSG2','symbol':'SAME','pval':'0.5','padj':'1','log2fc':'-1.25'}]
    value=source(source_kind='bio_analysis_artifact',source_id='marker-table',content={'table_key':'markers','rows':rows,'total_rows':2})
    catalog=project_bio_facts(value)
    p=next(f for f in catalog.facts if f.locator.row_key=={'cluster':'0','feature_id':'ENSG1'} and f.locator.column=='pval')
    assert p.raw_value=='0.00000000000000012345' and p.raw_type=='string'
    assert any(f.raw_value=='NA' and f.verification_status=='missing' for f in catalog.facts)
    assert len({f.id for f in catalog.facts})==len(catalog.facts)
    reordered=value.model_copy(deep=True);reordered.content['rows']=list(reversed(rows))
    assert {f.id for f in catalog.facts}=={f.id for f in project_bio_facts(reordered).facts}


def test_ambiguous_duplicate_row_keys_are_rejected():
    from app.domain.research_results.bio_projection import project_bio_facts
    row={'cluster':'0','feature_id':'ENSG1','pval':'0.01'}
    value=source(source_kind='bio_analysis_artifact',content={'table_key':'markers','rows':[row,deepcopy(row)],'total_rows':2})
    with pytest.raises(ValueError,match='Duplicate'):
        project_bio_facts(value)


def test_paged_catalog_is_explicit_and_does_not_claim_complete_table():
    from app.domain.research_results.bio_projection import project_bio_facts
    value=source(source_kind='bio_analysis_artifact',content={'table_key':'markers','rows':[{'cluster':'1','feature_id':'g1','pval':'0.02'}],'total_rows':40})
    assert any('1/40' in s for s in project_bio_facts(value).warnings)


def test_large_table_projection_requires_explicit_selection_not_silent_truncation():
    from app.domain.research_results.bio_projection import project_bio_facts
    rows=[{'cluster':'0','feature_id':f'g{i}','pval':'0.5'} for i in range(501)]
    value=source(source_kind='bio_analysis_artifact',content={'table_key':'markers','rows':rows,'total_rows':501})
    with pytest.raises(ValueError,match='select'):
        project_bio_facts(value)
