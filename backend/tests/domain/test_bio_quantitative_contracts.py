import pytest
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def postgres_schema():yield None


def config(technical=False):
    return dict(kind='comparison',schema_version=2,mode='continuous',design='independent',method='welch_t',analysis_layer='analysis',
        contrasts=[dict(contrast_id='B_A',name='B versus A',groups=[dict(label=g,sample_keys=[dict(processed_version_id='p',sample_id=g+str(i)) for i in range(3)]) for g in ('B','A')])],
        family_contrast_ids=['B_A'],namespace='protein_label',reference_version='fixed',species_taxon_id=None,
        inference_unit='technical' if technical else 'biological',independence_confirmed=not technical,independence_basis='' if technical else 'Independent units confirmed',
        technical_exploration_confirmed=technical,design_basis='Fixed study design',inference_goal='exploratory' if technical else 'inference',data_driven_grouping=False)


def sources(technical=False):
    return [dict(source_kind='bio_processed_dataset_version',source_id='p',metadata=dict(canonical_dataset_id='raw-p',assay='proteomics',observation_level='sample',
        namespace='protein_label',reference_version='fixed',species_taxon_id=None,feature_ids=['a','b'],
        layers={'analysis':{'scale':'intensity','unit':'AU','normalization':'none','transform':'none','input_scale':{'kind':'intensity'}}},
        observations=[dict(processed_version_id='p',sample_id=g+str(i),condition=g,retained=True,sample_role='technical' if technical else 'biological',
            biological_unit_id='' if technical else g+str(i),pair_id='pair'+str(i),donor='' if technical else g+str(i),batch='batch1') for g in ('B','A') for i in range(3)]))]


def test_v2_plan_and_exact_task_version_accept_sample_keys():
    from app.domain.bio_insights.contracts import InsightPlanRequest
    from app.domain.bio_insights.task_contracts import InsightTaskSnapshot
    plan=InsightPlanRequest.model_validate(dict(name='test',kind='comparison',expected_revision=0,config=config(),sources=[dict(source_kind='bio_processed_dataset_version',source_id='p',sha256='a'*64,role='processed')]))
    assert plan.config.schema_version==2 and plan.config.contrasts[0].groups[0].sample_keys[0].sample_id=='B0'
    task=InsightTaskSnapshot(kind='bio_comparison',workflow_version='bio_comparison_v2',project_id='p',plan_version_id='v',run_id='r',source_digest='a'*64)
    assert task.workflow_version=='bio_comparison_v2'
    with pytest.raises(ValidationError):InsightTaskSnapshot(kind='bio_candidate',workflow_version='bio_candidate_v2',project_id='p',plan_version_id='v',run_id='r',source_digest='a'*64)


def test_technical_scope_requires_explicit_confirmation_and_has_zero_biological_n():
    from app.domain.bio_insights.quantitative_design import validate_quantitative_design
    c=config(True);preview=validate_quantitative_design(c,sources(True))
    assert preview.executable and preview.actual_units[0]['inference_scope']=='sample_exploratory'
    assert preview.actual_units[0]['biological_n']==0
    c['technical_exploration_confirmed']=False
    assert not validate_quantitative_design(c,sources(True)).executable


def test_biological_checkbox_cannot_promote_technical_runs():
    from app.domain.bio_insights.quantitative_design import validate_quantitative_design
    assert not validate_quantitative_design(config(),sources(True)).executable


def test_paired_and_batch_design_reject_incomplete_or_confounded_units():
    from app.domain.bio_insights.quantitative_design import validate_quantitative_design
    c=config();c.update(design='paired',method='paired_t')
    assert validate_quantitative_design(c,sources()).executable
    s=sources();s[0]['metadata']['observations'][0]['pair_id']='missing'
    assert not validate_quantitative_design(c,s).executable
    c.update(mode='bulk_counts',method='deseq2_wald',analysis_layer='raw_counts',design='independent',batch_adjustment=True)
    s=sources();s[0]['metadata']['assay']='bulk_rna_counts'
    for row in s[0]['metadata']['observations']:row['batch']=row['condition']
    assert not validate_quantitative_design(c,s).executable


def test_predeclared_family_and_method_cannot_be_silently_changed():
    from app.domain.bio_insights.quantitative_contracts import QuantitativeComparisonConfig
    c=config();c['family_contrast_ids']=[]
    with pytest.raises(ValidationError):QuantitativeComparisonConfig.model_validate(c)
    c=config();c['design']='paired'
    with pytest.raises(ValidationError):QuantitativeComparisonConfig.model_validate(c)


def test_distinct_pair_labels_cannot_hide_repeated_biological_units():
    from app.domain.bio_insights.quantitative_design import validate_quantitative_design
    c=config();c.update(design='paired',method='paired_t')
    s=sources();s[0]['metadata']['observations'][1]['biological_unit_id']='B0'
    assert not validate_quantitative_design(c,s).executable

def test_database_snapshot_check_whitelists_only_comparison_v2():
    from app.db.schema import metadata
    constraint=next(c for c in metadata.tables['tasks'].constraints if c.name=='b04_tasks_snapshot_check')
    sql=str(constraint.sqltext)
    assert "task_type='bio_comparison' AND workflow_version IN ('bio_comparison_v2','bio_comparison_qpcr_v1','bio_comparison_microbiome_v1')" in sql
    assert "workflow_version=task_type||'_v1'" in sql
    assert "input_snapshot->'real_network_calls'='false'::jsonb" in sql
