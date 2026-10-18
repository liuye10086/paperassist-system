"""Unified worker entry point and fenced local Word execution."""
import logging
from threading import Event, Thread

from docx.image.exceptions import UnrecognizedImageError, UnexpectedEndOfFileError

from app.adapters.report_docx import build_report
from app.adapters.task_execution_store import TaskExecutionStore, LeaseLost
from app.core.exceptions import StorageError
from app.domain.regression.common import NumericError
from app.domain.tasks.numeric_failure import fail_numeric_task


logger = logging.getLogger(__name__)
SAFE_ERRORS = frozenset({'task_source_conflict', 'task_owner_unavailable', 'file_missing', 'file_changed',
    'figure_missing', 'figure_changed', 'report_missing', 'report_changed', 'storage_unavailable',
    'report_render_failed', 'task_execution_failed', 'source_conflict', 'dataset_missing', 'dataset_changed'})


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
        from app.domain.fixed_statistics_runtime import numeric_execution_scope
        from app.domain.statistics_execution.verification import verification_scope
        with numeric_execution_scope(timeout_seconds=60), verification_scope():
            snapshot, report, png = repository.load(lease)
            try:
                content = build_report(snapshot, report, png)
            except NumericError:
                raise
            except (ValueError, UnrecognizedImageError, UnexpectedEndOfFileError) as exc:
                raise StorageError('report_render_failed', '无法生成 Word 报告，请检查已保存的图片和文字内容后重试。', 422) from exc
            staged = repository.stage(lease, content)
            return repository.complete(lease, snapshot, report, staged, content)
    except LeaseLost:
        return None
    except NumericError as exc:
        return fail_numeric_task(repository, lease, exc)
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
    from app.domain.statistics_execution.execution import run_statistics_task
    def run_projection_task(*args, **kwargs):
        from app.domain.figure_workbench.projection_execution import run_projection_task as execute
        return execute(*args, **kwargs)
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    from app.domain.tasks.dataset_execution import run_dataset_task
    from app.domain.tasks.dataset_preparation_execution import run_preparation_task
    from app.domain.tasks.ocr_review_execution import run_ocr_review_task
    from app.domain.tasks.analysis_plan_execution import run_analysis_plan_task
    from app.domain.tasks.recommendation_execution import run_recommendation_task
    from app.domain.report_collections.execution import run_collection_word_task
    from app.domain.figure_workbench.execution import run_figure_workbench_task, run_figure_explanation_task
    repository = TaskExecutionStore(config=config, directory=directory)
    if not isinstance(task_id, str) or type(task_revision) is not int:
        return None
    with repository.connection() as db:
        task = db.execute('SELECT task_type FROM tasks WHERE id=%s AND revision=%s',
                          (task_id, task_revision)).fetchone()
    if not task:
        return None
    executor = {'figure_projection':run_projection_task,'statistics_compute':run_statistics_task,'figure_workbench':run_figure_workbench_task,'figure_explanation':run_figure_explanation_task,'collection_word_report': run_collection_word_task, 'word_report': run_word_task, 'explanation': run_explanation_task,
                'boxplot': run_boxplot_task, 'parse_file': run_parse_file_task, 'extract_dataset': run_dataset_task,
                'prepare_dataset': run_preparation_task, 'review_ocr': run_ocr_review_task,
                'analysis_plan': run_analysis_plan_task, 'analysis_recommendation':run_recommendation_task}.get(task['task_type'])
    return executor(task_id, task_revision, config=config, directory=directory) if executor else None
