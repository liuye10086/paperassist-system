import pytest
from pydantic import ValidationError
from app.domain.bio_insights.contracts import ResourceImportRequest,InsightPlanRequest,FigureConfig
from app.domain.bio_insights.service import BioInsightsService


def test_old_resource_wire_is_unchanged_and_rna_encoding_is_explicit():
    base=dict(kind='gene_sets',title='legacy',species_taxon_id=9606,namespace='local',release='1',source=dict(institution='test',name='test',description='fixture'),usage=dict(basis='test',redistribution_allowed=True,scope='project'),files=[dict(file_id='file',sha256='a'*64,format='gmt',role='gmt')])
    old=ResourceImportRequest(**base).model_dump(mode='json')
    assert not {'sequence_type','nucleotide_encoding','structure_origin'}&old.keys()
    new={**base,'kind':'sequence','sequence_type':'rna','files':[dict(file_id='file',sha256='a'*64,format='fasta',role='fasta')]}
    with pytest.raises(ValidationError,match='rna_nucleotide_encoding_required'):ResourceImportRequest(**new)
    assert ResourceImportRequest(**new,nucleotide_encoding='T').model_dump()['sequence_type']=='rna'


def test_candidate_plan_accepts_actual_feature_result_as_annotation_only():
    config=dict(kind='candidate',result_source_ids=['comparison'],source_contrasts={'comparison':'ab'},primary_result_source_id='comparison',annotation_source_ids=['features'],steps=[dict(operation='annotation',annotation_field='gc_fraction',annotation_operator='ge',annotation_value=.4)])
    sources=[dict(source_kind='bio_insight_result_version',source_id=sid,role=role,sha256='a'*64) for sid,role in [('comparison','result'),('features','feature_annotation')]]
    request=InsightPlanRequest(name='native annotation',kind='candidate',expected_revision=0,config=config,sources=sources)
    resolved=[dict(source_kind='bio_insight_result_version',source_id='comparison',metadata=dict(kind='comparison',species_taxon_id=9606,namespace='local',reference_version='1',plan_config={'contrasts':[{'contrast_id':'ab'}]}),members={}),dict(source_kind='bio_insight_result_version',source_id='features',metadata=dict(kind='feature_extract',species_taxon_id=9606,namespace='local',reference_version='1',plan_config={'kind':'feature_extract'}),members={'resource':{}})]
    assert BioInsightsService._design(object(),request.config,resolved).executable
    resolved[1]['metadata']['kind']='figure'
    assert not BioInsightsService._design(object(),request.config,resolved).executable
    with pytest.raises(ValidationError):FigureConfig(figure_type='feature_scatter',result_source_id='features',x_column='ca_count')


def test_standard_cif_filename_alias_retains_explicit_mmcif_contract():
    from app.domain.bio_insights.uploads import EXTENSIONS
    from app.domain.bio_insights.resources import resource_filename_matches
    original='pdb_00001ubq_xyz_v1-3.cif.gz'
    assert original.endswith(EXTENSIONS)
    assert resource_filename_matches(original,'mmcif.gz')
    assert resource_filename_matches('1UBQ.CIF','mmcif')
    assert not resource_filename_matches(original,'mmcif')
    assert not resource_filename_matches('1ubq.pdb.gz','mmcif.gz')


def test_feature_plan_rejects_eleventh_frozen_source_even_when_not_referenced():
    sources = [dict(source_kind='bio_resource_version', source_id=f'r{i}', role='feature_input', sha256='a'*64) for i in range(11)]
    request = dict(name='bounded extraction', kind='feature_extract', expected_revision=0, config=dict(kind='feature_extract', resource_source_ids=['r0']))
    assert len(InsightPlanRequest(**request, sources=sources[:10]).sources) == 10
    with pytest.raises(ValidationError, match='feature_frozen_source_limit'):
        InsightPlanRequest(**request, sources=sources)
