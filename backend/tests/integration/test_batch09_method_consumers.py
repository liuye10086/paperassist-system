"""Every already-approved numerical method consumes a filtered v3 + approved v4 plan."""
from tests.helpers.legacy_plans import seed_legacy_plan
from tests.helpers.statistics import statistics_post
import copy
import json
import pytest
from tests.api.test_analysis import client
from tests.domain.test_batch08_method_boundaries import METHODS,case
from tests.domain.test_correlation_plan_contracts import research
from tests.integration.test_dataset_preparation import create_preparation,run,review,decide,decision
from tests.integration.test_batch09_filter_pipeline import filtering,accept
from tests.helpers.analysis_plan import run_plan,review_plan,decide_plan
from tests.test_batch09_research_flow import decision as plan_decision
from app.db.database import database_connection


@pytest.mark.parametrize('method',METHODS)
def test_existing_method_never_restores_excluded_rows_and_preserves_external_boundary(client,method):
    values,chosen=case(method)
    width=len(values[0]);headers=['Field '+str(i+1) for i in range(width)]+['Include']
    rows=[headers]+[v+[1] for v in values]+[copy.deepcopy(values[0])+[0]]
    base,file,_,_,task=create_preparation(client,rows=rows)
    run(task);view=review(client,task);recipe=copy.deepcopy(view['recipe'])
    for field in recipe['fields']:
        field['unit']=dict(status='confirmed',value='day' if method=='kaplan_meier' and field['column']==2 else '')
    changed=decide(client,task,decision(view,'revise',recipe),'units').json();run(changed)
    approved=decide(client,task,decision(review(client,task)),'prepare-approve').json()
    assert run(approved)['status']=='succeeded'
    parent=review(client,task)['result'];old_bytes=client.get(parent['download_url']).content
    filter_task,_=filtering(client,base,parent,recipe=dict(conditions=[dict(column=width+1,kind='number',operator='eq',value='1')],
        reason='Prespecified synthetic population',unit_acknowledged=True))
    filtered,_,_=accept(client,filter_task)
    assert filtered['summary']['retained_record_count']==len(values)
    project=base.split('/')[4]
    external=client.post(f'/api/v1/projects/{project}/external-evidence',json=dict(file_id=file['id'],source_kind='original',
        title='External numeric claim 99999',user_note='EXTERNAL-CLAIM-SENTINEL P=0.000001 n=99999',
        intended_use='reference',original_data='unknown'),headers={'Idempotency-Key':'external'})
    assert external.status_code==201,external.text
    chosen['sheet_name']=filtered['source']['sheet_name'];declaration=research()
    if method in ('paired_t','wilcoxon'):
        declaration.update(observation_structure='paired',relationship_description='Same synthetic units')
    response=seed_legacy_plan(client, base+'/analysis-plans',json=dict(schema_version=4,input_kind='data',file_id=file['id'],dataset_id=filtered['id'],
        expected_setup_revision=0,selection=chosen,research_request=declaration,evidence_version_ids=[external.json()['id']]),
        headers={'Idempotency-Key':'v4-plan'})
    assert response.status_code==202,response.text
    plan=response.json();assert run_plan(plan)['status']=='waiting_confirmation'
    view=review_plan(client,plan)
    assert statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).status_code==409
    approved=decide_plan(client,plan,plan_decision(view),'approve')
    assert approved.status_code==202,approved.text
    assert run_plan(approved.json())['status']=='succeeded'
    result_response=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1})
    assert result_response.status_code==200,result_response.text
    result=result_response.json()
    assert result['source']==filtered['source'] and result['analysis_context']['plan']['schema_version']==4
    assert result['check']['valid_count']==len(values)
    if method!='descriptive':assert result['row_audit']['included_rows']==list(range(2,len(values)+2))
    assert 'EXTERNAL-CLAIM-SENTINEL' not in json.dumps(result.get('statistics',result.get('overall')))
    assert client.get(base+'/analysis-result').json()['result']==result
    assert statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).json()==result
    assert client.get(parent['download_url']).content==old_bytes
    from app.maintenance.analysis_plan_audit import audit_analysis_plans
    from app.maintenance.dataset_source_audit import audit_dataset_sources
    with database_connection() as db:
        checks=audit_analysis_plans(db)+audit_dataset_sources(db)
        assert all(c['invalid']==0 for c in checks),checks
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']==0
