"""Persisted approval, actual statistical consumption and cache boundary protection."""
from tests.helpers.legacy_plans import seed_legacy_plan
from tests.helpers.statistics import statistics_post
import copy
import json
import pytest
from psycopg.types.json import Jsonb
from app.db.database import database_connection
from tests.api.test_analysis import client,selection
from tests.api.test_dataset_analysis import forbid_original
from tests.helpers.analysis_plan import prepared_sample,create_plan,run_plan,review_plan,plan_decision,decide_plan,confirmed_sample


@pytest.mark.parametrize('planned',[False,True])
def test_trusted_recovery_reads_legacy_and_validates_planned_results(client,planned):
    from app.adapters.storage import ProjectStore
    from app.core.config import get_data_dir
    from app.core.exceptions import StorageError
    if planned:
        base,_,_,_=confirmed_sample(client)
    else:
        from tests.api.test_analysis import add_file
        base,_=add_file(client)
        assert client.put(base+'/analysis-setup',json=selection(expected_revision=0)).status_code==200
    response=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1})
    assert response.status_code==200,response.text
    result=response.json(); project=base.split('/')[4]; file=base.split('/')[6]
    trusted=ProjectStore(get_data_dir())
    assert trusted.analysis_result_by_id(project,file,result['id'])==result
    if planned:
        with database_connection(write=True) as db:
            value=copy.deepcopy(result);value.pop('analysis_plan')
            db.execute('UPDATE analysis_runs SET result_json=%s WHERE id=%s',(json.dumps(value),result['id']))
        with pytest.raises(StorageError) as error:
            trusted.analysis_result_by_id(project,file,result['id'])
        assert error.value.code=='task_source_conflict'


def test_explicit_plan_wait_approval_single_publish_and_real_statistics(client,monkeypatch):
    base,file,prepared=prepared_sample(client)
    task,body=create_plan(client,base,prepared)
    assert review_plan(client,task)['check'] is None
    assert seed_legacy_plan(client, base+'/analysis-plans',json=body,headers={'Idempotency-Key':'plan'}).status_code==200
    assert run_plan(task)['status']=='waiting_confirmation'
    view=review_plan(client,task)
    assert view['check']['data_range']=='C5:D10' and view['check']['selection_check']['valid_count']==4
    assert client.get(base+'/analysis-setup').json() is None
    with database_connection() as db:
        attempt=db.execute('SELECT * FROM task_attempts WHERE task_id=%s',(task['id'],)).fetchone()
        assert attempt['finished_at'] and attempt['lease_owner'] is None
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']==0
    assert client.get('/api/v1/tasks/'+task['id']+'/workspace').json()['allowed_actions']==['approve','revise']
    assert client.get(base+'/analysis-plans').json()['items']==[view]
    decision=plan_decision(view)
    assert decide_plan(client,task,{**decision,'resolutions':{}},'incomplete').status_code==422
    accepted=decide_plan(client,task,decision)
    assert accepted.status_code==202,accepted.text
    replay=decide_plan(client,task,decision)
    assert replay.status_code==200 and replay.json()==accepted.json()
    assert run_plan(accepted.json())['status']=='succeeded'
    assert run_plan(accepted.json()) is None
    with database_connection() as db:
        published=db.execute('SELECT * FROM confirmed_analysis_plans').fetchone()
        from datetime import timezone
        assert published['plan_json']['created_at']==published['created_at'].astimezone(timezone.utc).isoformat()
    plan=review_plan(client,task)['result']
    saved=client.get(base+'/analysis-setup').json()
    monkeypatch.setattr('app.adapters.storage.ProjectStore.original',forbid_original)
    assert saved['analysis_plan']==dict(plan_id=plan['id'],sha256=plan['sha256'],resolutions=plan['resolutions'])
    result=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1})
    assert result.status_code==200,result.text
    assert result.json()['overall']['n']==4 and result.json()['overall']['mean']==5.5
    assert result.json()['analysis_plan']==saved['analysis_plan']
    assert statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).json()==result.json()
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM confirmed_analysis_plans').fetchone()['n']==1


def test_revise_uses_a_new_wait_and_cannot_approve_old_candidate(client):
    base,_,prepared=prepared_sample(client);task,_=create_plan(client,base,prepared)
    run_plan(task);first=review_plan(client,task)
    changed={**first['selection'],'group_column':None}
    revised=decide_plan(client,task,plan_decision(first,'revise',changed),'revise')
    assert revised.status_code==202,revised.text
    run_plan(revised.json());second=review_plan(client,task)
    assert second['plan_revision']==2 and second['wait_id']!=first['wait_id']
    assert second['check']['selection_check']['valid_count']==5
    assert decide_plan(client,task,plan_decision(first),'stale').status_code==409
    accepted=decide_plan(client,task,plan_decision(second),'approve-new')
    assert run_plan(accepted.json())['status']=='succeeded'


def test_publish_cannot_overwrite_concurrent_setup_and_legacy_new_revision_stays_compatible(client):
    base,_,prepared=prepared_sample(client);task,_=create_plan(client,base,prepared)
    run_plan(task);view=review_plan(client,task)
    direct=client.put(base+'/analysis-setup',json=selection(numeric_column='D',group_column='C',unit='mg',dataset_id=prepared['id'],expected_revision=0))
    assert direct.status_code==200 and 'analysis_plan' not in direct.json()
    approved=decide_plan(client,task,plan_decision(view))
    failed=run_plan(approved.json())
    assert failed['status']=='failed' and failed['error_code']=='setup_conflict'
    assert client.get(base+'/analysis-setup').json()==direct.json()
    assert statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).status_code==200


@pytest.mark.parametrize('damage',['plan','decision','check','source','setup_ref','result_ref','delete_setup_ref','delete_result_ref'])
def test_tampering_is_rejected_before_cached_statistics(client,damage):
    base,_,_,view=confirmed_sample(client)
    assert statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).status_code==200
    with database_connection(write=True) as db:
        if damage=='plan':
            row=db.execute('SELECT plan_json FROM confirmed_analysis_plans').fetchone();value=copy.deepcopy(row['plan_json'])
            value['selection']['unit']='forged';db.execute('UPDATE confirmed_analysis_plans SET plan_json=%s',(Jsonb(value),))
        elif damage=='decision':
            row=db.execute('SELECT request_json FROM analysis_plan_decisions').fetchone();value=copy.deepcopy(row['request_json'])
            value['resolutions']={};db.execute('UPDATE analysis_plan_decisions SET request_json=%s',(Jsonb(value),))
        elif damage in ('check','source'):
            row=db.execute('SELECT id,state_json FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',(view['task']['id'],)).fetchone()
            value=copy.deepcopy(row['state_json'])
            if damage=='check': value['check']['row_count']=999
            else: value['input_version']['source']['dataset_sha256']='c'*64
            db.execute('UPDATE task_checkpoints SET state_json=%s WHERE id=%s',(Jsonb(value),row['id']))
        else:
            table,column=('analysis_setups','setup_json') if 'setup' in damage else ('analysis_runs','result_json')
            value=json.loads(db.execute('SELECT '+column+' FROM '+table).fetchone()[column])
            if damage.startswith('delete'): value.pop('analysis_plan')
            else: value['analysis_plan']['sha256']='c'*64
            db.execute('UPDATE '+table+' SET '+column+'=%s',(json.dumps(value),))
    response=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1})
    assert response.status_code==409,response.text


def test_confirmed_history_survives_direct_new_setup_without_plan(client):
    base,_,prepared,view=confirmed_sample(client)
    old=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).json()
    new=client.put(base+'/analysis-setup',json=selection(numeric_column='D',group_column=None,unit='mg',dataset_id=prepared['id'],expected_revision=1))
    assert new.status_code==200 and new.json()['revision']==2 and 'analysis_plan' not in new.json()
    assert client.get(base+'/analysis-plans/'+view['result']['id']).json()==view['result']
    assert client.get(base+'/analysis-result').json()['result']==old
    assert statistics_post(client, base+'/analysis-runs',json={'expected_revision':2}).json()['overall']['n']==5


def test_create_and_decision_strictness_and_ownership(client):
    base,_,prepared=prepared_sample(client);task,body=create_plan(client,base,prepared)
    for changes in ({'dataset_id':prepared['parent_dataset_id']},{'source':prepared['source']},{'expected_setup_revision':True}):
        response=seed_legacy_plan(client, base+'/analysis-plans',json={**body,**changes},headers={'Idempotency-Key':'invalid'})
        assert response.status_code==422,response.text
    assert seed_legacy_plan(client, base+'/analysis-plans',json={**body,'selection':{**body['selection'],'unit':'other'}},headers={'Idempotency-Key':'plan'}).status_code==409
    run_plan(task);view=review_plan(client,task);request=plan_decision(view)
    assert decide_plan(client,task,{**request,'selection':None}).status_code==422
    assert decide_plan(client,task,{**request,'plan_revision':2}).status_code==409
    from app.auth.service import create_user
    create_user('other-plan@paperassist.local','isolated-other-password-2026')
    login=client.post('/api/v1/auth/login',json={'email':'other-plan@paperassist.local','password':'isolated-other-password-2026'})
    client.headers['X-CSRF-Token']=login.json()['csrf_token']
    assert client.get('/api/v1/tasks/'+task['id']+'/analysis-plan').status_code==404
    assert decide_plan(client,task,request).status_code==404


def test_filename_and_revision_origin_tampering_cannot_change_review(client):
    base,_,prepared=prepared_sample(client);task,_=create_plan(client,base,prepared)
    run_plan(task)
    with database_connection(write=True) as db:
        snapshot=db.execute('SELECT input_snapshot FROM tasks WHERE id=%s',(task['id'],)).fetchone()['input_snapshot']
        snapshot['filename']='forged.xlsx'
        db.execute('UPDATE tasks SET input_snapshot=%s WHERE id=%s',(Jsonb(snapshot),task['id']))
    response=client.get('/api/v1/tasks/'+task['id']+'/analysis-plan')
    assert response.status_code==409,response.text


def test_missing_csrf_and_client_plan_reference_are_rejected(client):
    base,_,prepared=prepared_sample(client)
    body=dict(dataset_id=prepared['id'],expected_setup_revision=0,selection=selection(numeric_column='D',group_column='C',unit='mg'))
    response=seed_legacy_plan(client, base+'/analysis-plans',json=body,headers={'Idempotency-Key':'csrf','X-CSRF-Token':'invalid'})
    assert response.status_code==403,response.text
    request=selection(numeric_column='D',group_column='C',unit='mg',dataset_id=prepared['id'],expected_revision=0)
    assert client.put(base+'/analysis-setup',json={**request,'analysis_plan':{'plan_id':'fake','sha256':'a'*64,'resolutions':{}}}).status_code==422
