import hashlib
import pytest
from app.core.exceptions import StorageError
from app.adapters import bio_analysis_process as parent


def fixture(root):
    records=[]
    for key in ('one','two'):
        path=root/(key+'.txt');path.write_bytes(b'abc')
        records.append(dict(key=key,format='txt',role=key,path=str(path.resolve()),size_bytes=3,sha256=hashlib.sha256(b'abc').hexdigest()))
    return records


def test_parent_applies_explicit_aggregate_limit_without_relaxing_leaf_checks(tmp_path):
    records=fixture(tmp_path)
    assert parent.validate_artifacts(records,tmp_path,max_output_bytes=6)==records
    with pytest.raises(StorageError):parent.validate_artifacts(records,tmp_path,max_output_bytes=5)
    changed=[{**records[0],'size_bytes':256*1024**2+1},records[1]]
    with pytest.raises(StorageError):parent.validate_artifacts(changed,tmp_path,max_output_bytes=1024**3)


@pytest.mark.parametrize('budget',[512*1024**2,1024**3])
def test_result_validator_forwards_trusted_parent_budget(tmp_path,monkeypatch,budget):
    records=fixture(tmp_path);observed=[];validate=parent.validate_artifacts
    def tracked(outputs,directory,**kwargs):
        observed.append(kwargs['max_output_bytes']);return validate(outputs,directory,**kwargs)
    monkeypatch.setattr(parent,'validate_artifacts',tracked)
    result=dict(engine_version=parent.ENGINE_VERSION,status='completed',manifest={},summary={},steps=[],outputs=records)
    assert parent.validate_engine_result(result,tmp_path,mode='figure',max_output_bytes=budget)==result
    assert observed==[budget]


@pytest.mark.parametrize('workflow,task_type,enabled,accepted',[
    ('bio_analysis_v3','bio_analysis',True,True),
    ('bio_analysis_v3','bio_analysis',False,False),
    ('bio_analysis_v1','bio_analysis',True,False),
    ('bio_figure_v1','bio_figure',True,False),
])
def test_publish_staging_uses_same_scoped_output_budget(tmp_path,monkeypatch,workflow,task_type,enabled,accepted):
    from app.adapters import bio_analysis_execution as execution
    from app.domain.bioinformatics.single_cell_resources import analysis_limits_for
    from uuid import uuid4
    def small_budget(**kwargs):
        selected=analysis_limits_for(**kwargs)
        return selected.model_copy(update={'max_output_bytes':6 if selected.max_output_bytes==1024**3 else 5})
    monkeypatch.setattr(execution,'analysis_limits_for',small_budget,raising=False)
    identifier=str(uuid4())
    snapshot=dict(workflow_version=workflow,params=dict(decontx=dict(enabled=enabled)),**({'run_id':identifier} if task_type=='bio_analysis' else {'figure_version_id':identifier}))
    task=dict(task_type=task_type,input_snapshot=snapshot,input_digest='a'*64)
    class Objects:
        prefix='fixture'
        def path(self,key):return tmp_path/key
    result=dict(outputs=fixture(tmp_path),manifest={})
    if accepted:assert len(execution.build_candidate(task,result,Objects(),'compute')[0]['members'])==2
    else:
        with pytest.raises(StorageError) as failure:execution.build_candidate(task,result,Objects(),'compute')
        assert failure.value.code=='bio_resource_exceeded'
