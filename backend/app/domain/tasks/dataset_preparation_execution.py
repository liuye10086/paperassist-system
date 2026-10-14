"""Finite local preparation execution resumed from a persisted checkpoint."""
import logging
from threading import Event, Thread

from app.adapters.task_execution_store import TaskExecutionStore, LeaseLost
from app.adapters.dataset_preparation_store import DatasetPreparationStore
from app.core.exceptions import StorageError
from app.core.errors import PUBLIC_CODES
from app.domain.dataset_preparation.contracts import PreparationRecipe
from app.domain.dataset_preparation.transform import prepare_dataset

logger = logging.getLogger(__name__)


def run_preparation_task(task_id,task_revision,*,config=None,directory=None):
    repository = TaskExecutionStore(config=config,directory=directory)
    lease = repository.claim(task_id,task_revision,task_type='prepare_dataset')
    if lease is None:
        return None
    store = DatasetPreparationStore(repository)
    stop = Event()
    def keep_alive():
        while not stop.wait(10):
            try:
                if not repository.heartbeat(lease):
                    return
            except StorageError:
                logger.warning('preparation heartbeat unavailable task_id=%s',task_id)
    thread = Thread(target=keep_alive,name='preparation-heartbeat',daemon=True)
    thread.start()
    try:
        task,checkpoint,sheet = store.load(lease)
        state = checkpoint['state_json']
        if checkpoint['next_node'] == 'prepare_preview':
            obj = prepare_dataset(sheet,state['input_version']['source'],PreparationRecipe.model_validate(state['recipe']))
            return store.wait(lease,checkpoint,obj)
        if checkpoint['next_node'] == 'publish':
            return store.publish(lease,checkpoint)
        raise StorageError('task_source_conflict','整理流程检查点与任务状态不一致。',409)
    except LeaseLost:
        return None
    except Exception as exc:
        code = exc.code if isinstance(exc,StorageError) and exc.code in PUBLIC_CODES else (
            'storage_unavailable' if isinstance(exc,OSError) else 'task_execution_failed')
        logger.warning('preparation execution failed task_id=%s code=%s',task_id,code)
        try:
            return repository.fail(lease,code)
        except LeaseLost:
            return None
    finally:
        stop.set()
        thread.join(timeout=1)
