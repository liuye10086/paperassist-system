"""Finite, model-free plan nodes with durable human waits and lease fencing."""
import logging
from app.domain.statistics_execution.verification import local_numeric_node
from threading import Event,Thread
from app.adapters.task_execution_store import TaskExecutionStore,LeaseLost
from app.adapters.analysis_plan_store import AnalysisPlanStore
from app.core.exceptions import StorageError
from app.core.errors import PUBLIC_CODES
from app.domain.correlation.contracts import parse_selection
from app.domain.analysis_plan.checks import build_check
from app.domain.fixed_statistics_runtime import numeric_execution_scope
from app.adapters.task_store import TaskStore

logger=logging.getLogger(__name__)


def run_analysis_plan_task(task_id,task_revision,*,config=None,directory=None):
    repository=TaskExecutionStore(config=config,directory=directory)
    lease=repository.claim(task_id,task_revision,task_type='analysis_plan')
    if lease is None: return None
    stop=Event()
    def keep_alive():
        while not stop.wait(10):
            try:
                if not repository.heartbeat(lease): return
            except StorageError:
                logger.warning('plan heartbeat unavailable task_id=%s',task_id)
    thread=Thread(target=keep_alive,name='analysis-plan-heartbeat',daemon=True);thread.start()
    scope=None
    try:
        with numeric_execution_scope(timeout_seconds=60) as scope:return _run_plan_node(repository,lease)
    except LeaseLost: return None
    except Exception as exc:
        code=exc.code if getattr(exc,'code',None) in PUBLIC_CODES else ('storage_unavailable' if isinstance(exc,OSError) else 'task_execution_failed')
        logger.warning('analysis plan failed task_id=%s code=%s',task_id,code)
        try:
            with repository.connection(write=True) as db:
                task=repository.require_lease(db,lease)
                task['execution_receipt']={'schema_version':1,'status':'failed','error_code':code,'nodes':scope.execution_receipts() if scope else []}
                repository._finish(db,task,'failed',code)
                return TaskStore.public_task(task)
        except LeaseLost:return None
    finally:
        stop.set();thread.join(timeout=1)


@local_numeric_node
def _run_plan_node(repository,lease):
    store=AnalysisPlanStore(repository);task,checkpoint,sheet=store.load(lease)
    if checkpoint['next_node']=='check':
        if task['workflow_version'] in ('analysis_plan_v4','analysis_plan_v5'):
            from app.domain.analysis_plan.requirements import requirement_check
            state=checkpoint['state_json']
            options = dict(schema_version=5,source_resolution=state.get('source_resolution')) if task['workflow_version']=='analysis_plan_v5' else {}
            check=requirement_check(task['input_snapshot']['source'],state['selection'],state['research_request'],sheet,**options)
            return store.wait(lease,checkpoint,check)
        check=build_check(sheet,parse_selection(checkpoint['state_json']['selection']),checkpoint['state_json'].get('research_request'),schema_version=task['input_snapshot']['schema_version'])
        return store.wait(lease,checkpoint,check)
    if checkpoint['next_node']=='publish': return store.publish(lease,checkpoint)
    raise StorageError('task_source_conflict','分析计划检查点与状态不一致。',409)
