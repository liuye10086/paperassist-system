"""Queued projection check and independent approval use the real free Linux consumer."""
from tests.api.test_analysis import client
from tests.integration.test_batch05_figure_store import source
from app.domain.figure_workbench.contracts import SaveConfiguration,ConfirmProjection

def test_projection_http_check_is_queued_and_read_does_not_compute(client,monkeypatch):
    store,project,result=source(client);args=(project,result['file_id'],result['id'])
    saved=store.save(*args,SaveConfiguration(config={'figure_kind':'line','language':'en','projection':{'x_column':'A','y_column':'C'}}));v=saved['version']['id']
    import app.adapters.figure_workbench_store as module
    original=module.calculate
    def forbidden(*a,**k):raise AssertionError('HTTP computed projection')
    monkeypatch.setattr(module,'calculate',forbidden)
    queued=store.check(*args,v)
    assert queued['task']['status']=='queued' and queued['check'] is None
    assert store.check(*args,v)['task']['id']==queued['task']['id']
    assert store.state(*args)['configurations'][0]['projection_task']['status']=='queued'
    monkeypatch.setattr(module,'calculate',original)
    from app.domain.figure_workbench.projection_execution import run_projection_task
    waiting=run_projection_task(queued['task']['id'],queued['task']['revision'])
    assert waiting['status']=='waiting_confirmation',waiting
    checked=store.check(*args,v);assert checked['check']['valid_n']==4 and checked['requires_confirmation']
    monkeypatch.setattr(module,'calculate',forbidden)
    approved=store.confirm(*args,v,ConfirmProjection(input_sha256=checked['input_sha256'],approved=True))
    assert approved['task']['status']=='queued'
    assert store.state(*args)['configurations'][0]['projection'] is None
    monkeypatch.setattr(module,'calculate',original)
    done=run_projection_task(approved['task']['id'],approved['task']['revision'])
    assert done['status']=='succeeded',done
    monkeypatch.setattr('app.domain.figure_workbench.sources.compute_bounded',forbidden)
    entry=store.state(*args)['configurations'][0]
    assert entry['projection']['result']['audit']['valid_n']==4
    assert store.external_preview(*args,v)['payload']['figure_kind']=='line'

def test_projection_environment_failure_is_saved_and_never_auto_replayed(client,monkeypatch):
    store,project,result=source(client);args=(project,result['file_id'],result['id'])
    saved=store.save(*args,SaveConfiguration(config={'figure_kind':'line','language':'en','projection':{'x_column':'A','y_column':'C'}}));v=saved['version']['id']
    from app.domain.regression.common import NumericError
    from app.domain.figure_workbench.projection_execution import run_projection_task
    def unavailable(*a,**k):raise NumericError('numeric_environment_unavailable','Linux unavailable')
    monkeypatch.setattr('app.domain.figure_workbench.sources.compute_bounded',unavailable)
    queued=store.check(*args,v)['task'];failed=run_projection_task(queued['id'],queued['revision'])
    assert failed['status']=='failed' and failed['error_code']=='numeric_environment_unavailable'
    assert failed['execution_receipt']['status']=='failed'
    assert run_projection_task(queued['id'],queued['revision']) is None
    entry=store.state(*args)['configurations'][0]
    assert entry['projection'] is None and entry['projection_task']['id']==queued['id']
    assert store.check(*args,v)['task']['status']=='failed'

def test_legacy_projection_wait_can_finish_asynchronously_and_remains_readable(client):
    from app.db.database import database_connection
    from psycopg.types.json import Jsonb
    from app.domain.figure_workbench.projection_execution import run_projection_task
    from app.domain.external_processing import digest
    store,project,result=source(client);args=(project,result['file_id'],result['id'])
    saved=store.save(*args,SaveConfiguration(config={'figure_kind':'line','language':'en','projection':{'x_column':'A','y_column':'C'}}));v=saved['version']['id']
    queued=store.check(*args,v)['task'];assert run_projection_task(queued['id'],queued['revision'])['status']=='waiting_confirmation'
    checked=store.check(*args,v)
    # Freeze the exact pre-upgrade request/checkpoint shape without inventing results.
    with database_connection(write=True) as db:
        task=db.execute('SELECT * FROM tasks WHERE id=%s',(queued['id'],)).fetchone();snapshot=task['input_snapshot']
        snapshot.pop('projection_execution');snapshot['figure_workbench'].pop('configuration_sha256')
        cp=db.execute('SELECT * FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',(queued['id'],)).fetchone()
        legacy={'version_id':v,'input_sha256':checked['input_sha256'],'check':cp['state_json']['check']}
        db.execute("UPDATE tasks SET workflow_version='figure_projection_v1',input_digest=%s,input_snapshot=%s WHERE id=%s",(checked['input_sha256'],Jsonb(snapshot),queued['id']))
        db.execute('UPDATE task_checkpoints SET state_json=%s WHERE id=%s',(Jsonb(legacy),cp['id']))
    assert store.state(*args)['configurations'][0]['projection_check']['requires_confirmation']
    approved=store.confirm(*args,v,ConfirmProjection(input_sha256=checked['input_sha256'],approved=True))['task']
    done=run_projection_task(approved['id'],approved['revision']);assert done['status']=='succeeded',done
    # A genuine v1 published projection had no newly persisted numerical material.
    with database_connection(write=True) as db:
        row=db.execute('SELECT * FROM figure_projection_results WHERE config_version_id=%s',(v,)).fetchone()
        legacy_result={k:x for k,x in row['result_json'].items() if k!='_material'}
        db.execute('UPDATE figure_projection_results SET result_json=%s,sha256=%s WHERE id=%s',(Jsonb(legacy_result),digest(legacy_result),row['id']))
    assert store.state(*args)['configurations'][0]['projection']['result']==legacy_result
    assert store.external_preview(*args,v)['payload']['figure_kind']=='line'
