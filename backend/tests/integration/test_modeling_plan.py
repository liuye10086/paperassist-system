"""Four new local methods consume the same explicit, durable approved plan."""
from tests.helpers.legacy_plans import seed_legacy_plan
from tests.helpers.statistics import statistics_post
import copy
import math
import pytest
from tests.api.test_analysis import client
from tests.helpers.modeling import sample,selection,approve,prepared_modeling
from tests.integration.test_correlation_plan import prepared_correlations
from tests.integration.test_comparison_plan import make_plan
from tests.helpers.analysis_plan import run_plan,review_plan,decide_plan,plan_decision


@pytest.mark.parametrize('method',['ols','logistic','roc_auc','kaplan_meier'])
def test_modeling_confirm_execute_cache_and_read(client,method):
    base,_,prepared=prepared_modeling(client,method)
    chosen=selection(method,prepared['source']['sheet_name'])
    task,_=make_plan(client,base,prepared,chosen,key='modeling')
    assert statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).status_code==409
    plan=approve(client,task)
    response=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1})
    assert response.status_code==200,response.text
    result=response.json();stats=result['statistics']
    assert result['schema_version']==5 and result['result_type']==chosen['task_type']
    assert result['analysis_context']['plan']==plan
    assert stats['method']==method
    if method=='ols':
        assert [c['beta'] for c in stats['coefficients']]==pytest.approx([1,2])
        assert stats['residual_sd']==pytest.approx(math.sqrt(3.5/12))
    if method=='logistic':assert stats['coefficients'][1]['or_value']==pytest.approx(9.0)
    if method=='kaplan_meier':assert stats['groups'][0]['points'][-1]['survival']==pytest.approx(0.3)
    assert statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).json()==result
    assert client.get(base+'/analysis-result').json()['result']==result
    from app.maintenance.database_audit import audit_database
    from app.db.database import database_connection
    with database_connection() as db:assert audit_database(db)['ok']


def test_missing_role_waits_for_revision_then_separate_confirmation(client):
    base,_,prepared=prepared_correlations(client,rows=sample('roc_auc'))
    chosen=selection('roc_auc',prepared['source']['sheet_name']);chosen['score_column']=None
    task,_=make_plan(client,base,prepared,chosen)
    assert run_plan(task)['status']=='waiting_input'
    view=review_plan(client,task)
    assert 'score_column' in view['check']['research_missing']
    assert decide_plan(client,task,plan_decision(view)).status_code==409
    revision=plan_decision(view,'revise',selection('roc_auc',prepared['source']['sheet_name']))
    changed=decide_plan(client,task,revision,'supplement')
    assert changed.status_code==202,changed.text
    assert decide_plan(client,task,revision,'supplement').json()==changed.json()
    assert run_plan(changed.json())['status']=='waiting_confirmation'
    reviewed=review_plan(client,task)
    assert reviewed['plan_revision']==2 and reviewed['result'] is None
    assert decide_plan(client,task,plan_decision(view),'stale').status_code==409
    published=decide_plan(client,task,plan_decision(reviewed),'confirm').json()
    assert run_plan(published)['status']=='succeeded'


@pytest.mark.parametrize('mutation',[
    lambda v:v['statistics'].update(auc=0.01),
    lambda v:v['statistics'].update(positive_n=999),
    lambda v:v['row_audit']['included_rows'].append(999),
    lambda v:v['engine'].update(timeout_seconds=999),
    lambda v:v['engine'].update(parser_version='untrusted_parser_v999'),
])
def test_tampered_modeling_result_rejected_at_reads_and_cache(client,mutation):
    import json
    from app.db.database import database_connection
    base,_,prepared=prepared_correlations(client,rows=sample('roc_auc'))
    task,_=make_plan(client,base,prepared,selection('roc_auc',prepared['source']['sheet_name']))
    approve(client,task)
    response=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1})
    assert response.status_code==200,response.text
    value=response.json();mutation(value)
    with database_connection(write=True) as db:
        db.execute('UPDATE analysis_runs SET result_json=%s WHERE id=%s',(json.dumps(value),value['id']))
    assert client.get(base+'/analysis-result').status_code==409
    assert statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).status_code==409
    assert client.get(base+'/analysis-runs/'+value['id']+'/boxplot/disclosure').status_code==409


def test_new_modeling_plan_keeps_prior_result_and_owner_boundary(client):
    from tests.integration.test_project_ownership import account_client
    from app.adapters.storage import get_project_store
    base,_,prepared=prepared_correlations(client,rows=sample('roc_auc'))
    chosen=selection('roc_auc',prepared['source']['sheet_name'])
    task,body=make_plan(client,base,prepared,chosen,key='first')
    approve(client,task)
    first=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).json()
    changed=copy.deepcopy(body);changed['expected_setup_revision']=1
    changed['selection'].update(evaluation_role='apparent_exploratory',independence_confirmed=False)
    response=seed_legacy_plan(client, base+'/analysis-plans',json=changed,headers={'Idempotency-Key':'second'})
    assert response.status_code==202,response.text
    approve(client,response.json())
    response=statistics_post(client, base+'/analysis-runs',json={'expected_revision':2})
    assert response.status_code==200,response.text
    second=response.json()
    assert second['id']!=first['id']
    assert second['statistics']['confidence_interval']['low'] is None
    assert second['statistics']['confidence_interval']['reason']=='evaluation_role_not_independent'
    assert get_project_store().analysis_result_by_id(task['project_id'],first['file_id'],first['id'])==first
    with account_client('modeling-private@paperassist.local')[0] as other:
        assert other.get(base+'/analysis-result').status_code==404
        assert other.get('/api/v1/tasks/'+task['id']+'/analysis-plan').status_code==404
