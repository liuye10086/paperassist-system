import importlib.util
import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def api():
    assert importlib.util.find_spec('app.domain.bio_insights'), 'bio insight design missing'
    return __import__('app.domain.bio_insights.design',fromlist=['validate_design'])


def fixture(mode='donor_unpaired'):
    observations=[]
    keys=[[],[]]
    for group in range(2):
        for i in range(3):
            key=dict(processed_version_id='p',barcode=f'{group}-{i}')
            keys[group].append(key)
            observations.append({**key,'donor':f'd{i}' if mode=='donor_paired' else f'd{group}{i}',
                                 'condition':'A' if group==0 else 'B','batch':f'b{i%2}','library_counts':20})
    config=dict(kind='comparison',mode=mode,contrasts=[dict(contrast_id='c',name='A/B',
                numerator=dict(label='A',observation_keys=keys[0]),denominator=dict(label='B',observation_keys=keys[1]))],
                family_contrast_ids=['c'],species_taxon_id=9606,namespace='ensembl_gene',reference_version='v1',
                mapping_confirmed=True,independence_confirmed=True,independence_basis='confirmed donor registry')
    features=[dict(processed_version_id='p',species_taxon_id=9606,namespace='ensembl_gene',reference_version='v1',
                   canonical_dataset_id='dataset',feature_count=100,counts_nonnegative_integer=True,
                   counts_provenance='raw_gene_expression',filtered_feature_count=100)]
    return config,observations,features


def test_valid_unpaired_counts_donors_not_fragments():
    c,o,f=fixture()
    preview=api().validate_design(c,o,f)
    assert preview.executable
    assert preview.actual_units[0].n_numerator==3
    assert preview.actual_units[0].n_denominator==3
    assert preview.family==['c']
    extra={**o[0],'barcode':'technical-fragment'}
    c['contrasts'][0]['numerator']['observation_keys'].append({k:extra[k] for k in ('processed_version_id','barcode')})
    preview=api().validate_design(c,o+[extra],f)
    assert preview.actual_units[0].n_numerator==3
    assert preview.actual_units[0].spots_numerator==4


@pytest.mark.parametrize('problem,reason',[
    ('missing_donor','donor_missing'),('cross_condition','donor_crosses_conditions'),
    ('small_group','insufficient_donors'),('overlap','overlapping_groups'),
    ('batch_confounding','rank_deficient_design'),('bad_counts','counts_not_raw_integer'),
    ('species','incompatible_feature_metadata'),('duplicate_source','duplicate_canonical_dataset')])
def test_invalid_design_is_blocked_with_specific_reason(problem,reason):
    c,o,f=fixture()
    if problem=='missing_donor':o[0]['donor']=None
    if problem=='cross_condition':o[3]['donor']=o[0]['donor']
    if problem=='small_group':c['contrasts'][0]['numerator']['observation_keys'].pop()
    if problem=='overlap':c['contrasts'][0]['denominator']['observation_keys'].append(c['contrasts'][0]['numerator']['observation_keys'][0])
    if problem=='batch_confounding':
        c['batch_adjustment']=True
        for item in o:item['batch']=item['condition']
    if problem=='bad_counts':f[0]['counts_nonnegative_integer']=False
    if problem=='species':f[0]['species_taxon_id']=10090
    if problem=='duplicate_source':f.append({**f[0],'processed_version_id':'alternate'})
    preview=api().validate_design(c,o,f)
    assert not preview.executable
    assert reason in {r.code for r in preview.blocking_reasons}


def test_pairing_exclusion_is_explicit_and_requires_three_complete_pairs():
    c,o,f=fixture('donor_paired')
    assert api().validate_design(c,o,f).executable
    o[3]['donor']='unpaired'
    preview=api().validate_design(c,o,f)
    assert 'incomplete_pairs' in {r.code for r in preview.blocking_reasons}


def test_exploration_does_not_claim_independent_donors_or_require_counts():
    c,o,f=fixture('spot_exploratory')
    c['mapping_confirmed']=False;c['independence_confirmed']=False
    for item in o:item['donor']=None
    f[0]['counts_nonnegative_integer']=False
    preview=api().validate_design(c,o,f)
    assert preview.executable
    assert preview.actual_units[0].observation_level=='spot'
    assert preview.warnings


@pytest.mark.parametrize('problem,reason',[
    ('unknown','unknown_observation'),('zero_library','zero_library'),
    ('mapping','mapping_unconfirmed'),('independence','independence_unconfirmed'),
    ('no_features','no_features_after_filter'),('batch_nonunique','aggregate_batch_not_unique'),
    ('condition_nonunique','aggregate_condition_not_unique'),('duplicate_key','duplicate_observation_key'),
    ('metadata_missing','missing_feature_metadata'),('budget','resource_budget_exceeded')])
def test_design_submission_checks_metadata_and_budgets(problem,reason):
    c,o,f=fixture()
    if problem=='unknown':c['contrasts'][0]['numerator']['observation_keys'][0]['barcode']='unknown'
    if problem=='zero_library':o[0]['library_counts']=0
    if problem=='mapping':c['mapping_confirmed']=False
    if problem=='independence':c['independence_basis']=''
    if problem=='no_features':f[0]['filtered_feature_count']=0
    if problem in ('batch_nonunique','condition_nonunique'):
        c['batch_adjustment']=problem=='batch_nonunique'
        extra={**o[0],'barcode':'fragment','batch':'different','condition':'different'}
        o.append(extra)
        c['contrasts'][0]['numerator']['observation_keys'].append({k:extra[k] for k in ('processed_version_id','barcode')})
    if problem=='duplicate_key':o.append(dict(o[0]))
    if problem=='metadata_missing':f=[]
    if problem=='budget':f[0]['feature_count']=10000000
    preview=api().validate_design(c,o,f)
    assert not preview.executable
    assert reason in {r.code for r in preview.blocking_reasons}


def test_explicit_incomplete_donor_exclusion_leaves_three_pairs_and_audit_rows():
    c,o,f=fixture('donor_paired')
    extra={**o[0],'barcode':'incomplete','donor':'excluded'}
    o.append(extra)
    c['contrasts'][0]['numerator']['observation_keys'].append({k:extra[k] for k in ('processed_version_id','barcode')})
    assert not api().validate_design(c,o,f).executable
    c['excluded_donors']=[{'donor':'excluded','reason':'incomplete pair explicitly excluded'}]
    preview=api().validate_design(c,o,f)
    assert preview.executable
    assert preview.actual_units[0].complete_pairs==3
    assert preview.exclusions[0].reason=='incomplete pair explicitly excluded'


def test_multiple_datasets_never_merge_same_barcode_and_require_common_stable_axis():
    c,o,f=fixture('spot_exploratory')
    extra={**o[0],'processed_version_id':'other'}
    o.append(extra)
    c['contrasts'][0]['numerator']['observation_keys'].append({k:extra[k] for k in ('processed_version_id','barcode')})
    f.append({**f[0],'processed_version_id':'other','canonical_dataset_id':'different'})
    assert 'common_feature_axis_unverified' in {r.code for r in api().validate_design(c,o,f).blocking_reasons}
    for item in f:item['common_feature_count']=80
    preview=api().validate_design(c,o,f)
    assert preview.executable
    assert preview.actual_units[0].spots_numerator==4
    assert preview.resource_estimate.features==80


def test_pure_design_has_no_numeric_import_and_services_add_none_beyond_legacy_store():
    import subprocess
    import sys
    result=subprocess.run([sys.executable,'-c',
        "import sys; import app.domain.bio_insights.design; import app.domain.bio_insights.task_contracts; "
        "numeric={'numpy','scipy','pandas','pydeseq2','gseapy'}; "
        "assert not any(k.split('.')[0] in numeric for k in sys.modules); "
        "import app.adapters.task_store; baseline={k.split('.')[0] for k in sys.modules if k.split('.')[0] in numeric}; "
        "import app.domain.bio_insights.service; import app.domain.bio_insights.resources; import app.domain.bio_insights.uploads; "
        "assert {k.split('.')[0] for k in sys.modules if k.split('.')[0] in numeric}==baseline"],
        cwd=__import__('pathlib').Path(__file__).resolve().parents[2],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_aggregate_batch_uniqueness_is_checked_even_without_batch_model_term():
    c,o,f=fixture()
    extra={**o[0],'barcode':'fragment','batch':'incompatible_batch'}
    o.append(extra)
    c['contrasts'][0]['numerator']['observation_keys'].append({k:extra[k] for k in ('processed_version_id','barcode')})
    assert 'aggregate_batch_not_unique' in {r.code for r in api().validate_design(c,o,f).blocking_reasons}


def test_donor_condition_must_match_frozen_group_labels_before_execution():
    c,o,f=fixture()
    c['contrasts'][0]['numerator']['label']='CASE'
    preview=api().validate_design(c,o,f)
    assert not preview.executable
    assert 'condition_group_mismatch' in {r.code for r in preview.blocking_reasons}


def test_different_donors_on_same_side_cannot_have_different_conditions():
    c,o,f=fixture()
    o[1]['condition']='other'
    preview=api().validate_design(c,o,f)
    assert not preview.executable
    assert 'condition_group_mismatch' in {r.code for r in preview.blocking_reasons}
