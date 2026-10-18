"""Isolated database v4 waiting, handoff and independent approval."""
from tests.helpers.legacy_plans import seed_legacy_plan
from tests.api.test_analysis import client,selection
from tests.helpers.analysis_plan import prepared_sample,run_plan,review_plan,decide_plan
from tests.integration.test_research_plan import research


def decision(view,operation='approve',**changes):
    check=view['check']['data_check']
    return dict(operation=operation,expected_task_revision=view['task']['revision'],input_version=view['input_version'],
        checkpoint_id=view['checkpoint_id'],wait_id=view['wait_id'],plan_revision=view['plan_revision'],
        resolutions={i['id']:i['allowed_resolutions'][0] for i in check['issues']} if operation=='approve' and check else {},**changes)


def test_data_requirement_without_selection_waits_then_requires_separate_approval(client,tmp_path):
    base,file,prepared=prepared_sample(client)
    body=dict(schema_version=4,input_kind='data',file_id=file['id'],dataset_id=prepared['id'],expected_setup_revision=0,
        selection=None,research_request=research(),evidence_version_ids=[])
    created=seed_legacy_plan(client, base+'/analysis-plans',json=body,headers={'Idempotency-Key':'v4'})
    assert created.status_code==202,created.text
    task=created.json();assert run_plan(task)['status']=='waiting_input'
    view=review_plan(client,task)
    assert view['check']['research_missing']==['selection'] and view['check']['data_check'] is None
    assert decide_plan(client,task,decision(view),'early').status_code==409
    revised=decide_plan(client,task,decision(view,'revise',selection=selection(numeric_column='D',group_column='C',unit='mg')),'supply')
    assert revised.status_code==202,revised.text
    assert run_plan(revised.json())['status']=='waiting_confirmation'
    second=review_plan(client,task)
    assert second['result'] is None and second['plan_revision']==2 and second['check']['data_check']['selection_check']['ready']
    approved=decide_plan(client,task,decision(second),'approve')
    assert approved.status_code==202,approved.text
    assert run_plan(approved.json())['status']=='succeeded'
    final=review_plan(client,task)
    assert final['result']['schema_version']==4 and final['result']['source']==view['source']
    page=client.get(base+'/analysis-plans')
    assert page.status_code==200,page.text
    assert page.json()['items'][0]['result']==final['result']
    import json
    fixture=tmp_path/'research-confirmed-fixture.json'
    fixture.write_text(json.dumps(final,ensure_ascii=False),encoding='utf-8')


def test_continuation_is_atomic_fixed_source_and_replayed_once(client):
    base,file,prepared=prepared_sample(client)
    body=dict(schema_version=4,input_kind='data',file_id=file['id'],dataset_id=prepared['id'],expected_setup_revision=0,
        selection=None,research_request=research(),evidence_version_ids=[])
    task=seed_legacy_plan(client, base+'/analysis-plans',json=body,headers={'Idempotency-Key':'parent'}).json()
    assert run_plan(task)['status']=='waiting_input';view=review_plan(client,task)
    request={k:view[k] for k in ('input_version','checkpoint_id','wait_id','plan_revision')}
    request.update(expected_task_revision=view['task']['revision'],file_id=file['id'],dataset_id=prepared['id'],expected_setup_revision=0,
        selection=selection(numeric_column='D',group_column='C',unit='mg'),research_request=research())
    path='/api/v1/tasks/'+task['id']+'/analysis-plan/continuations'
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:client.post(path,json=request,headers={'Idempotency-Key':'supply'}),range(2)))
    assert sorted(r.status_code for r in results)==[200,202],[r.text for r in results]
    first=next(r for r in results if r.status_code==202)
    assert first.status_code==202,first.text
    receipt=first.json();assert receipt['completion_type']=='continued_as_plan'
    replay=client.post(path,json=request,headers={'Idempotency-Key':'supply'})
    assert replay.status_code==200 and replay.json()==receipt
    parent=review_plan(client,task)
    assert parent['task']['status']=='succeeded' and parent['result'] is None and parent['continuation']==receipt
    child=receipt['task'];assert child['id']!=task['id']
    assert run_plan(child)['status']=='waiting_input'
    child_view=review_plan(client,child)
    assert child_view['input_version']['workflow_version']=='analysis_plan_v5'
    assert child_view['check']['research_missing']==['source_confirmation'] and child_view['result'] is None
    assert client.post(path,json=request,headers={'Idempotency-Key':'different-key'}).status_code==409


def test_material_requirement_freezes_evidence_without_loading_dataset(client,monkeypatch):
    base,file,prepared=prepared_sample(client)
    project=base.split('/')[4]
    evidence=client.post('/api/v1/projects/'+project+'/external-evidence',json=dict(file_id=file['id'],source_kind='original',
        title='External graph',intended_use='request_reanalysis',original_data='unavailable'),headers={'Idempotency-Key':'evidence'})
    assert evidence.status_code==201,evidence.text
    def no_data(*args,**kwargs):raise AssertionError('Materials must never load computational data')
    from app.domain.analysis_plan import requirements_service
    original_loader=requirements_service.load_dataset
    monkeypatch.setattr('app.domain.analysis_plan.requirements_service.load_dataset',no_data)
    body=dict(schema_version=4,input_kind='materials',file_id=None,dataset_id=None,expected_setup_revision=0,
        selection=None,research_request=research(),evidence_version_ids=[evidence.json()['id']])
    created=seed_legacy_plan(client, '/api/v1/projects/'+project+'/analysis-plans',json=body,headers={'Idempotency-Key':'materials'})
    assert created.status_code==202,created.text
    task=created.json();assert run_plan(task)['status']=='waiting_input'
    view=review_plan(client,task)
    assert view['source'] is None and view['selection'] is None and view['result'] is None
    assert view['check']['research_missing']==['source','selection'] and view['check']['data_check'] is None
    assert view['evidence_versions']==[evidence.json()]
    assert decide_plan(client,task,decision(view),'approve-no-data').status_code==409
    workspace=client.get('/api/v1/tasks/'+task['id']+'/workspace')
    assert workspace.status_code==200,workspace.text
    assert workspace.json()['source']['material_versions']==[evidence.json()]
    corrected=decide_plan(client,task,decision(view,'revise',selection=None,research_request=research(question='Corrected external requirement')),'materials-revision')
    assert corrected.status_code==202,corrected.text
    assert run_plan(corrected.json())['status']=='waiting_input'
    view=review_plan(client,task)
    assert view['selection'] is None and view['research_request']['question']=='Corrected external requirement'
    monkeypatch.setattr(requirements_service,'load_dataset',original_loader)
    continuation={k:view[k] for k in ('input_version','checkpoint_id','wait_id','plan_revision')}
    continuation.update(expected_task_revision=view['task']['revision'],file_id=file['id'],dataset_id=prepared['id'],
        expected_setup_revision=0,selection=selection(numeric_column='D',group_column='C',unit='mg'),research_request=research())
    response=client.post('/api/v1/tasks/'+task['id']+'/analysis-plan/continuations',json=continuation,headers={'Idempotency-Key':'raw-data'})
    assert response.status_code==202,response.text
    child=response.json()['task'];assert run_plan(child)['status']=='waiting_input'
    assert review_plan(client,task)['source'] is None
    child_view=review_plan(client,child)
    assert child_view['source']['dataset_id']==prepared['id'] and child_view['evidence_versions']==[evidence.json()]
    assert child_view['input_version']['workflow_version']=='analysis_plan_v5'
    assert child_view['check']['research_missing']==['source_confirmation']
    assert child_view['result'] is None


def test_v4_explicit_null_selection_clears_method_and_revises_material_text(client):
    base,file,prepared=prepared_sample(client)
    body=dict(schema_version=4,input_kind='data',file_id=file['id'],dataset_id=prepared['id'],expected_setup_revision=0,
        selection=selection(numeric_column='D',group_column='C',unit='mg'),research_request=research(),evidence_version_ids=[])
    created=seed_legacy_plan(client, base+'/analysis-plans',json=body,headers={'Idempotency-Key':'clear-selection'})
    assert created.status_code==202,created.text
    task=created.json();assert run_plan(task)['status']=='waiting_confirmation'
    view=review_plan(client,task)
    cleared=decide_plan(client,task,decision(view,'revise',selection=None),'clear')
    assert cleared.status_code==202,cleared.text
    assert run_plan(cleared.json())['status']=='waiting_input'
    current=review_plan(client,task)
    assert current['selection'] is None and current['check']['research_missing']==['selection']
    assert decide_plan(client,task,decision(current),'approve-empty').status_code==409
    changed=research(question='Changed local requirement')
    revision=decide_plan(client,task,decision(current,'revise',selection=None,research_request=changed),'revise-question')
    assert revision.status_code==202,revision.text
    assert run_plan(revision.json())['status']=='waiting_input'
    assert review_plan(client,task)['research_request']==changed
