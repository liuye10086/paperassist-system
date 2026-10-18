"""Isolated v5 source confirmation cannot publish or stand in for plan approval."""
import pytest
from tests.helpers.legacy_plans import seed_legacy_plan
from tests.api.test_analysis import client,selection
from tests.helpers.analysis_plan import prepared_sample,run_plan,review_plan,decide_plan
from tests.integration.test_research_plan import research
from tests.test_batch09_research_flow import decision

def test_v5_manual_source_waits_and_requires_independent_approval(client,monkeypatch):
    base,file,prepared=prepared_sample(client)
    created=client.post(base+'/analysis-plans',json=dict(schema_version=5,input_kind='data',file_id=file['id'],dataset_id=prepared['id'],expected_setup_revision=0,selection=selection(numeric_column='D',group_column='C',unit='mg'),research_request=research(),evidence_version_ids=[]),headers={'Idempotency-Key':'source-v5'})
    assert created.status_code==202,created.text
    task=created.json();assert run_plan(task)['status']=='waiting_input'
    view=review_plan(client,task)
    assert view['source_reference'] is None and view['source_resolution'] is None
    assert 'source_confirmation' in view['check']['research_missing']
    assert decide_plan(client,task,decision(view),'early-approve').status_code==409
    body={k:view[k] for k in ('input_version','checkpoint_id','wait_id','plan_revision')}
    body.update(expected_task_revision=view['task']['revision'],source_resolution=dict(confirmed=True,note='This question refers to the frozen file, worksheet and prepared version.'))
    path='/api/v1/tasks/'+task['id']+'/analysis-plan/source-decisions'
    supplied=client.post(path,json=body,headers={'Idempotency-Key':'clarify'})
    assert supplied.status_code==202,supplied.text
    assert client.post(path,json=body,headers={'Idempotency-Key':'clarify'}).status_code==200
    assert run_plan(supplied.json())['status']=='waiting_confirmation'
    current=review_plan(client,task)
    assert current['plan_revision']==2 and current['result'] is None
    assert client.post(path,json=body,headers={'Idempotency-Key':'stale'}).status_code==409
    approved=decide_plan(client,task,decision(current),'independent-approve')
    assert approved.status_code==202,approved.text
    assert run_plan(approved.json())['status']=='succeeded'
    final=review_plan(client,task)
    assert final['result']['schema_version']==5
    # GET retains source/checkpoint validation while never invoking numeric build_check.
    def forbidden(*a,**k):raise AssertionError('GET must not recompute')
    monkeypatch.setattr('app.domain.analysis_plan.checks.build_check',forbidden)
    assert client.get('/api/v1/tasks/'+task['id']+'/analysis-plan').status_code==200
    assert client.get(base+'/analysis-plans/'+final['result']['id']).status_code==200

@pytest.mark.parametrize('parent_version',[4,5])
def test_new_continuation_requires_v5_source_confirmation_even_from_legacy_parent(client,parent_version):
    base,file,prepared=prepared_sample(client)
    body=dict(schema_version=parent_version,input_kind='data',file_id=file['id'],dataset_id=prepared['id'],expected_setup_revision=0,selection=None,research_request=research(),evidence_version_ids=[])
    task=seed_legacy_plan(client,base+'/analysis-plans',json=body,headers={'Idempotency-Key':'parent'}).json()
    assert run_plan(task)['status']=='waiting_input';view=review_plan(client,task)
    request={k:view[k] for k in ('input_version','checkpoint_id','wait_id','plan_revision')}
    request.update(expected_task_revision=view['task']['revision'],file_id=file['id'],dataset_id=prepared['id'],expected_setup_revision=0,selection=selection(numeric_column='D',group_column='C',unit='mg'),research_request=research())
    path='/api/v1/tasks/'+task['id']+'/analysis-plan/continuations'
    response=client.post(path,json=request,headers={'Idempotency-Key':'child-v5'})
    assert response.status_code==202,response.text
    child=response.json()['task']
    assert child['input_version']['workflow_version']=='analysis_plan_v5'
    assert run_plan(child)['status']=='waiting_input'
    current=review_plan(client,child)
    assert current['check']['research_missing']==['source_confirmation']
    assert current['source_resolution'] is None and current['result'] is None
    assert decide_plan(client,child,decision(current),'early-child-approve').status_code==409
    replay=client.post(path,json=request,headers={'Idempotency-Key':'child-v5'})
    assert replay.status_code==200 and replay.json()==response.json()
    assert client.post(path,json=request,headers={'Idempotency-Key':'second-child'}).status_code==409
    parent=review_plan(client,task)
    assert parent['continuation']==response.json() and parent['result'] is None
    assert parent['input_version']['workflow_version']==f'analysis_plan_v{parent_version}'
    if parent_version==4:
        assert 'source_resolution' not in parent and 'source_reference' not in parent
    from app.db.database import database_connection
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM confirmed_analysis_plans WHERE task_id IN (%s,%s)',(task['id'],child['id'])).fetchone()['n']==0
        assert db.execute("SELECT count(*) AS n FROM tasks WHERE input_snapshot->>'parent_requirement_task_id'=%s",(task['id'],)).fetchone()['n']==1

def test_v5_question_revision_invalidates_prior_source_clarification(client):
    base,file,prepared=prepared_sample(client)
    created=client.post(base+'/analysis-plans',json=dict(schema_version=5,input_kind='data',file_id=file['id'],dataset_id=prepared['id'],expected_setup_revision=0,selection=selection(numeric_column='D',group_column='C',unit='mg'),research_request=research(),evidence_version_ids=[]),headers={'Idempotency-Key':'rev-source'}).json()
    assert run_plan(created)['status']=='waiting_input';view=review_plan(client,created)
    body={k:view[k] for k in ('input_version','checkpoint_id','wait_id','plan_revision')};body.update(expected_task_revision=view['task']['revision'],source_resolution=dict(confirmed=True,note='Current selected data.'))
    clarified=client.post('/api/v1/tasks/'+created['id']+'/analysis-plan/source-decisions',json=body,headers={'Idempotency-Key':'resolve-source'}).json()
    assert run_plan(clarified)['status']=='waiting_confirmation';view=review_plan(client,created)
    revised=decide_plan(client,created,decision(view,'revise',research_request=research(question='A revised research question referring to a different study')),'change-question')
    assert revised.status_code==202,revised.text
    assert run_plan(revised.json())['status']=='waiting_input'
    current=review_plan(client,created);assert current['source_resolution'] is None


def test_saved_v4_continuation_is_read_and_replayed_without_creating_a_new_child(client,monkeypatch):
    """Seed an old receipt through the retained v4 builder, then use current APIs."""
    from app.domain.analysis_plan import requirements_service
    from app.domain.analysis_plan.requirements import RequirementCreateRequest
    from app.db.database import database_connection
    base,file,prepared=prepared_sample(client)
    body=dict(schema_version=4,input_kind='data',file_id=file['id'],dataset_id=prepared['id'],expected_setup_revision=0,selection=None,research_request=research(),evidence_version_ids=[])
    parent=seed_legacy_plan(client,base+'/analysis-plans',json=body,headers={'Idempotency-Key':'historic-parent'}).json()
    assert run_plan(parent)['status']=='waiting_input';view=review_plan(client,parent)
    request={k:view[k] for k in ('input_version','checkpoint_id','wait_id','plan_revision')}
    request.update(expected_task_revision=view['task']['revision'],file_id=file['id'],dataset_id=prepared['id'],expected_setup_revision=0,selection=None,research_request=research())
    path='/api/v1/tasks/'+parent['id']+'/analysis-plan/continuations'
    original=requirements_service.create_requirement
    def historical_child(service,project,request,key,**kwargs):
        raw=request.model_dump(mode='json');raw['schema_version']=4
        return original(service,project,RequirementCreateRequest.model_validate(raw),key,**kwargs)
    # This fixture alone reproduces the persisted old child. Production HTTP
    # behavior is asserted without patching in the parameterized test above.
    with monkeypatch.context() as patch:
        patch.setattr(requirements_service,'create_requirement',historical_child)
        saved=client.post(path,json=request,headers={'Idempotency-Key':'historic-receipt'})
    assert saved.status_code==202,saved.text
    receipt=saved.json();child=receipt['task']
    assert child['input_version']['workflow_version']=='analysis_plan_v4'
    assert run_plan(child)['status']=='waiting_input'
    old=review_plan(client,child)
    assert old['check']['rules_version']=='analysis_plan_rules_v4'
    assert old['check']['research_missing']==['selection'] and 'source_resolution' not in old
    assert review_plan(client,parent)['continuation']==receipt
    replay=client.post(path,json=request,headers={'Idempotency-Key':'historic-receipt'})
    assert replay.status_code==200 and replay.json()==receipt
    with database_connection() as db:
        assert db.execute("SELECT count(*) AS n FROM tasks WHERE input_snapshot->>'parent_requirement_task_id'=%s",(parent['id'],)).fetchone()['n']==1
        assert db.execute('SELECT count(*) AS n FROM confirmed_analysis_plans WHERE task_id IN (%s,%s)',(parent['id'],child['id'])).fetchone()['n']==0
