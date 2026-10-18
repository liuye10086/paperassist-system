"""Reusable real-upload preparation → local plan → approval → statistics scenario."""
from tests.helpers.legacy_plans import seed_legacy_plan
from tests.integration.test_dataset_preparation import create_preparation,run,review,decide,decision
from tests.api.test_analysis import selection


def prepared_sample(client):
    rows=[['说明'],[],[None,None,'处理组','读数'],[None,None,'不选此行',900],
        [None,None,' A ',1],[None,None,'NA',3],[None,None,' A ',5],
        [None,None,' B ',7],[None,None,' B ',9],[],['边界标记']]
    base,file,raw,_,initial=create_preparation(client,rows=rows)
    run(initial)
    defaults=client.get(base+'/dataset-versions/'+raw['id']+'/preparation-defaults',params={'header_row':3,'data_range':'C5:D10'}).json()
    recipe=defaults['recipe']; recipe['fields'][0].update(trim_text=True,missing_markers=['NA'])
    recipe['fields'][1].update(name='体重',unit=dict(status='confirmed',value='mg'))
    revised=decide(client,initial,decision(review(client,initial),'revise',recipe),'range').json()
    run(revised)
    approved=decide(client,initial,decision(review(client,initial)),'approve').json()
    assert run(approved)['status']=='succeeded'
    return base,file,review(client,initial)['result']


def create_plan(client,base,prepared,expected=0,key='plan'):
    body=dict(dataset_id=prepared['id'],expected_setup_revision=expected,
        selection=selection(numeric_column='D',group_column='C',unit='mg'))
    response=seed_legacy_plan(client, base+'/analysis-plans',json=body,headers={'Idempotency-Key':key})
    assert response.status_code==202,response.text
    return response.json(),body


def run_plan(task):
    from app.domain.tasks.analysis_plan_execution import run_analysis_plan_task
    return run_analysis_plan_task(task['id'],task['revision'])


def review_plan(client,task):
    response=client.get('/api/v1/tasks/'+task['id']+'/analysis-plan')
    assert response.status_code==200,response.text
    return response.json()


def plan_decision(view,operation='approve',selection=None):
    return dict(operation=operation,expected_task_revision=view['task']['revision'],input_version=view['input_version'],
        checkpoint_id=view['checkpoint_id'],wait_id=view['wait_id'],plan_revision=view['plan_revision'],
        resolutions={i['id']:i['allowed_resolutions'][0] for i in view['check']['issues']} if operation=='approve' else {},
        **({'selection':selection} if operation=='revise' else {}))


def decide_plan(client,task,body,key='plan-decision'):
    return client.post('/api/v1/tasks/'+task['id']+'/analysis-plan/decisions',json=body,headers={'Idempotency-Key':key})


def confirmed_sample(client):
    base,file,prepared=prepared_sample(client)
    task,_=create_plan(client,base,prepared)
    assert run_plan(task)['status']=='waiting_confirmation'
    view=review_plan(client,task)
    accepted=decide_plan(client,task,plan_decision(view))
    assert accepted.status_code==202,accepted.text
    assert run_plan(accepted.json())['status']=='succeeded'
    return base,file,prepared,review_plan(client,task)
