"""Offline subset selection and immutable snapshot checks."""
import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def parent():
    raw=dict(kind='bio_dataset_version',schema_version=1,project_id='p',dataset_id='d',dataset_version_id='raw',version=1,
                source_file_ids=['f'],manifest_sha256='a'*64,parser_version='single_cell_import_v1')
    return dict(kind='bio_processed_dataset_version',schema_version=1,project_id='p',processed_dataset_version_id='processed',
                analysis_run_id='run',raw_source=raw,recipe_version_id='recipe',manifest_sha256='b'*64,
                engine_version='visium_explore_v1.0.0',environment_digest='c'*64)


def test_subset_request_requires_nonempty_explicit_unique_selection():
    from app.domain.bioinformatics.single_cell_contracts import SingleCellSubsetRequest
    from pydantic import ValidationError
    for selectors in [{},{'cell_ids':['c1','c1']},{'cluster_ids':['0','0']}]:
        with pytest.raises(ValidationError):SingleCellSubsetRequest(name='T subset',parent_processed_source=parent(),**selectors)
    value=SingleCellSubsetRequest(name='T subset',parent_processed_source=parent(),cell_ids=['c1'])
    assert value.cell_ids==['c1']


def test_subset_selection_unions_cells_and_clusters_preserves_parent_axis():
    from app.domain.bioinformatics.single_cell_subsets import resolve_selection
    rows=[dict(barcode='c2',kept='True',cluster='1'),dict(barcode='c1',kept='True',cluster='0'),dict(barcode='dropped',kept='False',cluster='0')]
    assert resolve_selection(rows,['0'],['c2'])==['c2','c1']
    from app.core.exceptions import StorageError
    for clusters,cells in [(['bad'],[]),([],['dropped']),([],['unknown'])]:
        with pytest.raises(StorageError):resolve_selection(rows,clusters,cells)


def test_subset_snapshot_rejects_cross_parent_raw_and_out_of_selection_contract():
    from app.domain.bioinformatics.single_cell_contracts import SingleCellSubsetSelection
    from pydantic import ValidationError
    with pytest.raises(ValidationError):SingleCellSubsetSelection(parent_processed_source=parent(),cell_ids=['c1'],resolved_cell_ids=['c1','c1'])
    with pytest.raises(ValidationError):SingleCellSubsetSelection(parent_processed_source=parent(),cell_ids=['c1'],resolved_cell_ids=[])


def test_existing_direct_analysis_snapshot_freezes_subset_parent_and_selection():
    from app.domain.bioinformatics.analysis_contracts import validate_snapshot
    from app.domain.bioinformatics.single_cell_contracts import SingleCellParameters
    from app.domain.bioinformatics.single_cell_resources import analysis_limits_for
    from app.domain.bioinformatics.contracts import digest
    from app.core.exceptions import StorageError
    params=SingleCellParameters().model_dump()
    value=dict(schema_version=1,kind='bio_analysis',workflow_version='bio_analysis_v3',project_id='p',run_id='run',setup_id='setup',recipe_version_id='r',
        expected_setup_revision=1,raw_source=parent()['raw_source'],params=params,observation_map_version_id=None,design_version_id=None,
        engine_version='visium_explore_v1.0.0',environment_digest='c'*64,code_digest='d'*64,output_language='en',
        limits=analysis_limits_for(single_cell=True,params=params).model_dump(),execution_mode='direct',
        subset=dict(parent_processed_source=parent(),cluster_ids=['0'],cell_ids=[],resolved_cell_ids=['c1']))
    def task():return dict(input_snapshot=value,task_type='bio_analysis',workflow_version='bio_analysis_v3',project_id='p',input_digest=digest(value))
    assert validate_snapshot(task())['subset']['resolved_cell_ids']==['c1']
    value['subset']['parent_processed_source']['raw_source']['dataset_version_id']='other'
    with pytest.raises(StorageError):validate_snapshot(task())
