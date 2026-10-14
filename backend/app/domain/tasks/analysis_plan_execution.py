"""Finite, model-free plan nodes with durable human waits and lease fencing."""
import logging
from threading import Event,Thread
from app.adapters.task_execution_store import TaskExecutionStore,LeaseLost
from app.adapters.analysis_plan_store import AnalysisPlanStore
from app.core.exceptions import StorageError
from app.core.errors import PUBLIC_CODES
from app.domain.analysis import AnalysisSelection
from app.domain.analysis_plan.checks import build_check

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
    try:
        store=AnalysisPlanStore(repository);task,checkpoint,sheet=store.load(lease)
        if checkpoint['next_node']=='check':
            check=build_check(sheet,AnalysisSelection.model_validate(checkpoint['state_json']['selection'],strict=True))
            return store.wait(lease,checkpoint,check)
        if checkpoint['next_node']=='publish': return store.publish(lease,checkpoint)
        raise StorageError('task_source_conflict','分析计划检查点与状态不一致。',409)
    except LeaseLost: return None
    except Exception as exc:
        code=exc.code if isinstance(exc,StorageError) and exc.code in PUBLIC_CODES else ('storage_unavailable' if isinstance(exc,OSError) else 'task_execution_failed')
        logger.warning('analysis plan failed task_id=%s code=%s',task_id,code)
        try: return repository.fail(lease,code)
        except LeaseLost: return None
    finally:
        stop.set();thread.join(timeout=1)
