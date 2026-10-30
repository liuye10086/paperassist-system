"""Finite leased science slices with durable, private recovery staging."""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Thread
from uuid import UUID, uuid4

from app.adapters.bio_analysis_process import execute_bio_analysis
from app.adapters.task_execution_store import LeaseLost, TaskExecutionStore
from app.core.config import local_config
from app.core.errors import PUBLIC_CODES
from app.core.exceptions import StorageError

logger = logging.getLogger(__name__)


def execution_store(repository):
    # Keep task contracts importable without loading the publication adapter.
    from app.adapters.bio_analysis_execution import BioAnalysisExecution
    return BioAnalysisExecution(repository)


def _staging(repository, lease, configured):
    value = configured or local_config().get('PAPERASSIST_BIO_STAGING_DIR')
    if not value:
        raise StorageError('bio_environment_unavailable', '尚未配置持久生信恢复目录。', 409)
    root = Path(value)
    assets = repository.assets.directory.resolve()
    if not root.is_absolute():
        raise StorageError('bio_environment_unavailable', '生信恢复目录必须是固定绝对路径。', 409)
    for component in [root, *root.parents]:
        if component.is_symlink() or getattr(component, 'is_junction', lambda: False)():
            raise StorageError('bio_environment_unavailable', '生信恢复目录不能经过链接。', 409)
    resolved = root.resolve()
    if resolved.is_relative_to(assets) or assets.is_relative_to(resolved):
        raise StorageError('bio_environment_unavailable', '生信恢复目录必须与正式资产目录分开。', 409)
    task_id = str(UUID(lease.task_id))
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    attempt = root / task_id / (str(lease.attempt_no) + '-' + uuid4().hex)
    attempt.mkdir(parents=True, mode=0o700)
    output = attempt / 'output'
    output.mkdir(mode=0o700)
    return attempt, output


def _receipt(attempt, lease, status):
    if attempt is None:
        return
    value = {'schema_version': 1, 'task_id': lease.task_id, 'attempt_no': lease.attempt_no,
             'status': status, 'at': datetime.now(timezone.utc).isoformat(),
             'retention': 'preserved_for_explicit_recovery_and_batch_acceptance'}
    (attempt / 'receipt.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def run_bio_analysis_task(task_id, task_revision, *, config=None, directory=None,
                          engine=None, staging_directory=None, task_type='bio_analysis'):
    if task_type not in {'bio_analysis', 'bio_figure'}:
        raise ValueError('Unsupported science task type')
    repository = TaskExecutionStore(config=config, directory=directory)
    lease = repository.claim(task_id, task_revision, task_type=task_type)
    if lease is None:
        return None
    stop, lost = Event(), Event()

    def keep_alive():
        while not stop.wait(10):
            try:
                if not repository.heartbeat(lease):
                    lost.set()
                    return
            except StorageError:
                logger.warning('bio analysis heartbeat unavailable task_id=%s', task_id)

    thread = Thread(target=keep_alive, name='bio-analysis-heartbeat', daemon=True)
    thread.start()
    attempt = None
    try:
        store = execution_store(repository)
        task, checkpoint, payload = store.load(lease)
        if checkpoint['next_node'] == 'publish':
            return store.publish_existing(lease, checkpoint)
        stage = checkpoint['state_json'].get('stage')
        if (checkpoint['next_node'] != 'check' or stage not in {'qc', 'compute', 'figure'}
                or (task_type == 'bio_figure') != (stage == 'figure') or task['task_type'] != task_type):
            raise StorageError('bio_source_conflict', '生信任务阶段与固定输入不一致。', 409)
        attempt, output = _staging(repository, lease, staging_directory)
        _receipt(attempt, lease, 'running_' + stage)
        result = (engine or execute_bio_analysis)(payload, output, mode=stage)
        if lost.is_set():
            raise LeaseLost()
        response = store.wait(lease, checkpoint, result) if stage == 'qc' else store.publish_result(lease, checkpoint, result)
        try:
            _receipt(attempt, lease, response['status'])
        except OSError:
            logger.warning('bio analysis runtime receipt unavailable task_id=%s', task_id)
        return response
    except LeaseLost:
        try:
            _receipt(attempt, lease, 'lease_lost')
        except OSError:
            pass
        return None
    except Exception as exc:
        code = exc.code if isinstance(exc, StorageError) and exc.code in PUBLIC_CODES else (
            'storage_unavailable' if isinstance(exc, OSError) else 'task_execution_failed')
        logger.warning('bio analysis failed task_id=%s code=%s', task_id, code)
        try:
            _receipt(attempt, lease, 'failed_' + code)
        except OSError:
            pass
        try:
            return repository.fail(lease, code)
        except LeaseLost:
            return None
    finally:
        stop.set()
        thread.join(timeout=1)


def run_bio_figure_task(task_id, task_revision, **kwargs):
    return run_bio_analysis_task(task_id, task_revision, task_type='bio_figure', **kwargs)
