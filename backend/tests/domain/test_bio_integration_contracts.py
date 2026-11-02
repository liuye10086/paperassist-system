import json
import pytest
from app.domain.bio_insights.contracts import ResourceImportRequest,FigureConfig,InsightPlanRequest
from app.domain.bio_insights.integration_contracts import IntegrationConfig,normalize_correspondence

def test_typed_correspondence_and_old_resource_wire():
    base=dict(title='mapping',species_taxon_id=9606,namespace='symbol',release='unknown',source=dict(institution='source',name='source',description='frozen labels'),usage=dict(basis='declared',redistribution_allowed=False,scope='project'))
    old=ResourceImportRequest(kind='id_mapping',mapping_source_namespace='symbol',mapping_target_namespace='symbol',files=[dict(file_id='f',sha256='a'*64,role='id_mapping',format='tsv',columns={'source_id':'s','target_id':'t'})],**base).model_dump(mode='json')
    assert not {'sequence_type','nucleotide_encoding','structure_origin'}&old.keys()
    for kind in ('sample_correspondence','object_correspondence'):
        resource=ResourceImportRequest(kind=kind,files=[dict(file_id='f',sha256='a'*64,role=kind,format='tsv')],**base)
        assert resource.files[0].columns.model_dump(exclude_none=True)=={}
    with pytest.raises(ValueError):FigureConfig(result_source_id='r',figure_type='integration_network',contrast_id='c')
    rows=[dict(dataset_version='a',observation_id='A0FJ',donor_id='',tissue='',time='',match_group='A0FJ',relationship='author_declared_matched_sample',basis='author declared matched, full donor unknown',independent_unit_verified='false')]
    row=normalize_correspondence('sample_correspondence',rows)[0]
    assert row['donor_id'] is None and row['independent_unit_verified'] is False

def test_inference_admission_and_fixed_family():
    pairs=[dict(pair_id='p',left_source_id='a',left_feature_id='x',right_source_id='b',right_feature_id='y')]
    args=dict(processed_source_ids=['a','b'],sample_mapping_source_id='s',object_mapping_source_id='o',pairs=pairs)
    assert IntegrationConfig(**args).mode=='descriptive'
    with pytest.raises(ValueError):IntegrationConfig(**args,mode='inference')
    with pytest.raises(ValueError):IntegrationConfig(**{**args,'pairs':pairs*2})
    with pytest.raises(ValueError):IntegrationConfig(**args,transform='log2')


def test_concordance_admission_requires_complete_saved_families():
    from app.domain.bio_insights.integration_design import validate_integration_design
    config=IntegrationConfig(mapping_confirmed=True,concordances=[dict(concordance_id='c',left_result_source_id='a',right_result_source_id='b',left_contrast_id='c',right_contrast_id='c',object_ids=['g'],direction_alignment='same',comparison_basis='frozen control direction')])
    sources=[dict(source_id=s,metadata=dict(kind='result_import',summary_json={'tested_universe_complete':True})) for s in ('a','b')]
    assert validate_integration_design(config,sources).executable
    sources[1]['metadata']['summary_json']['tested_universe_complete']=False
    assert not validate_integration_design(config,sources).executable
