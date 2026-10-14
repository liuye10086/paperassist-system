"""Background isolated parser execution; no model or API-process fallback."""
from threading import Event, Thread
import logging

from app.adapters.task_execution_store import TaskExecutionStore, LeaseLost
from app.adapters.dataset_store import DatasetStore
from app.core.errors import PUBLIC_CODES
from app.core.exceptions import StorageError

logger = logging.getLogger(__name__)


def run_dataset_task(task_id, task_revision, *, config=None, directory=None, parser=None):
    repository = TaskExecutionStore(config=config, directory=directory)
    lease = repository.claim(task_id, task_revision, task_type='extract_dataset')
    if lease is None:
        return None
    store = DatasetStore(repository)
    stop = Event()
    def keep_alive():
        while not stop.wait(10):
            try:
                if not repository.heartbeat(lease):
                    return
            except StorageError:
                logger.warning('parse heartbeat unavailable task_id=%s', task_id)
    thread = Thread(target=keep_alive, name='dataset-heartbeat', daemon=True)
    thread.start()
    try:
        snapshot, content = store.load(lease)
        if parser is None:
            from app.adapters.excel_structure_process import parse_excel_structure_isolated
            parser = parse_excel_structure_isolated
        preview = parser(content, snapshot['file']['filename'], snapshot['settings'])
        return store.complete(lease, snapshot, preview)
    except LeaseLost:
        return None
    except Exception as exc:
        code = exc.code if isinstance(exc, StorageError) and exc.code in PUBLIC_CODES else (
            'storage_unavailable' if isinstance(exc, OSError) else 'task_execution_failed')
        logger.warning('parse execution failed task_id=%s code=%s', task_id, code)
        try:
            return store.fail(lease, code)
        except LeaseLost:
            return None
    finally:
        stop.set()
        thread.join(timeout=1)
