import pytest

@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def config(mode='descriptive', **changes):
    return dict(kind='comparison', schema_version=5, method='single_cell_composition',
        processed_source_id='p', annotation_source_id='a', label_ids=['T'], labels_confirmed=True,
        label_basis='Manual marker review', mode=mode, numerator='B', denominator='A',
        mapping_confirmed=True, independence_confirmed=True, independence_basis='Known donors', **changes)


def sources(pairs=3):
    observations=[]; assignments=[]
    for condition in ('A','B'):
        for donor in range(pairs):
            for j,status in enumerate(('assigned','unknown','uncertain','ambiguous')):
                barcode=f'{condition}{donor}-{j}'
                observations.append(dict(processed_version_id='p',barcode=barcode,condition=condition,
                    donor=f'd{donor}',sample=f'{condition}{donor}-{j//2}',batch=f'b{j//2}',retained=True,library_counts=10))
                assignments.append(dict(barcode=barcode,label_id='T' if status in ('assigned','uncertain') else None,status=status))
    return [dict(source_kind='bio_processed_dataset_version',source_id='p',metadata=dict(assay='single_cell',observations=observations)),
            dict(source_kind='bio_annotation_version',source_id='a',metadata=dict(processed_dataset_version_id='p',labels=[dict(id='T',name='T')],assignments=dict(rows=assignments)))]


def test_schema5_is_accepted_in_existing_comparison_plan():
    from app.domain.bio_insights.contracts import InsightPlanRequest
    value=InsightPlanRequest.model_validate(dict(name='Composition',kind='comparison',expected_revision=0,
        config=config(),sources=[dict(source_kind=s['source_kind'],source_id=s['source_id'],role='processed' if s['source_id']=='p' else 'annotation',sha256='a'*64) for s in sources()]))
    assert value.config.schema_version==5


def test_unknown_uncertain_and_conflict_remain_in_denominator_technical_samples_merge():
    from app.domain.bio_insights.single_cell_composition import composition_data
    data=composition_data(config(),sources())
    assert len(data['units'])==6
    assert {r['denominator_cells'] for r in data['counts']}=={4}
    t=[r for r in data['counts'] if r['label_id']=='T']
    assert len(t)==6 and {r['cell_count'] for r in t}=={1}
    assert {r['category'] for r in data['counts']}=={'label','unknown','uncertain','conflict','unlabeled','other'}
    assert sum(r['cell_count'] for r in data['counts'])==24
    assert len(data['assignments'])==24


@pytest.mark.parametrize('pairs,mode,reason',[(2,'donor_paired','insufficient_pairs'),(3,'donor_unpaired','donor_crosses_conditions')])
def test_inference_refuses_invalid_independent_units(pairs,mode,reason):
    from app.domain.bio_insights.single_cell_composition import validate_composition_design
    design=validate_composition_design(config(mode),sources(pairs))
    assert not design.executable and reason in {r.code for r in design.blocking_reasons}


def test_multiple_technical_batches_only_block_when_batch_enters_model():
    from app.domain.bio_insights.single_cell_composition import validate_composition_design
    data=sources()
    assert validate_composition_design(config('donor_paired'),data).executable
    for o in data[0]['metadata']['observations']:
        o['donor']=o['condition']+o['donor']
    design=validate_composition_design(config('donor_unpaired',batch_adjustment=True),data)
    assert 'aggregate_batch_not_unique' in {r.code for r in design.blocking_reasons}
    for o in data[0]['metadata']['observations']:o['batch']=o['condition']
    design=validate_composition_design(config('donor_unpaired',batch_adjustment=True),data)
    assert 'rank_deficient_design' in {r.code for r in design.blocking_reasons}


def test_source_mismatch_and_forged_cell_membership_are_blocked():
    from app.domain.bio_insights.single_cell_composition import composition_data,selected_cell_keys
    data=sources();data[1]['metadata']['processed_dataset_version_id']='other'
    with pytest.raises(ValueError,match='annotation_processed_mismatch'):composition_data(config(),data)
    data=sources();data[1]['metadata']['assignments']['rows'].append(dict(barcode='forged',label_id='T',status='assigned'))
    with pytest.raises(ValueError,match='annotation_cell_axis_invalid'):composition_data(config(),data)
    data=sources();selected=selected_cell_keys(config(),data)
    assert len(selected)==6 and ('p','A0-1') not in selected and ('p','A0-2') not in selected


def test_single_cell_donor_resource_estimate_uses_sparse_and_aggregate_blocks():
    from app.domain.bio_insights.design import validate_design
    from tests.numeric.bio_insights_fixtures import config as de_config
    cfg=de_config(n=12000,mode='donor_paired')
    cfg['single_cell_selection']=dict(processed_source_id='p1',annotation_source_id='a',label_ids=['T'],labels_confirmed=True,label_basis='manual')
    observations=[dict(processed_version_id='p1',barcode=f'b{i}',donor=f'd{i%3}',condition='A' if i<6000 else 'B',
        batch='x' if i%2 else 'y',retained=True,library_counts=50) for i in range(12000)]
    features=[dict(processed_version_id='p1',species_taxon_id=9606,namespace='ensembl',reference_version='GRCh38.1',
        canonical_dataset_id='raw',feature_count=30000,common_feature_count=30000,filtered_feature_count=10000,
        counts_nonnegative_integer=True,counts_provenance='raw_gene_expression')]
    preview=validate_design(cfg,observations,features)
    assert preview.executable, [r.code for r in preview.blocking_reasons]
    assert preview.resource_estimate.estimated_working_bytes<2*1024**3

def test_descriptive_single_condition_works_without_donor_metadata():
    from app.domain.bio_insights.single_cell_composition import validate_composition_design
    data=sources()
    for o in data[0]['metadata']['observations']:o['condition']='A';o['donor']=None
    preview=validate_composition_design(config(),data)
    assert preview.executable
    assert preview.actual_units[0].n_numerator==0


def test_old_spatial_design_retains_multi_batch_rejection():
    from app.domain.bio_insights.design import validate_design
    from tests.numeric.bio_insights_fixtures import config as de_config
    cfg=de_config(12,mode='donor_paired')
    observations=[dict(processed_version_id='p1',barcode=f'b{i}',donor=f'd{i%3}',condition='A' if i<6 else 'B',batch=str(i%2),library_counts=10) for i in range(12)]
    features=[dict(processed_version_id='p1',species_taxon_id=9606,namespace='ensembl',reference_version='GRCh38.1',canonical_dataset_id='raw',feature_count=3,counts_nonnegative_integer=True,counts_provenance='raw_gene_expression',filtered_feature_count=3)]
    preview=validate_design(cfg,observations,features)
    assert 'aggregate_batch_not_unique' in {r.code for r in preview.blocking_reasons}

def test_adjustment_requires_multiple_real_batches_before_queueing():
    from app.domain.bio_insights.single_cell_composition import validate_composition_design
    data=sources()
    for o in data[0]['metadata']['observations']:
        o['donor']=o['condition']+o['donor'];o['batch']='only_batch'
    preview=validate_composition_design(config('donor_unpaired',batch_adjustment=True),data)
    assert not preview.executable
    assert 'single_batch_adjustment' in {r.code for r in preview.blocking_reasons}

def test_single_condition_descriptive_contract_accepts_same_condition_but_inference_does_not():
    from app.domain.bio_insights.single_cell_composition_contracts import SingleCellCompositionConfig
    cfg=config();cfg['numerator']='A'
    assert SingleCellCompositionConfig.model_validate(cfg).numerator=='A'
    with pytest.raises(ValueError,match='composition_conditions_equal'):SingleCellCompositionConfig.model_validate({**cfg,'mode':'donor_paired'})

def test_existing_spatial_comparison_wire_omits_absent_single_cell_selection():
    from app.domain.bio_insights.contracts import ComparisonConfig
    from tests.numeric.bio_insights_fixtures import config as de_config
    old=de_config();value=ComparisonConfig.model_validate(old)
    assert 'single_cell_selection' not in value.model_dump(mode='json')
    selected=dict(processed_source_id='p1',annotation_source_id='a',label_ids=['T'],labels_confirmed=True,label_basis='manual')
    assert ComparisonConfig.model_validate({**old,'single_cell_selection':selected}).model_dump(mode='json')['single_cell_selection']==selected
