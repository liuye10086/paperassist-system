"""Persisted v3 approval is independent from numeric execution."""
from tests.helpers.legacy_plans import seed_legacy_plan
from tests.helpers.statistics import statistics_post
import copy
import pytest
from tests.api.test_analysis import client
from tests.integration.test_dataset_preparation import create_preparation,run,review,decide,decision
from tests.helpers.analysis_plan import run_plan,review_plan,plan_decision,decide_plan
from tests.domain.test_correlation_plan_contracts import selection,research

def prepared_correlations(client, *, rows=None):
    base,file,raw,_,task=create_preparation(client,rows=rows or [['身高','体重','第三列'],[1,2,9],[2,4,8],[3,6,7],[4,None,6],[None,10,5]])
    run(task);view=review(client,task);recipe=copy.deepcopy(view['recipe'])
    for field in recipe['fields']: field['unit']={'status':'confirmed','value':''}
    changed=decide(client,task,decision(view,'revise',recipe),'prepare-revise').json()
    run(changed);confirmed=decide(client,task,decision(review(client,task)),'prepare-confirm').json()
    assert run(confirmed)['status']=='succeeded'
    return base,file,review(client,task)['result']

def create_correlation(client,base,prepared,*,changes=None):
    chosen=selection();chosen['sheet_name']=prepared['source']['sheet_name'];chosen['units']={'A':'','B':''}
    body=dict(schema_version=3,dataset_id=prepared['id'],expected_setup_revision=0,selection=chosen,
        research_request=research(),recommendation_ref=None)
    if changes: body.update(changes)
    response=seed_legacy_plan(client, base+'/analysis-plans',json=body,headers={'Idempotency-Key':'correlation-plan'})
    assert response.status_code==202,response.text
    return response.json(),body

def test_confirmed_correlation_preserves_complete_record_rows_and_distinct_plan(client):
    base,_,prepared=prepared_correlations(client)
    task,body=create_correlation(client,base,prepared)
    assert run_plan(task)['status']=='waiting_confirmation'
    assert statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).status_code==409
    view=review_plan(client,task)
    approved=decide_plan(client,task,plan_decision(view)).json()
    assert run_plan(approved)['status']=='succeeded'
    result=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1})
    assert result.status_code==200,result.text
    value=result.json()
    assert value['schema_version']==3 and value['result_type']=='correlation'
    assert value['statistics']['coefficient']==pytest.approx(1)
    assert value['statistics']['n']==3 and value['check']['excluded_count']==2
    assert value['row_audit']['included_rows']==[2,3,4]
    assert value['row_audit']['excluded_rows']==[
        {'row':5,'coordinates':['B5'],'reason':'selected_missing'},
        {'row':6,'coordinates':['A6'],'reason':'selected_missing'}]
    assert value['analysis_context']['plan']==review_plan(client,task)['result']
    assert client.get(base+'/analysis-result').json()['result']==value
    assert statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).json()==value
    from app.maintenance.database_audit import audit_database
    from app.db.database import database_connection
    with database_connection() as db:
        audit=audit_database(db)
        assert audit['ok'],audit

def test_unknown_independence_requires_revision_then_separate_confirmation(client):
    base,_,prepared=prepared_correlations(client)
    declaration=research();declaration['observation_structure']='unknown'
    task,_=create_correlation(client,base,prepared,changes={'research_request':declaration})
    assert run_plan(task)['status']=='waiting_input'
    first=review_plan(client,task)
    assert 'observation_structure' in first['check']['research_missing']
    assert decide_plan(client,task,plan_decision(first),'early').status_code==409
    body=plan_decision(first,'revise',first['selection']);body['research_request']=research()
    updated=decide_plan(client,task,body,'supply').json()
    assert run_plan(updated)['status']=='waiting_confirmation'
    second=review_plan(client,task)
    assert second['plan_revision']==2 and second['wait_id']!=first['wait_id']
    assert decide_plan(client,task,plan_decision(first),'stale').status_code==409


def test_platform_roundoff_preserves_frozen_statistics_and_saved_json(client,monkeypatch):
    import json
    import math
    from app.adapters.task_store import DatasetTaskAssets
    from app.db.database import database_connection,get_database_config
    from app.domain.correlation import kernel
    from app.domain.correlation.service import load_correlation_input
    from tests.helpers.tasks import task_owner
    base,_,prepared=prepared_correlations(client,rows=[['X','Y'],[1,2],[2,1],[3,4],[4,3],[5,5]])
    task,_=create_correlation(client,base,prepared)
    run_plan(task);approved=decide_plan(client,task,plan_decision(review_plan(client,task))).json();run_plan(approved)
    response=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1});assert response.status_code==200
    result=response.json();original=copy.deepcopy(result)
    with database_connection() as db:
        saved_json=db.execute('SELECT result_json FROM analysis_runs WHERE id=%s',(result['id'],)).fetchone()['result_json']
    compute=kernel.compute_correlation
    def other_platform(*args,**kwargs):
        value=compute(*args,**kwargs)
        if value['mode']=='pair':
            for _ in range(8): value['p_value']['value']=math.nextafter(value['p_value']['value'],0.0)
            assert value['p_value']['value']!=result['statistics']['p_value']['value']
        return value
    monkeypatch.setattr(kernel,'compute_correlation',other_platform)
    assets=DatasetTaskAssets(task_owner(client),get_database_config())
    material=load_correlation_input(assets,task['project_id'],result['file_id'],result)
    assert material['statistics']==original['statistics'] and result==original
    material['statistics']['p_value']['value']=0.25
    assert result==original  # Callers cannot mutate the frozen result through returned facts.
    assert client.get(base+'/analysis-result').json()['result']==original
    assert statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).json()==original
    with database_connection() as db:
        current=db.execute('SELECT result_json FROM analysis_runs WHERE id=%s',(result['id'],)).fetchone()['result_json']
    assert current==saved_json and json.loads(current)['statistics']==original['statistics']

@pytest.mark.parametrize('mutation',[
    lambda value:value['statistics'].update(arbitrary_method='kendall'),
    lambda value:value['statistics']['p_value'].update(value=2.0),
    lambda value:value['statistics'].update(coefficient=0.123),
    lambda value:value['statistics']['p_value'].update(value=0.123),
    lambda value:value['statistics']['confidence_interval'].update(low=-0.5,high=0.5,reason=None,method='fisher_z'),
    lambda value:value['statistics'].update(n=4),
    lambda value:value['row_audit'].update(included_rows=[2,3,5]),
],ids=['extra','invalid_p','coefficient','valid_p','ci','n','rows'])
def test_invalid_saved_correlation_contract_fails_closed_on_read(client,mutation,request):
    base,_,prepared=prepared_correlations(client);task,_=create_correlation(client,base,prepared)
    run_plan(task);approved=decide_plan(client,task,plan_decision(review_plan(client,task))).json();run_plan(approved)
    response=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1});assert response.status_code==200
    value=response.json();mutation(value)
    if request.node.callspec.id not in ('extra','invalid_p'):
        from app.domain.correlation.service import CorrelationResult
        CorrelationResult.model_validate(value,strict=True)  # Shape-valid but scientifically false.
    import json
    from app.db.database import database_connection
    with database_connection(write=True) as db:
        db.execute('UPDATE analysis_runs SET result_json=%s WHERE id=%s',(json.dumps(value),value['id']))
    assert client.get(base+'/analysis-result').status_code==409
    assert statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).status_code==409
    run_url=base+'/analysis-runs/'+value['id']
    for suffix in ('/boxplot','/boxplot/image','/boxplot/disclosure','/figures/missing/download',
            '/explanation','/explanation/disclosure','/report','/report/missing/download'):
        assert client.get(run_url+suffix).status_code==409,suffix
    from types import SimpleNamespace
    from tests.helpers.tasks import task_owner
    from app.adapters.task_store import TaskStore
    from app.core.exceptions import StorageError
    repository=TaskStore(task_owner(client));project_id=base.split('/')[4]
    with repository.connection() as db:
        project=repository.require_project(db,project_id)
        request=SimpleNamespace(file_id=value['file_id'],analysis_run_id=value['id'],expected_revision=1,
            figure_id=None,explanation_id=None)
        with pytest.raises(StorageError) as caught: repository.source_snapshot(db,project,request)
        assert caught.value.code=='task_source_conflict'
