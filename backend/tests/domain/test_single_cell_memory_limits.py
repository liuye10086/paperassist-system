import pytest
from app.domain.bioinformatics.analysis_settings import BioAnalysisLimits


@pytest.mark.parametrize('single_cell,params,memory,space',[
    (False,{},2,3),(False,{'decontx':{'enabled':True}},2,3),
    (True,{},2,3),(True,{'doublet':{'enabled':False}},2,3),
    (True,{'doublet':{'enabled':True}},4,5),(True,{'decontx':{'enabled':True}},4,5),
])
def test_r_budget_is_bounded_and_only_applies_to_enabled_single_cell(single_cell,params,memory,space):
    from app.domain.bioinformatics.single_cell_resources import analysis_limits_for,memory_bounds
    limits=analysis_limits_for(single_cell=single_cell,params=params)
    assert limits.memory_bytes==memory*1024**3
    assert memory_bounds(single_cell=single_cell,params=params)==dict(rss_limit_bytes=memory*1024**3,address_space_limit_bytes=space*1024**3)
    assert limits.max_dense_values==BioAnalysisLimits().max_dense_values
    assert limits.max_output_bytes==(1024**3 if memory==4 else 512*1024**2)


def test_estimate_exposes_actual_selected_and_optional_r_budget():
    from app.domain.bioinformatics.single_cell_resources import resource_estimate
    manifest=dict(input_shape=dict(observations=2700,features=30000),stored_entries=1000000)
    baseline=resource_estimate(manifest)
    assert baseline['configured_limits']['memory_bytes']==2*1024**3
    assert baseline['optional_r_limits']['memory_bytes']==4*1024**3
    assert baseline['optional_r_limits']['max_output_bytes']==1024**3
    actual=resource_estimate(manifest,dict(decontx=dict(enabled=True)))
    assert actual['configured_limits']['memory_bytes']==4*1024**3


@pytest.mark.parametrize('enabled,memory,output_mib,accepted',[(True,4,1024,True),(False,4,1024,False),(True,3,1024,False),(True,2,1024,False),(True,4,512,False)])
def test_frozen_single_cell_limits_only_allow_r_budget_with_enabled_tools(enabled,memory,output_mib,accepted):
    from app.domain.bioinformatics.analysis_contracts import validate_snapshot
    from app.domain.bioinformatics.contracts import digest
    from app.core.exceptions import StorageError
    source=dict(kind='bio_dataset_version',schema_version=1,project_id='p',dataset_id='d',dataset_version_id='v',version=1,manifest_sha256='a'*64,parser_version='single_cell_import_v1',source_file_ids=['f'])
    limits={**BioAnalysisLimits().model_dump(),'memory_bytes':memory*1024**3,'max_output_bytes':output_mib*1024**2}
    value=dict(schema_version=1,kind='bio_analysis',workflow_version='bio_analysis_v3',project_id='p',run_id='r',setup_id='s',recipe_version_id='q',expected_setup_revision=1,raw_source=source,
        params=dict(decontx=dict(enabled=enabled)),observation_map_version_id=None,design_version_id=None,engine_version='visium_explore_v1.0.0',environment_digest='b'*64,code_digest='c'*64,output_language='en',limits=limits)
    task=dict(task_type='bio_analysis',workflow_version='bio_analysis_v3',project_id='p',input_snapshot=value,input_digest=digest(value))
    if accepted:assert validate_snapshot(task)==value
    else:
        with pytest.raises(StorageError):validate_snapshot(task)
