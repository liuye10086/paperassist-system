"""Small synthetic examples with analytically known results; never real data."""
def identity(value):
    return dict(kind='number' if isinstance(value,(int,float)) else 'text',value=str(value))


def prepared_modeling(client,method):
    import copy
    from tests.integration.test_dataset_preparation import create_preparation,run,review,decide,decision
    base,file,_,_,task=create_preparation(client,rows=sample(method))
    run(task);view=review(client,task);recipe=copy.deepcopy(view['recipe'])
    for field in recipe['fields']:
        field['unit']=dict(status='confirmed',value='day' if method=='kaplan_meier' and field['column']==2 else '')
    changed=decide(client,task,decision(view,'revise',recipe),'modeling-prepare-revise').json()
    run(changed)
    confirmed=decide(client,task,decision(review(client,task)),'modeling-prepare-confirm').json()
    assert run(confirmed)['status']=='succeeded'
    return base,file,review(client,task)['result']


def approve(client,task):
    from tests.helpers.analysis_plan import run_plan,review_plan,decide_plan,plan_decision
    assert run_plan(task)['status']=='waiting_confirmation'
    view=review_plan(client,task)
    assert not [i for i in view['check']['issues'] if i['severity']=='blocking'],view['check']
    accepted=decide_plan(client,task,plan_decision(view))
    assert accepted.status_code==202,accepted.text
    assert run_plan(accepted.json())['status']=='succeeded'
    return review_plan(client,task)['result']


def sample(method):
    if method=='ols':
        return [['Outcome','Exposure']]+[[1+2*x+e,x] for x in range(-3,4) for e in (-0.5,0.5)]
    if method=='logistic':
        return [['Outcome','Exposure']]+[[int(i<n),x] for x,n in [(0,5),(1,15)] for i in range(20)]
    if method=='roc_auc':
        return [['Outcome','Score']]+[[y,s] for y,ss in [(1,[0.4,0.5,0.6,0.7,0.8,0.9]),(0,[0.1,0.2,0.3,0.4,0.6,0.7])] for s in ss]
    return [['ID','Time','Status']]+[[f'synthetic-{i}',t,e] for i,(t,e) in enumerate([(0,0),(1,1),(2,1),(2,0),(3,1),(4,0)])]


def selection(method,sheet):
    common=dict(sheet_name=sheet,method=method,missing_policy='complete_cases',
                assumptions=dict(independent_units=True,inference_confirmed=True))
    if method in ('ols','logistic'):
        return dict(**common,task_type='regression',outcome_column='A',
            covariates=[dict(column='B',type='continuous',unit='',levels=[],reference=None)],outcome_unit='',
            positive=identity(1) if method=='logistic' else None,negative=identity(0) if method=='logistic' else None,id_column=None)
    if method=='roc_auc':
        return dict(**common,task_type='roc',outcome_column='A',score_column='B',positive=identity(1),negative=identity(0),
            direction='higher_is_positive',score_kind='probability',score_source='Frozen synthetic instrument',score_version='1',
            formation='Prespecified synthetic scores; no training in this workflow.',evaluation_role='external_validation',
            independence_confirmed=True,outcome_time='At synthetic baseline')
    return dict(**common,task_type='survival',id_column='A',time_column='B',status_column='C',group_column=None,
        event=identity(1),censored=identity(0),groups=[],time_unit='day',time_origin='synthetic entry',noninformative_censoring=True)
