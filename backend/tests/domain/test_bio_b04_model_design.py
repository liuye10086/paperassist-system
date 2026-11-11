import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def contrast(cid, numerator, denominator, n=2):
    return dict(contrast_id=cid, name=cid, groups=[
        dict(label=label, sample_keys=[dict(processed_version_id='p', sample_id=f'{label}{i}') for i in range(n)])
        for label in (numerator, denominator)
    ])


def bulk_config(contrasts, **changes):
    return dict(kind='comparison', schema_version=2, mode='bulk_counts', design='independent',
        method='deseq2_wald', analysis_layer='raw_counts', bulk_model='shared_wald_v1',
        contrasts=contrasts, family_contrast_ids=[c['contrast_id'] for c in contrasts], namespace='Ensembl',
        reference_version='GRCh38', species_taxon_id=9606, inference_unit='biological',
        inference_goal='inference', independence_confirmed=True, independence_basis='Independent biological units',
        design_basis='Prespecified', data_driven_grouping=False) | changes


def sources(labels, count, paired=False):
    rows = [dict(processed_version_id='p', sample_id=f'{label}{i}', condition=label, retained=True,
                 biological_unit_id=f'donor{i}' if paired else f'{label}{i}', pair_id=f'p{i}' if paired else '',
                 batch=f'b{(j + i) % 2}', age=str(30 + i*i + j), sex='F' if i % 3 == 0 else 'M')
            for j, label in enumerate(labels) for i in range(count)]
    return [dict(source_kind='bio_processed_dataset_version', metadata=dict(
        canonical_dataset_id='raw', assay='bulk_rna_counts', observation_level='sample',
        namespace='Ensembl', reference_version='GRCh38', species_taxon_id=9606, feature_ids=['g'], observations=rows))]


def test_two_biological_repeats_and_two_pairs_are_admitted_with_warning():
    from app.domain.bio_insights.quantitative_design import validate_quantitative_design

    for design in ('independent', 'paired'):
        paired = design == 'paired'
        preview = validate_quantitative_design(bulk_config([contrast('B_A', 'B', 'A')], design=design),
                                              sources('AB', 2, paired=paired))
        assert preview.executable, preview.blocking_reasons
        assert preview.actual_units[0]['complete_pairs'] == (2 if paired else 0)
        assert preview.bulk_model['residual_degrees_freedom'] == (1 if paired else 2)
        assert any('2 个生物学重复' in warning for warning in preview.warnings)
    blocked = validate_quantitative_design(bulk_config([contrast('B_A', 'B', 'A', 1)]), sources('AB', 1))
    assert {reason.code for reason in blocked.blocking_reasons} == {'insufficient_samples'}


def test_legacy_bulk_config_serializes_without_new_model_and_keeps_three_replicate_gate():
    from app.domain.bio_insights.quantitative_contracts import QuantitativeComparisonConfig
    from app.domain.bio_insights.quantitative_design import validate_quantitative_design

    config = bulk_config([contrast('B_A', 'B', 'A')])
    del config['bulk_model']
    assert 'covariates' not in QuantitativeComparisonConfig.model_validate(config).model_dump()
    preview = validate_quantitative_design(config, sources('AB', 2))
    assert not preview.executable
    assert 'bulk_model' not in preview.model_dump()


def test_paired_batch_uses_selected_pair_key_and_blocks_confounded_batch():
    from app.domain.bio_insights.quantitative_design import validate_quantitative_design

    config = bulk_config([contrast('B_A', 'B', 'A', 3)], design='paired', batch_adjustment=True)
    source = sources('AB', 3, paired=True)
    preview = validate_quantitative_design(config, source)
    assert preview.executable, preview.blocking_reasons
    assert preview.bulk_model['formula'] == '~ donor + batch + condition'
    assert preview.bulk_model['terms'][0]['field'] == 'pair_id'
    assert preview.bulk_model['residual_degrees_freedom'] == 1
    for row in source[0]['metadata']['observations']:
        row['batch'] = row['condition']
    assert {r.code for r in validate_quantitative_design(config, source).blocking_reasons} == {'rank_deficient_design'}


@pytest.mark.parametrize('mode,expected', [
    ('valid', None), ('constant', 'covariate_constant'), ('missing', 'covariate_missing'),
    ('invalid', 'covariate_invalid'), ('bad_reference', 'covariate_reference_missing'),
])
def test_bulk_covariates_validate_actual_values_and_reference(mode, expected):
    from app.domain.bio_insights.quantitative_design import validate_quantitative_design

    config = bulk_config([contrast('B_A', 'B', 'A', 4)], condition_reference='B',
        covariates=[dict(field='age', kind='continuous', name='Age'), dict(
            field='sex', kind='categorical', name='Sex', reference_level='X' if mode=='bad_reference' else 'M')])
    source = sources('AB', 4)
    rows = source[0]['metadata']['observations']
    if mode == 'constant':
        for row in rows:
            row['age'] = '30'
    if mode in ('missing','invalid'):
        rows[0]['age'] = '' if mode=='missing' else 'inf'
    preview = validate_quantitative_design(config, source)
    if expected:
        assert expected in {r.code for r in preview.blocking_reasons}
    else:
        assert preview.executable, preview.blocking_reasons
        assert preview.bulk_model['formula'] == '~ covariate_1 + covariate_2 + condition'
        assert preview.bulk_model['terms'][1]['levels'] == ['M', 'F']
        assert preview.bulk_model['condition_reference'] == 'B'


def test_multiple_pairwise_contrasts_share_one_frozen_cohort():
    from app.domain.bio_insights.bulk_model_design import contrast_vectors
    from app.domain.bio_insights.quantitative_design import validate_quantitative_design

    config = bulk_config([contrast('B_A','B','A'),contrast('C_B','C','B'),contrast('A_B','A','B')], design='multiple')
    source = sources('ABC', 2)
    preview = validate_quantitative_design(config, source)
    assert preview.executable, preview.blocking_reasons
    model = preview.bulk_model
    assert model['condition_levels'] == ['A','B','C']
    assert len(model['samples']) == 6
    assert contrast_vectors(model) == {'B_A':[0,1,0], 'C_B':[0,-1,1], 'A_B':[0,-1,0]}

    source[0]['metadata']['observations'][4]['biological_unit_id'] = 'A0'
    assert {r.code for r in validate_quantitative_design(config, source).blocking_reasons} == {'nonindependent_biological_units'}
    config['contrasts'][0]['groups'][0]['sample_keys'].pop()
    assert 'inconsistent_condition_cohort' in {r.code for r in validate_quantitative_design(config, source).blocking_reasons}


def test_repeated_measurement_conditions_share_one_complete_block_model():
    from app.domain.bio_insights.bulk_model_design import contrast_vectors
    from app.domain.bio_insights.quantitative_design import validate_quantitative_design

    contrasts = [contrast('B_A', 'B', 'A', 3), contrast('C_A', 'C', 'A', 3), contrast('C_B', 'C', 'B', 3)]
    preview = validate_quantitative_design(bulk_config(contrasts, design='paired'), sources('ABC', 3, paired=True))
    assert preview.executable, preview.blocking_reasons
    model = preview.bulk_model
    assert model['formula'] == '~ donor + condition'
    assert len(model['samples']) == 9
    assert model['rank'] == 5 and model['residual_degrees_freedom'] == 4
    assert contrast_vectors(model) == {'B_A': [0, 0, 0, 1, 0], 'C_A': [0, 0, 0, 0, 1], 'C_B': [0, 0, 0, -1, 1]}
    assert {unit['complete_pairs'] for unit in preview.actual_units} == {3}


def test_repeated_measurement_model_rejects_disconnected_blocks():
    from app.domain.bio_insights.quantitative_design import validate_quantitative_design

    source = sources('ABCD', 3, paired=True)
    for row in source[0]['metadata']['observations']:
        if row['condition'] in ('C', 'D'):
            row['pair_id'] = 'other_' + row['pair_id']
            row['biological_unit_id'] = 'other_' + row['biological_unit_id']
    config = bulk_config([contrast('B_A', 'B', 'A', 3), contrast('D_C', 'D', 'C', 3)], design='paired')
    preview = validate_quantitative_design(config, source)
    assert not preview.executable
    assert {reason.code for reason in preview.blocking_reasons} == {'incomplete_or_duplicate_pairs'}
