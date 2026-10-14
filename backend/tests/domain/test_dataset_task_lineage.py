"""Dataset task lineage must survive strict parsing and external confirmation."""
import copy
import pytest
from pydantic import ValidationError
from app.core.exceptions import StorageError
from app.domain.tasks.wait_contracts import ResumeRequest
from app.domain.tasks.waits import input_version
from app.domain.external_processing import disclosure, freeze_confirmation, source_digest


def source():
    return dict(kind='dataset_version', schema_version=1, dataset_id='dataset', structure_id='structure',
                dataset_version=1, file_id='file', source_sha256='a'*64, dataset_sha256='b'*64,
                dataset_size_bytes=123, dataset_schema_version=1, sheet_index=0, sheet_name='Sheet1', parser_version='openpyxl-3.1.5-structure-v1')


def snapshot():
    result = dict(setup_revision=3, numeric_name='值', group_name=None, groups=[],
                  selection={'unit':'kg'}, check={'valid_count':2,'excluded_count':0}, source=source())
    return dict(schema_version=2, source=source(), file={'filename':'sample.xlsx'}, result=result,
                figure=None, versions={}, output_language='zh-CN')


def test_dataset_input_version_survives_resume_and_rejects_unknown_fields():
    task = {'task_type':'boxplot', 'input_snapshot':snapshot()}
    version = input_version(task)
    assert version == dict(kind='dataset_analysis', setup_revision=3, output_language='zh-CN', source=source())
    request = dict(operation='retry', wait_id=None, expected_task_revision=4, input_version=version)
    assert ResumeRequest.model_validate(request).model_dump()['input_version'] == version
    for extra in ({'unknown':1}, {'source':{**source(), 'object_key':'private'}}):
        with pytest.raises(ValidationError):
            ResumeRequest.model_validate({**request, 'input_version':{**version, **extra}})


def test_dataset_disclosure_binds_readable_source_and_complete_identity():
    frozen = snapshot()
    preview = disclosure(frozen, 'boxplot', 'owner')
    assert preview['version'] == 2
    assert preview['source'] == {'filename':'sample.xlsx','sheet_name':'Sheet1','dataset_version':1}
    altered = copy.deepcopy(frozen)
    altered['source']['dataset_id'] = 'other'
    assert source_digest(altered,'boxplot','owner') != preview['source_digest']
    confirmation = dict(version=2, confirmed=True, source_digest=preview['source_digest'],
                        labels={item['key']:item['value'] for item in preview['labels']})
    assert freeze_confirmation(frozen,'boxplot','owner',confirmation)['version'] == 2
    with pytest.raises(StorageError):
        freeze_confirmation(frozen,'boxplot','owner',{**confirmation,'version':1})


def test_legacy_disclosure_and_input_version_do_not_add_source():
    frozen = snapshot()
    frozen.pop('source'); frozen['result'].pop('source'); frozen['schema_version']=1
    assert input_version({'task_type':'boxplot','input_snapshot':frozen}) == {'setup_revision':3,'output_language':'zh-CN'}
    preview=disclosure(frozen,'boxplot','owner')
    assert preview['version']==1 and 'source' not in preview

def test_snapshot_comparison_rejects_top_level_source_switch():
    from app.adapters.task_store import snapshots_match
    original=snapshot()
    current=copy.deepcopy(original)
    current['source']['dataset_id']='other'
    assert not snapshots_match(current,original)
    assert not snapshots_match({k:v for k,v in original.items() if k!='source'},original)


def test_workspace_projection_keeps_dataset_source_and_legacy_omits_it():
    from app.domain.tasks.workspace_contracts import TaskSource
    value=dict(file_id='file',filename='sample.xlsx',analysis_run_id='run',is_current=True,dataset_source=source())
    assert TaskSource.model_validate(value).model_dump()['dataset_source']==source()
    legacy={k:v for k,v in value.items() if k!='dataset_source'}
    assert 'dataset_source' not in TaskSource.model_validate(legacy).model_dump()

def test_dataset_external_material_accepts_v2_without_changing_instructions():
    from app.domain.external_material import contract_labels, plot_instructions, PLOT_INSTRUCTIONS
    frozen=snapshot(); preview=disclosure(frozen,'boxplot','owner')
    confirmation=dict(version=2,confirmed=True,source_digest=preview['source_digest'],
        labels={item['key']:item['value'] for item in preview['labels']})
    external=freeze_confirmation(frozen,'boxplot','owner',confirmation)
    assert contract_labels(frozen['result'],None,external,'boxplot')==confirmation['labels']
    assert plot_instructions(external)==PLOT_INSTRUCTIONS
    with pytest.raises(StorageError):
        contract_labels(frozen['result'],None,{**external,'version':1},'boxplot')

@pytest.mark.parametrize('tamper',['source','digest'])
def test_workspace_report_rejects_saved_input_top_level_source_or_digest(tamper):
    from app.domain.tasks.workspace import TaskWorkspaceService
    from app.adapters.report_store import digest
    import json
    frozen=snapshot(); frozen['file']['id']='file'; frozen['file']['sha256']='a'*64
    frozen['result']['id']='run'; frozen['result']['source_sha256']='a'*64
    frozen['figure']={'id':'figure','sha256':'d'*64}
    frozen['explanation']={'id':'explanation'}
    saved_input=copy.deepcopy(frozen)
    if tamper=='source': saved_input['source']['dataset_id']='other'
    report=dict(id='report',analysis_run_id='run',source_sha256='a'*64,setup_revision=3,source=source(),
                explanation_id='explanation',figure_id='figure',figure_sha256='d'*64,input_sha256=digest(saved_input))
    if tamper=='digest': report['input_sha256']='e'*64
    row=dict(source_file_id='file',explanation_id='explanation',report_json=json.dumps(report),input_json=json.dumps(saved_input))
    class Result:
        def fetchone(self): return row
    class DB:
        def execute(self,*args): return Result()
    task=dict(input_snapshot=frozen,result_report_id='report')
    with pytest.raises(StorageError) as error:
        TaskWorkspaceService('owner')._saved_artifact(DB(),task,'report')
    assert error.value.code=='task_source_conflict'

def test_matching_task_source_requires_complete_frozen_identity():
    from app.adapters.task_store import task_source_matches
    expected=snapshot(); task={'input_snapshot':copy.deepcopy(expected)}
    assert task_source_matches(task,expected['result'])
    task['input_snapshot']['source']['dataset_sha256']='c'*64
    assert not task_source_matches(task,expected['result'])
    task['input_snapshot']=copy.deepcopy(expected)
    task['input_snapshot']['result']['source']['dataset_id']='other'
    assert not task_source_matches(task,expected['result'])

@pytest.mark.parametrize('kind',['plot','explanation'])
def test_dataset_material_refuses_unconfirmed_source(kind, monkeypatch):
    from app.domain.external_material import plot_material, explanation_material
    monkeypatch.setattr('app.domain.external_material.build_payload', lambda *args: {'bounded': True})
    with pytest.raises(StorageError) as error:
        if kind=='plot': plot_material(snapshot()['result'],{}, {},None)
        else: explanation_material(snapshot()['result'],{},None)
    assert error.value.code=='task_source_conflict'

@pytest.mark.parametrize('tamper',['missing_source','different_source','schema'])
def test_task_input_projection_rejects_incoherent_snapshot_source(tamper):
    task={'task_type':'boxplot','input_snapshot':snapshot()}
    if tamper=='missing_source': task['input_snapshot'].pop('source')
    elif tamper=='different_source': task['input_snapshot']['source']['dataset_id']='other'
    else: task['input_snapshot']['schema_version']=1
    with pytest.raises(StorageError) as error:
        input_version(task)
    assert error.value.code=='task_source_conflict'

def test_task_input_projection_rejects_invalid_source_with_safe_error():
    task={'task_type':'boxplot','input_snapshot':snapshot()}
    task['input_snapshot']['source']['object_key']='private'
    task['input_snapshot']['result']['source']=copy.deepcopy(task['input_snapshot']['source'])
    with pytest.raises(StorageError) as error:
        input_version(task)
    assert error.value.code=='task_source_conflict'
