import pytest
from pydantic import ValidationError


def test_new_defaults_do_not_enable_historical_replay():
    from app.domain.bioinformatics import single_cell_contracts as c
    old=c.SingleCellParameters.model_validate({})
    assert getattr(old,'hvg_batch_key','missing') is None
    assert old.technical_covariates==[] and old.harmony.enabled is False
    new=c.new_single_cell_parameters()
    assert new.hvg_batch_key=='batch' and new.technical_covariates==['log1p_total_counts']
    assert new.harmony.model_dump(by_alias=True)==dict(enabled=True,batch_key='batch',theta=2,**{'lambda':1},max_iter=10)
    assert c.SingleCellSetupRequest.model_fields['params'].default_factory()==new


@pytest.mark.parametrize('params',[
    {'technical_covariates':['group']},{'technical_covariates':['mt_fraction','mt_fraction']},
    {'harmony':{'theta':float('inf')}},{'harmony':{'lambda':0}},{'harmony':{'max_iter':101}},
])
def test_invalid_integration_parameters_rejected(params):
    from app.domain.bioinformatics.single_cell_contracts import SingleCellParameters
    with pytest.raises(ValidationError):SingleCellParameters.model_validate(params)


def test_harmony_uses_existing_r_budget_only_for_single_cell():
    from app.domain.bioinformatics.single_cell_resources import analysis_limits_for,memory_bounds
    params={'harmony':{'enabled':True}}
    assert analysis_limits_for(single_cell=True,params=params).memory_bytes==4*1024**3
    assert memory_bounds(single_cell=True,params=params)['address_space_limit_bytes']==5*1024**3
    assert analysis_limits_for(single_cell=False,params=params).memory_bytes==2*1024**3


def test_partial_new_request_defaults_and_serialized_lambda_roundtrip():
    from app.domain.bioinformatics.single_cell_contracts import SingleCellSetupRequest,SingleCellParameters
    from app.domain.bioinformatics.contracts import BioDatasetSourceV1
    raw=BioDatasetSourceV1(project_id='p',dataset_id='d',dataset_version_id='v',manifest_sha256='a'*64,version=1,parser_version='single_cell_import_v1',source_file_ids=['f'])
    request=SingleCellSetupRequest(name='new',raw_source=raw,expected_revision=0,recipe_code='single_cell_explore_v1',params={'min_counts':2})
    assert request.params.harmony.enabled is True and request.params.technical_covariates==['log1p_total_counts']
    assert 'lambda' in request.params.model_dump()['harmony']
    assert SingleCellParameters.model_validate(request.params.model_dump())==request.params
    edited=SingleCellSetupRequest(**{**request.model_dump(),'expected_revision':2,'params':{'min_counts':3}})
    assert edited.params.harmony.enabled is False and edited.params.technical_covariates==[]

def test_report_describes_requested_applied_and_scientific_boundary():
    import io
    from docx import Document
    from app.adapters.single_cell_report import build_single_cell_report
    state=dict(hvg=dict(strategy='global_seurat',fallback_reason='single_batch'),
        technical_covariates=dict(status='completed',requested=['log1p_total_counts'],applied=True,columns=['log1p_total_counts'],reason=None),
        harmony=dict(status='not_computable',requested=True,applied=False,batch_key='batch',reason='single_batch'),
        design=dict(status='not_computable',reason='single_batch'),downstream_representation='X_pca',versions={'scanpy':'1.11.1'},
        diagnostics=[dict(representation='X_pca',status='completed',sampled_cells=80,dimensions=6,batch_silhouette=.12,knn_cross_batch_fraction=.4)])
    for language in ('en','zh-CN'):
        content=build_single_cell_report('p','i','a'*64,dict(summary={'single_cell_integration':state},params={},steps=[]),{},[],language)
        doc=Document(io.BytesIO(content));text='\n'.join(p.text for p in doc.paragraphs)
        assert 'Harmony' in text and 'X_pca' in text and 'single_batch' in text and 'log1p_total_counts' in text
        assert 'requested=None' not in text and 'applied=None' not in text
        if language=='zh-CN':
            assert '单批次' in text and '已应用' in text and '抽样细胞' in text and '异批邻居比例' in text
        assert '"sampled_cells"' not in text


@pytest.mark.parametrize('prefix',['integration_covariates','integration_harmony'])
def test_integration_default_figure_publication_preserves_kind(monkeypatch,prefix):
    import json
    from uuid import uuid4
    from app.adapters import bio_figure_store as module
    inserted=[]
    monkeypatch.setattr(module,'insert',lambda db,table,row:inserted.append((table,row)))
    monkeypatch.setattr(module,'object_by_key',lambda *args:dict(id='object',sha256='a'*64))
    store=module.BioFigureStore.__new__(module.BioFigureStore)
    class Objects:
        def read(self,member):return json.dumps(dict(config=dict(kind=prefix),dpi=300,width_inches=8,height_inches=4)).encode()
    store.objects=Objects()
    members=[dict(key=prefix+'_'+suffix,format=fmt,size_bytes=2,sha256='a'*64) for suffix,fmt in [('png','png'),('data','json'),('manifest','json')]]
    store.publish_defaults(None,dict(project_id='p',user_id='u',id='task'),str(uuid4()),dict(manifest={},members=members))
    version=next(row for table,row in inserted if table=='bio_figure_versions')
    assert version['config_json']['kind']==prefix
    assert len([row for table,row in inserted if table=='bio_figure_members'])==3


@pytest.mark.parametrize('key',['technical_covariates','harmony'])
def test_parent_allows_recorded_adjustment_failure_without_relaxing_other_steps(monkeypatch,tmp_path,key):
    from app.adapters import bio_analysis_process as parent
    from app.core.exceptions import StorageError
    monkeypatch.setattr(parent,'validate_artifacts',lambda outputs,*args,**kwargs:outputs)
    result=dict(engine_version=parent.ENGINE_VERSION,status='completed',manifest={},summary={},outputs=[],
        steps=[dict(key=key,status='failed',reason='tool_failed')])
    assert parent.validate_engine_result(result,tmp_path,mode='figure') is result
    result['steps']=[dict(key='pca',status='failed',reason='tool_failed')]
    with pytest.raises(StorageError):parent.validate_engine_result(result,tmp_path,mode='figure')
