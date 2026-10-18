"""Approved comparisons keep local roles, typed groups and immutable provenance."""
from tests.helpers.legacy_plans import seed_legacy_plan
from tests.helpers.statistics import statistics_post
import copy
import json
import math
import pytest
from tests.api.test_analysis import client
from tests.integration.test_correlation_plan import prepared_correlations
from tests.helpers.analysis_plan import run_plan, review_plan, plan_decision, decide_plan
from tests.domain.test_correlation_plan_contracts import research


def selection(sheet, method='welch_t', **changes):
    design = 'paired' if method in ('paired_t', 'wilcoxon') else 'multiple' if method in ('welch_anova', 'kruskal_wallis') else 'independent'
    paired = design == 'paired'
    return dict(task_type='group_comparison', sheet_name=sheet, design=design, method=method,
        numeric_column=None if paired else 'A', group_column=None if paired else 'B',
        groups=[] if paired else [dict(kind='text', value=v) for v in (['A','B','C'] if design=='multiple' else ['A','B'])],
        pair_id_column='A' if paired else None, before_column='B' if paired else None, after_column='C' if paired else None,
        unit='', missing_policy='complete_pairs' if paired else 'complete_cases', posthoc='none',
        assumptions=dict(independent_units=True, distribution='normal' if method in ('welch_t','paired_t','welch_anova') else 'symmetric_differences' if paired else 'rank', inference_confirmed=True), **changes)


def make_plan(client, base, prepared, chosen=None, declaration=None, key='comparison'):
    body=dict(schema_version=3,dataset_id=prepared['id'],expected_setup_revision=0,
        selection=chosen or selection(prepared['source']['sheet_name']), research_request=declaration or research(),recommendation_ref=None)
    response=seed_legacy_plan(client, base+'/analysis-plans',json=body,headers={'Idempotency-Key':key})
    assert response.status_code==202,response.text
    return response.json(),body


def approve(client, task):
    assert run_plan(task)['status']=='waiting_confirmation'
    view=review_plan(client,task)
    approved=decide_plan(client,task,plan_decision(view)).json()
    assert run_plan(approved)['status']=='succeeded'
    return review_plan(client,task)['result']


def independent_rows():
    return [['Outcome','Group']]+[[v,'A'] for v in [1,2,4,5,7]]+[[v,'B'] for v in [3,5,6,8,11]]+[[v,'C'] for v in [6,7,9,12,13]]+[[8,'ignored'],[None,'A'],[3,None]]


@pytest.mark.parametrize('method',['welch_t','mann_whitney_u','paired_t','wilcoxon','welch_anova','kruskal_wallis'])
def test_six_methods_execute_only_after_confirmed_plan_and_keep_rows(client,method):
    paired=method in ('paired_t','wilcoxon')
    rows=[['ID','Before','After'],['local-private-1',8,2],['local-private-2',9,3],['local-private-3',7,4],['local-private-4',10,6],['local-private-5',11,8],['local-private-6',None,8]] if paired else independent_rows()
    base,_,prepared=prepared_correlations(client,rows=rows)
    chosen=selection(prepared['source']['sheet_name'],method)
    if chosen['design']=='multiple':chosen['posthoc']='all_pairs_holm'
    declaration=research()
    if paired:declaration.update(observation_structure='paired',relationship_description='Same participant before and after')
    task,_=make_plan(client,base,prepared,chosen,declaration)
    assert statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).status_code==409
    plan=approve(client,task)
    response=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1})
    assert response.status_code==200,response.text
    result=response.json()
    assert result['schema_version']==4 and result['result_type']=='group_comparison'
    assert result['analysis_context']['plan']==plan
    assert result['statistics']['method']==method and result['statistics']['sample_sizes']==[5]*len(result['groups'])
    assert result['check']['valid_count']==5 if paired else result['check']['valid_count'] in (10,15)
    assert result['row_audit']['included_rows']==list(range(2,7)) if paired else result['row_audit']['included_rows']==list(range(2,12 if chosen['design']=='independent' else 17))
    assert result['row_audit']['pair_id_column']==('A' if paired else None)
    assert 'local-private' not in json.dumps(result)
    assert result['analysis_context']['method']['observation_basis']==('paired_rows' if paired else 'independent_rows')
    assert statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).json()==result
    assert client.get(base+'/analysis-result').json()['result']==result
    if chosen['design']=='multiple':assert len(result['statistics']['pairwise'])==3
    from app.maintenance.database_audit import audit_database
    from app.db.database import database_connection
    with database_connection() as db:assert audit_database(db)['ok']


def test_group_options_read_full_sheet_and_keep_type_identity(client):
    rows=[['Outcome','Group']]+[[i,'first'] for i in range(25)]+[[1,1],[2,'1'],[3,True],[4,False],[5,None]]
    base,_,prepared=prepared_correlations(client,rows=rows)
    response=client.get(base+'/comparison-group-options',params=dict(dataset_id=prepared['id'],sheet=prepared['source']['sheet_name'],group_column='B'))
    assert response.status_code==200,response.text
    value=response.json()
    assert value['row_count']==30 and value['missing_count']==1
    assert value['options']==[dict(kind='text',value='first',label='first',count=25),dict(kind='number',value='1',label='1',count=1),dict(kind='text',value='1',label='1',count=1),dict(kind='boolean',value='true',label='TRUE',count=1),dict(kind='boolean',value='false',label='FALSE',count=1)]
    assert client.get(base+'/comparison-group-options',params=dict(dataset_id=prepared['id'],sheet='wrong',group_column='B')).status_code==422


@pytest.mark.parametrize('rows,code',[
    ([['ID','Before','After'],['x',1,2],['x',None,3],['z',4,3]],'pair_id_duplicate'),
    ([['ID','Before','After'],['x',1,2],[' ',None,3],['z',4,3]],'pair_id_missing'),
    ([['ID','Before','After'],['x',1,2],['y','3',3],['z',4,3]],'numeric_type'),
])
def test_bad_pair_ids_and_values_block_even_when_measurement_missing(client,rows,code):
    base,_,prepared=prepared_correlations(client,rows=rows)
    declaration=research();declaration.update(observation_structure='paired',relationship_description='paired')
    task,_=make_plan(client,base,prepared,selection(prepared['source']['sheet_name'],'paired_t'),declaration)
    run_plan(task);view=review_plan(client,task)
    assert any(i['code']==code and i['severity']=='blocking' for i in view['check']['issues'])
    approval=plan_decision({**view,'check':{**view['check'],'issues':[]}})
    assert decide_plan(client,task,approval).status_code==422


def test_comparison_requires_matching_research_and_explicit_distribution(client):
    base,_,prepared=prepared_correlations(client,rows=independent_rows())
    chosen=selection(prepared['source']['sheet_name']);chosen['assumptions'].update(distribution='unknown',inference_confirmed=False,independent_units=False)
    declaration=research();declaration.update(observation_structure='paired',relationship_description='paired')
    task,_=make_plan(client,base,prepared,chosen,declaration)
    assert run_plan(task)['status']=='waiting_input'
    view=review_plan(client,task)
    assert set(view['check']['research_missing'])>={'distribution','inference_confirmed','independent_units','observation_structure'}
    revised=plan_decision(view,'revise',selection(prepared['source']['sheet_name']));revised['research_request']=research()
    updated=decide_plan(client,task,revised,'revise').json()
    assert run_plan(updated)['status']=='waiting_confirmation'
    assert review_plan(client,task)['plan_revision']==2


def test_comparison_frozen_statistics_allow_only_small_platform_roundoff(client,monkeypatch):
    base,_,prepared=prepared_correlations(client,rows=independent_rows());task,_=make_plan(client,base,prepared);approve(client,task)
    result=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).json();original=copy.deepcopy(result)
    from app.domain.comparison import kernel
    from app.domain.comparison.service import load_comparison_input
    from app.adapters.task_store import DatasetTaskAssets
    from app.db.database import get_database_config
    from tests.helpers.tasks import task_owner
    compute=kernel.compute_comparison
    def rounded(*args,**kwargs):
        value=compute(*args,**kwargs)
        for _ in range(8):value['p_value']['value']=math.nextafter(value['p_value']['value'],0.0)
        return value
    monkeypatch.setattr(kernel,'compute_comparison',rounded)
    material=load_comparison_input(DatasetTaskAssets(task_owner(client),get_database_config()),task['project_id'],result['file_id'],result)
    assert material['statistics']==original['statistics']
    material['statistics']['p_value']['value']=0.25
    assert result==original and client.get(base+'/analysis-result').json()['result']==original


@pytest.mark.parametrize('mutation',[
    lambda v:v['statistics']['p_value'].update(value=0.25),
    lambda v:v['groups'][0]['statistics'].update(mean=999.0),
    lambda v:v['row_audit']['group_rows'][0].append(99),
    lambda v:v.update(result_type='unknown'),
])
def test_tampered_comparison_is_rejected_at_result_and_task_source_boundaries(client,mutation):
    base,_,prepared=prepared_correlations(client,rows=independent_rows());task,_=make_plan(client,base,prepared);approve(client,task)
    value=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).json();mutation(value)
    from app.db.database import database_connection
    with database_connection(write=True) as db:db.execute('UPDATE analysis_runs SET result_json=%s WHERE id=%s',(json.dumps(value),value['id']))
    assert client.get(base+'/analysis-result').status_code==409
    assert statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).status_code==409
    assert client.get(base+'/analysis-runs/'+value['id']+'/boxplot').status_code==409
    from app.adapters.task_store import TaskStore
    from app.core.exceptions import StorageError
    from tests.helpers.tasks import task_owner
    from types import SimpleNamespace
    repository=TaskStore(task_owner(client))
    with repository.connection() as db:
        project=repository.require_project(db,task['project_id'])
        with pytest.raises(StorageError) as caught:
            repository.source_snapshot(db,project,SimpleNamespace(file_id=value['file_id'],analysis_run_id=value['id'],
                expected_revision=1,figure_id=None,explanation_id=None))
        assert caught.value.code=='task_source_conflict'


def test_group_options_and_plan_reads_are_private(client):
    from tests.integration.test_project_ownership import account_client
    from fastapi.testclient import TestClient
    from app.main import app
    base,_,prepared=prepared_correlations(client,rows=independent_rows());task,_=make_plan(client,base,prepared);approve(client,task)
    result=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).json()
    params=dict(dataset_id=prepared['id'],sheet=prepared['source']['sheet_name'],group_column='B')
    with account_client('comparison-other@paperassist.local')[0] as other:
        assert other.get(base+'/comparison-group-options',params=params).status_code==404
        assert other.get(base+'/analysis-result').status_code==404
        assert other.get('/api/v1/tasks/'+task['id']+'/analysis-plan').status_code==404
    with TestClient(app) as anonymous:
        assert anonymous.get(base+'/comparison-group-options',params=params).status_code==401


def test_comparison_plan_idempotency_and_next_plan_preserve_prior_result(client):
    base,_,prepared=prepared_correlations(client,rows=independent_rows());task,body=make_plan(client,base,prepared)
    repeat=seed_legacy_plan(client, base+'/analysis-plans',json=body,headers={'Idempotency-Key':'comparison'})
    assert repeat.status_code==200 and repeat.json()==task
    first_plan=approve(client,task);first=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).json()
    revised=copy.deepcopy(body);revised.update(expected_setup_revision=1);revised['selection']['method']='mann_whitney_u';revised['selection']['assumptions']['distribution']='rank'
    assert seed_legacy_plan(client, base+'/analysis-plans',json=revised,headers={'Idempotency-Key':'comparison'}).status_code==409
    response=seed_legacy_plan(client, base+'/analysis-plans',json=revised,headers={'Idempotency-Key':'comparison-new'})
    assert response.status_code==202,response.text
    second_plan=approve(client,response.json());second=statistics_post(client, base+'/analysis-runs',json={'expected_revision':2}).json()
    assert first['id']!=second['id'] and first_plan['id']!=second_plan['id']
    from app.adapters.storage import get_project_store
    store=get_project_store()
    assert store.analysis_result_by_id(task['project_id'],first['file_id'],first['id'])==first
