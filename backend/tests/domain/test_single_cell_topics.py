import pytest
from pydantic import ValidationError

from app.domain.bio_insights.single_cell_topic_contracts import SingleCellTopicConfig
from app.domain.bio_insights.single_cell_topics import topic_selection, validate_topic_design

@pytest.fixture(autouse=True)
def postgres_schema():yield None


def sources(donors=True):
    rows=[dict(processed_version_id='p',barcode=f'c{i}',retained=i!=6,donor=f'd{i//2}' if donors else None,
               sample=f's{i//2}',condition='ctrl' if i%2==0 else 'stim') for i in range(7)]
    return [dict(source_id='p',source_kind='bio_processed_dataset_version',metadata=dict(assay='single_cell',species_taxon_id=9606,
        observations=rows,cell_clusters={f'c{i}':str(i%2) for i in range(6)},retained_feature_ids=['g1','g2','g3']),members={'pca':{},'log1p_data':{}}),
        dict(source_id='a',source_kind='bio_annotation_version',metadata=dict(processed_dataset_version_id='p',labels=[{'id':'T'},{'id':'B'}],
        assignments={'rows':[dict(barcode=f'c{i}',label_id='T' if i%2==0 else 'B',status='assigned' if i!=5 else 'uncertain') for i in range(6)]}))]


def trajectory(**kwargs):
    return SingleCellTopicConfig(processed_source_id='p',method='slingshot',root_cluster='0',root_basis='Engineering root, not biological time',**kwargs)


def test_trajectory_requires_explicit_root_basis():
    with pytest.raises(ValidationError):SingleCellTopicConfig(processed_source_id='p',method='slingshot',root_cluster='0')


def test_regulators_must_belong_to_explicit_gene_axis():
    with pytest.raises(ValidationError):
        SingleCellTopicConfig(processed_source_id='p',method='genie3',gene_ids=['g1','g2'],tf_ids=['absent'],tf_basis='curated list')


def test_selected_cells_keep_original_axis_and_exclusion_reasons():
    selected=topic_selection(trajectory(cluster_ids=['0']),sources())
    assert [r['barcode'] for r in selected['selected']]==['c0','c2','c4']
    assert selected['exclusions']['not_retained']==1
    assert selected['exclusions']['cluster_not_selected']==3


def test_missing_root_is_blocked_before_execution():
    config=trajectory().model_copy(update={'root_cluster':'missing'})
    preview=validate_topic_design(config,sources())
    assert not preview.executable
    assert 'trajectory_root_missing' in [r.code for r in preview.blocking_reasons]


def test_annotation_parent_mismatch_is_not_silently_reused():
    src=sources();src[1]['metadata']['processed_dataset_version_id']='other'
    config=trajectory(annotation_source_id='a',label_ids=['T'])
    with pytest.raises(ValueError,match='annotation_processed_mismatch'):topic_selection(config,src)


def test_uncertain_cells_excluded_from_label_selected_topic_and_counted():
    config=trajectory(annotation_source_id='a',label_ids=['T','B'])
    selected=topic_selection(config,sources())
    assert len(selected['selected'])==5
    assert selected['exclusions']['annotation_uncertain']==1


def test_communication_missing_donors_blocks_inference_not_description():
    config=SingleCellTopicConfig(processed_source_id='p',annotation_source_id='a',label_ids=['T','B'],method='cellchat',
        condition_values=['ctrl','stim'],communication_mode='paired',min_cells=2)
    result=validate_topic_design(config,sources(donors=False))
    assert not result.executable
    assert 'communication_donor_required' in [r.code for r in result.blocking_reasons]
    descriptive=validate_topic_design(config.model_copy(update={'communication_mode':'per_donor'}),sources(donors=False))
    assert 'communication_donor_required' not in [r.code for r in descriptive.blocking_reasons]


def test_technical_samples_do_not_increase_donor_units():
    config=SingleCellTopicConfig(processed_source_id='p',annotation_source_id='a',label_ids=['T','B'],method='cellchat',min_cells=2)
    src=sources()
    for row in src[0]['metadata']['observations']:row['donor']='one';row['condition']='ctrl'
    selected=topic_selection(config,src)
    assert len(selected['units'])==1
    assert selected['units'][0]['cell_count']==5


def test_topic_contract_uses_existing_integration_envelope():
    from app.domain.bio_insights.contracts import InsightPlanRequest
    c=trajectory()
    plan=InsightPlanRequest(name='Trajectory',kind='integration',expected_revision=0,config=c,
        sources=[dict(source_kind='bio_processed_dataset_version',source_id='p',role='processed',sha256='a'*64)])
    assert plan.config.method=='slingshot' and plan.config.schema_version==2


def test_fixed_observation_map_overlays_topic_donor_condition_and_sample():
    from app.domain.bio_insights.sources import apply_observation_maps
    processed=sources()[0];processed['metadata']['raw_dataset_version_id']='raw'
    mapping=dict(metadata=dict(raw_dataset_version_id='raw',rows=[dict(barcode=f'c{i}',donor={'status':'known','value':'new_donor'},group={'status':'known','value':'new_condition'},sample_id={'status':'known','value':'new_sample'}) for i in range(7)]))
    apply_observation_maps([processed],[mapping])
    row=processed['metadata']['observations'][0]
    assert (row['donor'],row['condition'],row['sample'])==('new_donor','new_condition','new_sample')


def test_same_barcode_from_other_raw_dataset_does_not_overlay_topic():
    from app.domain.bio_insights.sources import apply_observation_maps
    processed=sources()[0];processed['metadata']['raw_dataset_version_id']='raw'
    apply_observation_maps([processed],[dict(metadata=dict(raw_dataset_version_id='other',rows=[dict(barcode='c0',donor={'status':'known','value':'wrong'})]))])
    assert processed['metadata']['observations'][0]['donor']=='d0'


@pytest.mark.parametrize('method',['slingshot','genie3'])
def test_topic_optional_species_does_not_change_old_frozen_configuration(method):
    config=trajectory() if method=='slingshot' else SingleCellTopicConfig(method='genie3',processed_source_id='p',gene_ids=['g1','g2'],tf_ids=['g1'],tf_basis='curated')
    old=config.model_dump(mode='json')
    old.pop('species_taxon_id',None);old.pop('species_basis',None)
    assert SingleCellTopicConfig.model_validate(old).model_dump(mode='json')==old
    assert SingleCellTopicConfig.model_validate({**old,'species_taxon_id':None,'species_basis':''}).model_dump(mode='json')==old


@pytest.mark.parametrize('fields',[
    {'species_taxon_id':9606},
    {'species_taxon_id':9606,'species_basis':'  '},
    {'species_basis':'publication'},
])
def test_topic_species_declaration_requires_taxon_and_basis(fields):
    with pytest.raises(ValidationError):
        SingleCellTopicConfig(method='cellchat',processed_source_id='p',annotation_source_id='a',label_ids=['T','B'],**fields)


def test_species_declaration_is_cellchat_only():
    with pytest.raises(ValidationError):trajectory(species_taxon_id=9606,species_basis='publication')


@pytest.mark.parametrize('upstream,declared,expected,code',[
    (None,9606,True,None),
    (None,None,False,'communication_resource_species_mismatch'),
    (9606,10090,False,'communication_species_declaration_conflict'),
    (10090,9606,False,'communication_species_declaration_conflict'),
    (9606,9606,True,None),
])
def test_topic_preview_resolves_optional_species_without_overriding_upstream(monkeypatch,upstream,declared,expected,code):
    from app.domain.bio_insights import sources as source_module
    from app.domain.bio_insights.service import BioInsightsService
    src=sources();metadata=src[0]['metadata'];metadata.update(species_taxon_id=upstream,feature_ids=['g1','g2'])
    fields={} if declared is None else dict(species_taxon_id=declared,species_basis='original publication')
    config=SingleCellTopicConfig.model_validate(dict(method='cellchat',processed_source_id='p',annotation_source_id='a',label_ids=['T','B'],**fields))
    reader=object.__new__(source_module.InsightSourceReader);reader.assets=object()
    from types import SimpleNamespace
    selections=[SimpleNamespace(source_id=s['source_id'],source_kind=s['source_kind']) for s in src]
    reader._resolve_in_phase=lambda db,project,selection,**kwargs:next(s for s in src if s['source_id']==selection.source_id)
    monkeypatch.setattr(source_module,'require_phase',lambda *args:None)
    resolved=reader._resolve_many_in_phase(None,'project',selections,config,phase=object())
    assert metadata['species_taxon_id']==(declared if upstream is None else upstream)
    preview=object.__new__(BioInsightsService)._design(config,resolved)
    assert preview.executable is expected
    if code:assert code in [reason.code for reason in preview.blocking_reasons]
