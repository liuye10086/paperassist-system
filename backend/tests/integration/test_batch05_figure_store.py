from tests.helpers.projection import check_projection,confirm_projection
from tests.helpers.statistics import statistics_post
import copy
import pytest
from tests.api.test_analysis import client
from tests.integration.test_correlation_plan import prepared_correlations,create_correlation
from tests.helpers.analysis_plan import run_plan,review_plan,plan_decision,decide_plan
from tests.helpers.tasks import task_owner
from app.adapters.storage import ProjectStore
from app.core.config import get_data_dir
from app.adapters.figure_workbench_store import FigureWorkbenchStore
from app.domain.figure_workbench.contracts import SaveConfiguration,ConfirmProjection
from app.db.database import database_connection


def source(client):
    base,_,prepared=prepared_correlations(client)
    task,_=create_correlation(client,base,prepared);run_plan(task)
    approved=decide_plan(client,task,plan_decision(review_plan(client,task))).json();run_plan(approved)
    result=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).json()
    store=ProjectStore(get_data_dir(),owner_id=task_owner(client))
    return FigureWorkbenchStore(store),task['project_id'],result


def test_projection_wait_confirmation_does_not_modify_analysis_setup(client):
    store,project,result=source(client);args=(project,result['file_id'],result['id'])
    config={'figure_kind':'line','language':'en','projection':{'x_column':'A','y_column':'C'}}
    saved=store.save(*args,SaveConfiguration(config=config))
    version=saved['version']['id'];check=check_projection(store,*args,version)
    assert check['check']['valid_n']==4 # Original correlation n is three, independent projection n is four.
    assert check['task']['status']=='waiting_confirmation'
    with database_connection() as db:before=dict(db.execute('SELECT * FROM analysis_setups WHERE file_id=%s',(result['file_id'],)).fetchone())
    projection=confirm_projection(store,*args,version,ConfirmProjection(input_sha256=check['input_sha256'],approved=True))
    assert projection['result']['audit']['valid_n']==4
    assert confirm_projection(store,*args,version,ConfirmProjection(input_sha256=check['input_sha256'],approved=True))['id']==projection['id']
    with database_connection() as db:
        after=dict(db.execute('SELECT * FROM analysis_setups WHERE file_id=%s',(result['file_id'],)).fetchone())
        wait=db.execute('SELECT * FROM task_waits WHERE task_id=%s',(check['task']['id'],)).fetchone()
        assert wait['status']=='resolved'
    assert before==after
    payload=store.external_preview(*args,version)['payload']
    assert not any('row' in entry for entry in payload['observations'])


def test_style_version_reuses_projection_but_has_new_identity(client):
    store,project,result=source(client);args=(project,result['file_id'],result['id'])
    config={'figure_kind':'violin','language':'en','projection':{'y_column':'C'}}
    saved=store.save(*args,SaveConfiguration(config=config));v=saved['version']['id'];check=check_projection(store,*args,v)
    first=confirm_projection(store,*args,v,ConfirmProjection(input_sha256=check['input_sha256'],approved=True))
    config['style']={'palette':'gray'}
    second=store.save(*args,SaveConfiguration(configuration_id=saved['id'],expected_revision=1,config=config))
    assert second['version']['id']!=v
    assert second['projection']['id']==first['id']
    assert check_projection(store,*args,second['version']['id'])['requires_confirmation'] is False


def test_projection_approval_receipt_corruption_is_rejected(client):
    from app.core.exceptions import StorageError
    store,project,result=source(client);args=(project,result['file_id'],result['id'])
    saved=store.save(*args,SaveConfiguration(config={'figure_kind':'line','language':'en','projection':{'x_column':'A','y_column':'C'}}));v=saved['version']['id'];check=check_projection(store,*args,v)
    confirm_projection(store,*args,v,ConfirmProjection(input_sha256=check['input_sha256'],approved=True))
    with database_connection(write=True) as db:db.execute("UPDATE figure_projection_decisions SET decision_json=jsonb_set(decision_json,'{approved}','false') WHERE config_version_id=%s",(v,))
    with pytest.raises(StorageError):store.external_preview(*args,v)

def test_historical_confirmed_result_remains_usable_after_current_setup_changes(client):
    store,project,result=source(client);args=(project,result['file_id'],result['id'])
    saved=store.save(*args,SaveConfiguration(config={'figure_kind':'line','language':'en','projection':{'x_column':'A','y_column':'C'}}));v=saved['version']['id'];check=check_projection(store,*args,v)
    confirm_projection(store,*args,v,ConfirmProjection(input_sha256=check['input_sha256'],approved=True))
    with database_connection(write=True) as db:db.execute('UPDATE analysis_setups SET revision=revision+1 WHERE file_id=%s',(result['file_id'],))
    assert store.external_preview(*args,v)['payload']['figure_kind']=='line'


def test_http_draft_missing_field_error_and_owner_scoped_state(client):
    store,project,result=source(client)
    base=f"/api/v1/projects/{project}/files/{result['file_id']}/analysis-runs/{result['id']}/figure-workbench"
    response=client.post(base+'/configurations',json={'config':{'figure_kind':'line','language':'en'}})
    assert response.status_code==200,response.text
    vid=response.json()['version']['id'];failed=client.post(base+f'/versions/{vid}/check')
    assert failed.status_code==202,failed.text
    from app.domain.figure_workbench.projection_execution import run_projection_task
    task=failed.json()['task'];done=run_projection_task(task['id'],task['revision'])
    assert done['status']=='failed' and done['error_code']=='figure_projection_invalid'
    assert done['execution_receipt']['params']['reason']=='missing_fields'
    state=client.get(base);assert state.status_code==200,state.text
    assert state.json()['configurations'][0]['version']['id']==vid


@pytest.mark.parametrize('kind,rules,expected_n',[
    ('line',{'x_column':'A','y_column':'C','x_type':'ordered','x_order':[1,2,3,4],'expected_x':[1,2,3,4]},4),
    ('bar',{'category_column':'C','bar_stat':'proportion','included_categories':[7,8,9]},3),
])
def test_http_browser_integer_categories_match_source_numbers_without_rewriting_config(client,kind,rules,expected_n):
    store,project,result=source(client)
    base=f"/api/v1/projects/{project}/files/{result['file_id']}/analysis-runs/{result['id']}/figure-workbench"
    response=client.post(base+'/configurations',json={'config':{'figure_kind':kind,'language':'en','projection':rules}})
    assert response.status_code==200,response.text
    version=response.json()['version'];vid=version['id']
    with database_connection() as db:before=dict(db.execute('SELECT * FROM figure_config_versions WHERE id=%s',(vid,)).fetchone())
    category_rule='x_order' if kind=='line' else 'included_categories'
    assert type(before['config_json']['projection'][category_rule][0]) is int
    checked=client.post(base+f'/versions/{vid}/check')
    assert checked.status_code==202,checked.text
    from app.domain.figure_workbench.projection_execution import run_projection_task
    task=checked.json()['task'];assert run_projection_task(task['id'],task['revision'])['status']=='waiting_confirmation'
    checked=client.post(base+f'/versions/{vid}/check')
    assert checked.status_code==200,checked.text
    assert checked.json()['check']['valid_n']==expected_n
    confirmed=client.post(base+f'/versions/{vid}/confirm',json={'input_sha256':checked.json()['input_sha256'],'approved':True})
    assert confirmed.status_code==202,confirmed.text
    task=confirmed.json()['task'];assert run_projection_task(task['id'],task['revision'])['status']=='succeeded'
    confirmed=client.post(base+f'/versions/{vid}/confirm',json={'input_sha256':checked.json()['input_sha256'],'approved':True})
    assert confirmed.status_code==200,confirmed.text
    points=confirmed.json()['result']['series'][0]['points']
    if kind=='line':
        assert [p['x'] for p in points]==[1.,2.,3.,4.]
        assert [p['y'] for p in points]==[9.,8.,7.,6.]
        assert all(type(p['x']) is float for p in points)
    else:
        assert [p['category'] for p in points]==[7.,8.,9.]
        assert [p['denominator'] for p in points]==[3,3,3]
        assert all(p['value']==pytest.approx(1/3) for p in points)
    assert client.post(base+f'/versions/{vid}/external-preview').status_code==200
    with database_connection() as db:after=dict(db.execute('SELECT * FROM figure_config_versions WHERE id=%s',(vid,)).fetchone())
    assert after==before
    assert after['sha256']==version['sha256']

def test_projection_read_preserves_frozen_numbers_across_platform_roundoff(client,monkeypatch):
    import math
    from app.domain.figure_workbench import sources
    store,project,result=source(client);args=(project,result['file_id'],result['id'])
    saved=store.save(*args,SaveConfiguration(config={'figure_kind':'violin','language':'en','projection':{'y_column':'C'}}));v=saved['version']['id'];check=check_projection(store,*args,v)
    frozen=confirm_projection(store,*args,v,ConfirmProjection(input_sha256=check['input_sha256'],approved=True))
    original=sources.compute_bounded
    def other_platform(*args,**kwargs):
        computed=original(*args,**kwargs)
        computed['series'][0]['density'][0]=math.nextafter(computed['series'][0]['density'][0],0.)
        return computed
    monkeypatch.setattr(sources,'compute_bounded',other_platform)
    from app.domain.statistics_execution.verification import verification_scope
    with verification_scope():_,_,computed,_,expected=store.material(*args,v)
    assert computed==frozen['result']
    assert expected['statistics']['series']==frozen['result']['series']
    from app.core.exceptions import StorageError
    mutations=[
        lambda p:p['series'][0]['density'].__setitem__(0,p['series'][0]['density'][0]*1.001),
        lambda p:p['series'][0].__setitem__('group','forged'),
        lambda p:p['audit'].__setitem__('valid_n',99),
        lambda p:p['series'][0].__setitem__('n',float(p['series'][0]['n'])),
    ]
    for mutate in mutations:
        def corrupted(*args,**kwargs):
            computed=original(*args,**kwargs);mutate(computed);return computed
        monkeypatch.setattr(sources,'compute_bounded',corrupted)
        with verification_scope(),pytest.raises(StorageError) as error:store.material(*args,v)
        assert error.value.code=='task_source_conflict'
