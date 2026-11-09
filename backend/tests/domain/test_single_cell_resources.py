from app.domain.bioinformatics.analysis_settings import BioAnalysisLimits


def test_resource_estimate_counts_csr_and_actual_hvg_dense_blocks():
    from app.domain.bioinformatics.single_cell_resources import resource_estimate
    manifest=dict(input_shape=dict(observations=15000,features=30000),stored_entries=1000000)
    result=resource_estimate(manifest,dict(hvg_count=1000))
    assert result['matrix']==dict(observations=15000,features=30000,nnz=1000000)
    assert result['sparse_bytes']==1000000*12+15001*8
    assert result['dense_hvg_bytes']==15000*1000*4
    assert result['dense_hvg_values']==15000000
    assert result['configured_limits']==BioAnalysisLimits().model_dump()
    assert result['estimate_only'] is True and result['blockers']==[]
    assert result['peak_memory_bytes'] is None
    assert 'embedded R' in result['basis']['excludes'] and 'correction' in result['basis']['excludes']
    assert resource_estimate(manifest,dict(hvg_count=2000))['blockers']==['single_cell_dense_hvg_limit']


def test_resource_estimate_identifies_every_existing_matrix_limit():
    from app.domain.bioinformatics.single_cell_resources import resource_estimate
    result=resource_estimate(dict(input_shape=dict(observations=20001,features=100001),stored_entries=10000001),dict(hvg_count=3))
    assert set(result['blockers'])=={'single_cell_observations_limit','single_cell_features_limit','single_cell_nnz_limit'}
    capped=resource_estimate(dict(input_shape=dict(observations=10,features=5),stored_entries=8),dict(hvg_count=2000))
    assert capped['hvg_count']==5 and capped['dense_hvg_values']==50


def test_r_runtime_is_not_required_for_inapplicable_harmony():
    from app.domain.bioinformatics.single_cell_resources import requires_r_runtime
    payload = {'raw': {'manifest': {'assay': 'single_cell', 'samples': []}},
               'config': {'harmony': {'enabled': True}}}
    assert requires_r_runtime(mode='compute', payload=payload) is False


def test_r_runtime_is_required_for_enabled_qc_tools_or_multiple_batches():
    from app.domain.bioinformatics.single_cell_resources import requires_r_runtime
    base = {'raw': {'manifest': {'assay': 'single_cell', 'samples': []}}, 'config': {}}
    assert requires_r_runtime(mode='compute', payload={**base, 'config': {'doublet': {'enabled': True}}}) is True
    batched = {'raw': {'manifest': {'assay': 'single_cell', 'samples': [{'batch': 'A'}, {'batch': 'B'}]}},
               'config': {'harmony': {'enabled': True}}}
    assert requires_r_runtime(mode='compute', payload=batched) is True
