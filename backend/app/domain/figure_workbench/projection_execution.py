"""Bounded, lease-fenced free projections; HTTP never executes a numerical kernel."""
from copy import deepcopy
from threading import Event,Thread
from uuid import uuid5,NAMESPACE_URL
from psycopg.types.json import Jsonb
from app.adapters.task_execution_store import TaskExecutionStore,LeaseLost
from app.adapters.task_store import TaskStore,source_conflict
from app.adapters.figure_workbench_store import FigureWorkbenchStore,projection_request_digest,validate_projection_checkpoint,_same_projection_value
from app.domain.figure_workbench.tasks import assets_for
from app.domain.dataset_preparation.service import append_checkpoint
from app.domain.external_processing import digest
from app.domain.statistics_execution.verification import local_numeric_node
from app.domain.fixed_statistics_runtime import execution_receipts,numeric_execution_scope
from app.domain.regression.common import NumericError
from app.core.exceptions import StorageError

@local_numeric_node
def _node(repository,lease):
    with repository.connection() as db:
        task=repository.require_lease(db,lease);repository.require_owner(db,task)
        checkpoint=db.execute('SELECT * FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',(task['id'],)).fetchone()
        state=validate_projection_checkpoint(task,checkpoint)
    workbench=FigureWorkbenchStore(assets_for(repository,task['user_id']));frozen=task['input_snapshot']['result'];vid=state['version_id']
    row,result,computed,payload,expected=workbench.material(task['project_id'],frozen['file_id'],frozen['id'],vid)
    if (result!=frozen or (projection_request_digest(row) if task['workflow_version']=='figure_projection_v2' else computed['input_sha256'])!=task['input_digest']
        or task['workflow_version']=='figure_projection_v2' and row['sha256']!=task['input_snapshot']['figure_workbench']['configuration_sha256']):raise source_conflict()
    with repository.connection(write=True) as db:
        task=repository.require_lease(db,lease);repository.require_owner(db,task)
        current=db.execute('SELECT * FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',(task['id'],)).fetchone()
        if current['id']!=checkpoint['id']:raise source_conflict()
        now=max(repository.now(db),task['updated_at']);task['updated_at']=now
        if checkpoint['next_node']=='check':
            state.update(check=computed,payload=payload,expected=expected,material_sha256=digest({'check':computed,'payload':payload,'expected':expected}),execution_nodes=execution_receipts())
            revision=task['revision'];task.update(status='waiting_confirmation',revision=revision+1,reason_code='confirmation_required',phase='compute',error_code=None)
            append_checkpoint(db,task,'check','await_confirmation',state,dict(checkpoint))
            repository.require_lease(db,lease)
            TaskStore.finish_attempt(db,task);TaskStore.update_task(db,task,revision);TaskStore.append_event(db,task,'waiting')
            from app.domain.tasks.waits import persist_wait
            persist_wait(db,task)
            return TaskStore.public_task(task)
        if checkpoint['next_node']!='publish' or not _same_projection_value(computed,state['check']) or task['workflow_version']=='figure_projection_v2' and (payload!=state['payload'] or expected!=state['expected']):raise source_conflict()
        decision=db.execute('SELECT * FROM figure_projection_decisions WHERE id=%s AND task_id=%s',(state['decision_id'],task['id'])).fetchone()
        if not decision:raise source_conflict()
        receipt=decision['decision_json']
        reviewed=db.execute('SELECT * FROM task_checkpoints WHERE id=%s AND task_id=%s',(receipt.get('checkpoint_id'),task['id'])).fetchone()
        wait=db.execute('SELECT * FROM task_waits WHERE id=%s AND task_id=%s',(receipt.get('wait_id'),task['id'])).fetchone()
        if (receipt.get('approved') is not True or receipt.get('input_sha256')!=computed['input_sha256']
            or decision['config_version_id']!=vid or decision['approved_by']!=task['user_id']
            or not reviewed or reviewed['next_node']!='await_confirmation' or (validate_projection_checkpoint(task,reviewed)['material_sha256']!=state['material_sha256'] if task['workflow_version']=='figure_projection_v2' else reviewed['state_json']['check']!=state['check'])
            or not wait or wait['status']!='resolved' or wait['kind']!='figure_projection_confirmation'
            or wait['task_revision']!=receipt['expected_task_revision'] or wait['resolved_task_revision']!=receipt['expected_task_revision']+1):raise source_conflict()
        if task['workflow_version']=='figure_projection_v1':state.update(payload=payload,expected=expected,material_sha256=digest({'check':computed,'payload':payload,'expected':expected}))
        published={**deepcopy(state['check']),'_material':{'payload':deepcopy(payload),'expected':deepcopy(expected),'sha256':digest({'payload':payload,'expected':expected})}}
        pid=str(uuid5(NAMESPACE_URL,'paperassist:projection:'+task['id']))
        db.execute('INSERT INTO figure_projection_results(id,config_version_id,decision_id,tool_version,sha256,result_json,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)',
            (pid,vid,decision['id'],computed['tool_version'],digest(published),Jsonb(published),now))
        append_checkpoint(db,task,'publish','done',{**state,'projection_id':pid},dict(checkpoint))
        task['execution_receipt']={'schema_version':1,'status':'succeeded','nodes':execution_receipts(),'projection_sha256':digest(published),'material_sha256':state['material_sha256']}
        repository.require_lease(db,lease)
        repository._finish(db,task,'succeeded',None)
        return TaskStore.public_task(task)

def run_projection_task(task_id,task_revision,*,config=None,directory=None):
    repository=TaskExecutionStore(config=config,directory=directory);lease=repository.claim(task_id,task_revision,task_type='figure_projection')
    if lease is None:return None
    stop=Event()
    def heartbeat():
        while not stop.wait(10):
            try:
                if not repository.heartbeat(lease):return
            except StorageError:return
    thread=Thread(target=heartbeat,daemon=True);thread.start()
    scope=None
    try:
        with numeric_execution_scope(timeout_seconds=60) as scope:return _node(repository,lease)
    except LeaseLost:return None
    except (StorageError,NumericError) as exc:
        from app.core.errors import safe_params
        with repository.connection(write=True) as db:
            task=repository.require_lease(db,lease)
            task['execution_receipt']={'schema_version':1,'status':'failed','nodes':scope.execution_receipts() if scope else [],'error_code':exc.code,'params':safe_params(exc.code,getattr(exc,'params',{}))}
            repository._finish(db,task,'failed',exc.code)
            return TaskStore.public_task(task)
    except Exception:
        return repository.fail(lease,'task_execution_failed')
    finally:stop.set();thread.join(timeout=1)
