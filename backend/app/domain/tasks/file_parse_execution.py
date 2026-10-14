"""Background isolated parser execution; no model or API-process fallback."""
from threading import Event, Thread
import logging

from app.adapters.task_execution_store import TaskExecutionStore, LeaseLost
from app.adapters.file_parse_store import FileParseStore
from app.core.errors import PUBLIC_CODES
from app.core.exceptions import StorageError

logger = logging.getLogger(__name__)


def run_parse_file_task(task_id, task_revision, *, config=None, directory=None, parser=None, on_started=None):
    repository = TaskExecutionStore(config=config, directory=directory)
    lease = repository.claim(task_id, task_revision, task_type='parse_file')
    if lease is None:
        return None
    store = FileParseStore(repository)
    stop = Event()
    def keep_alive():
        while not stop.wait(10):
            try:
                if not repository.heartbeat(lease):
                    return
            except StorageError:
                logger.warning('parse heartbeat unavailable task_id=%s', task_id)
    thread = Thread(target=keep_alive, name='file-parse-heartbeat', daemon=True)
    thread.start()
    try:
        snapshot, content = store.load(lease)
        if snapshot.get('kind') in ('docx_document', 'pdf_document', 'ocr_document'):
            from app.adapters.document_parse_store import DocumentParseStore
            store = DocumentParseStore(repository)
            if parser is None:
                if snapshot['kind']=='ocr_document':
                    from app.adapters.ocr_process import parse_ocr_isolated
                    parser=parse_ocr_isolated
                elif snapshot['kind'] == 'pdf_document':
                    from app.adapters.pdf_process import parse_pdf_isolated
                    # Dispatch from the frozen parser identity; retries never silently upgrade v1.
                    from functools import partial
                    parser = partial(parse_pdf_isolated, parser_version=snapshot['parser_version'])
                else:
                    from app.adapters.docx_process import parse_docx_isolated
                    parser = parse_docx_isolated
        if parser is None:
            from app.adapters.excel_process import parse_excel_isolated
            parser = parse_excel_isolated
        if snapshot['kind']=='ocr_document':
            kwargs={'on_started':on_started} if on_started is not None else {}
            preview=parser(content,snapshot['file']['filename'],snapshot['file']['file_type'],snapshot['page_numbers'],snapshot['settings'],**kwargs)
        else:
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
