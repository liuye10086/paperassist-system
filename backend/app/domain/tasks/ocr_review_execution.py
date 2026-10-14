"""Finite local ocr review execution resumed from a persisted checkpoint."""
import logging
from threading import Event, Thread

from app.adapters.task_execution_store import TaskExecutionStore, LeaseLost
from app.adapters.ocr_review_store import OcrReviewStore
from app.core.exceptions import StorageError
from app.core.errors import PUBLIC_CODES

from app.domain.ocr_review.transform import review_document

logger = logging.getLogger(__name__)


def run_ocr_review_task(task_id,task_revision,*,config=None,directory=None):
    repository = TaskExecutionStore(config=config,directory=directory)
    lease = repository.claim(task_id,task_revision,task_type='review_ocr')
    if lease is None:
        return None
    store = OcrReviewStore(repository)
    stop = Event()
    def keep_alive():
        while not stop.wait(10):
            try:
                if not repository.heartbeat(lease):
                    return
            except StorageError:
                logger.warning('ocr review heartbeat unavailable task_id=%s',task_id)
    thread = Thread(target=keep_alive,name='ocr-review-heartbeat',daemon=True)
    thread.start()
    try:
        task,checkpoint,sheet = store.load(lease)
        state = checkpoint['state_json']
        if checkpoint['next_node'] == 'prepare_preview':
            obj = review_document(sheet,state['input_version']['source'],state['edits'])
            return store.wait(lease,checkpoint,obj)
        if checkpoint['next_node'] == 'publish':
            return store.publish(lease,checkpoint)
        raise StorageError('task_source_conflict','OCR 核对流程检查点与任务状态不一致。',409)
    except LeaseLost:
        return None
    except Exception as exc:
        code = exc.code if isinstance(exc,StorageError) and exc.code in PUBLIC_CODES else (
            'storage_unavailable' if isinstance(exc,OSError) else 'task_execution_failed')
        logger.warning('ocr review execution failed task_id=%s code=%s',task_id,code)
        try:
            return repository.fail(lease,code)
        except LeaseLost:
            return None
    finally:
        stop.set()
        thread.join(timeout=1)
