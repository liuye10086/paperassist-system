"""Unified worker entry point and fenced local Word execution."""
import logging
from threading import Event, Thread

from docx.image.exceptions import UnrecognizedImageError, UnexpectedEndOfFileError

from app.adapters.report_docx import build_report
from app.adapters.task_execution_store import TaskExecutionStore, LeaseLost
from app.core.exceptions import StorageError


logger = logging.getLogger(__name__)
SAFE_ERRORS = frozenset({'task_source_conflict', 'task_owner_unavailable', 'file_missing', 'file_changed',
    'figure_missing', 'figure_changed', 'report_missing', 'report_changed', 'storage_unavailable',
    'report_render_failed', 'task_execution_failed'})


def run_word_task(task_id, task_revision, *, config=None, directory=None):
    repository = TaskExecutionStore(config=config, directory=directory)
    lease = repository.claim(task_id, task_revision, task_type='word_report')
    if lease is None:
        return None
    stop = Event()
    def keep_alive():
        while not stop.wait(10):
            try:
                if not repository.heartbeat(lease):
                    return
            except StorageError:
                # A failed heartbeat cannot grant ownership; finalization rechecks expiry.
                logger.warning('task heartbeat unavailable task_id=%s attempt=%s', task_id, lease.attempt_no)
    thread = Thread(target=keep_alive, name='word-task-heartbeat', daemon=True)
    thread.start()
    staged = None
    try:
        snapshot, report, png = repository.load(lease)
        try:
            content = build_report(snapshot, report, png)
        except (ValueError, UnrecognizedImageError, UnexpectedEndOfFileError) as exc:
            raise StorageError('report_render_failed', '无法生成 Word 报告，请检查已保存的图片和文字内容后重试。', 422) from exc
        staged = repository.stage(lease, content)
        return repository.complete(lease, snapshot, report, staged, content)
    except LeaseLost:
        return None
    except Exception as exc:
        code = exc.code if isinstance(exc, StorageError) and exc.code in SAFE_ERRORS else (
            'storage_unavailable' if isinstance(exc, OSError) else 'task_execution_failed')
        logger.warning('task execution failed task_id=%s attempt=%s code=%s', task_id, lease.attempt_no, code)
        try:
            return repository.fail(lease, code)
        except LeaseLost:
            return None
    finally:
        stop.set()
        thread.join(timeout=1)
        if staged is not None:
            try:
                staged.unlink(missing_ok=True)
            except OSError:
                logger.warning('task temporary cleanup pending task_id=%s attempt=%s', task_id, lease.attempt_no)


def run_explanation_task(task_id, task_revision, **kwargs):
    from app.domain.tasks.explanation_execution import run_explanation_task as execute
    return execute(task_id, task_revision, **kwargs)


def run_boxplot_task(task_id, task_revision, **kwargs):
    from app.domain.tasks.boxplot_execution import run_boxplot_task as execute
    return execute(task_id, task_revision, **kwargs)


def run_task(task_id, task_revision, *, config=None, directory=None):
    repository = TaskExecutionStore(config=config, directory=directory)
    if not isinstance(task_id, str) or type(task_revision) is not int:
        return None
    with repository.connection() as db:
        task = db.execute('SELECT task_type FROM tasks WHERE id=%s AND revision=%s',
                          (task_id, task_revision)).fetchone()
    if not task:
        return None
    executor = {'word_report': run_word_task, 'explanation': run_explanation_task,
                'boxplot': run_boxplot_task}.get(task['task_type'])
    return executor(task_id, task_revision, config=config, directory=directory) if executor else None
