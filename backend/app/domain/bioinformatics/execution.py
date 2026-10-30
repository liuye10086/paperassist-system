"""One finite leased bio import slice; no network/model or unsafe fallback."""
import logging
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread

from app.adapters.bio_dataset_execution import BioDatasetExecution
from app.adapters.bio_parse_process import parse_bio_isolated
from app.adapters.task_execution_store import LeaseLost, TaskExecutionStore
from app.core.errors import PUBLIC_CODES
from app.core.exceptions import StorageError

logger = logging.getLogger(__name__)


def run_bio_import_task(task_id, task_revision, *, config=None, directory=None, parser=None, staging_directory=None):
    repository = TaskExecutionStore(config=config, directory=directory)
    lease = repository.claim(task_id, task_revision, task_type="bio_import")
    if lease is None:
        return None
    store, stop = BioDatasetExecution(repository), Event()

    def keep_alive():
        while not stop.wait(10):
            try:
                if not repository.heartbeat(lease):
                    return
            except StorageError:
                logger.warning("bio import heartbeat unavailable task_id=%s", task_id)

    thread = Thread(target=keep_alive, name="bio-import-heartbeat", daemon=True)
    thread.start()
    try:
        task, checkpoint, files = store.load(lease)
        if checkpoint["next_node"] == "publish":
            return store.publish(lease, checkpoint)
        if checkpoint["next_node"] != "check":
            raise StorageError("bio_source_conflict", "生信导入检查点与任务状态不一致。", 409)
        # Keep unregistered parsing output outside the project assets ledger;
        # the store admits the whole known leaf set before immutable publication.
        if task['input_snapshot']['workflow_version'] == 'bio_import_v2':
            from app.domain.bioinformatics.analysis_execution import _staging
            _, persistent = _staging(repository, lease, staging_directory)
            manager = nullcontext(str(persistent))
        else:
            manager = TemporaryDirectory(prefix="paperassist-bio-")
        with manager as temporary:
            output = Path(temporary)
            snapshot = task["input_snapshot"]
            frozen = {"parser_version": snapshot["parser_version"], "files": files}
            selected_parser = parser or parse_bio_isolated
            if snapshot['workflow_version'] == 'bio_import_v2':
                from app.adapters.bio_import_v2_process import parse_bio_v2
                frozen.update({key: snapshot[key] for key in ('matrix_representation', 'compare_alternate',
                    'analysis_limits', 'engine_version', 'environment_digest', 'code_digest')})
                selected_parser = parser or parse_bio_v2
            result = selected_parser(frozen, output, snapshot["settings"])
            return store.wait(lease, checkpoint, result)
    except LeaseLost:
        return None
    except Exception as exc:
        code = exc.code if isinstance(exc, StorageError) and exc.code in PUBLIC_CODES else (
            "storage_unavailable" if isinstance(exc, OSError) else "task_execution_failed")
        logger.warning("bio import failed task_id=%s code=%s", task_id, code)
        try:
            return repository.fail(lease, code)
        except LeaseLost:
            return None
    finally:
        stop.set()
        thread.join(timeout=1)


def run_bio_import(task_id, task_revision, settings=None, **kwargs):
    """Compatibility name; parsing always consumes the frozen task settings."""
    if settings is not None:
        raise ValueError("Bio import settings are frozen in the task snapshot")
    return run_bio_import_task(task_id, task_revision, **kwargs)
