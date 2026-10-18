"""Reuse existing task lease/outbox machinery; commit result and completion together."""
import json
import logging
from copy import deepcopy
from threading import Event, Thread
from uuid import uuid4
from app.adapters.storage import ProjectStore
from app.adapters.task_store import TaskStore, source_conflict
from app.adapters.task_execution_store import TaskExecutionStore, LeaseLost
from app.core.config import get_excel_settings
from app.core.exceptions import StorageError
from app.domain.statistics_execution.service import require_snapshot, validate_setup, digest
from app.domain.statistics_execution.verification import computation_scope
from app.domain.fixed_statistics_runtime import numeric_execution_scope, remaining_seconds

logger = logging.getLogger(__name__)


class ComputationStore:
    def __init__(self, assets, snapshot):
        self.assets = assets
        self.snapshot = snapshot

    def __getattr__(self, name):
        return getattr(self.assets, name)

    def analysis_setup(self, project_id, file_id):
        current = self.assets.analysis_setup(project_id, file_id)
        if current != self.snapshot['setup']:
            raise source_conflict()
        return deepcopy(current)

    def analysis_run(self, *args):
        # Always independently reproduce; persisted results never bypass the worker.
        return None

    def save_analysis_run(self, project_id, file_id, result):
        return {**result, 'id': str(uuid4())}


def assets_for(repository, task):
    assets = object.__new__(ProjectStore)
    assets.owner_id = task['user_id']; assets.db_config = repository.config
    assets.directory = repository.assets.directory; assets.objects = repository.assets.objects
    assets.files_dir = repository.assets.files_dir; assets.figures_dir = repository.assets.figures_dir
    return assets


def require_current(repository, db, task, assets):
    repository.require_owner(db, task)
    snapshot = require_snapshot(task)
    record = assets.file(task['project_id'],snapshot['file']['id'])
    if any(record[key]!=value for key,value in snapshot['file'].items()):
        raise source_conflict()
    current = db.execute('SELECT setup_json FROM analysis_setups WHERE file_id=%s', (snapshot['file']['id'],)).fetchone()
    if not current or json.loads(current['setup_json']) != snapshot['setup']:
        raise source_conflict()
    plan = validate_setup(assets, task['project_id'], snapshot['file']['id'], snapshot['setup'], recompute=True)
    if plan != snapshot['plan']:
        raise source_conflict()
    return snapshot


def results_match(existing, candidate):
    from app.domain.descriptive import result_model
    result_model(existing).model_validate(existing, strict=True)
    ignored = {'id','started_at','completed_at','engine','statistics','groups','overall'}
    if {k:v for k,v in existing.items() if k not in ignored} != {k:v for k,v in candidate.items() if k not in ignored}:
        return False
    runtime_fields={'python_version','numpy_version','scipy_version','openpyxl_version','statsmodels_version','execution_contract'}
    if {k:v for k,v in existing['engine'].items() if k not in runtime_fields}!={k:v for k,v in candidate['engine'].items() if k not in runtime_fields}:
        return False
    kind = candidate.get('result_type')
    if kind == 'correlation':
        from app.domain.correlation.service import statistics_match
    elif kind == 'group_comparison':
        from app.domain.comparison.service import statistics_match
        if not statistics_match(existing['groups'],candidate['groups'],summaries=True): return False
    elif kind in ('regression','roc','survival'):
        from app.domain.regression.service import statistics_match
    else:
        return existing.get('overall') == candidate.get('overall') and existing.get('groups') == candidate.get('groups')
    return statistics_match(existing['statistics'],candidate['statistics'])


def complete(repository, lease, assets, candidate, receipt):
    from app.domain.descriptive import result_model
    result_model(candidate).model_validate(candidate,strict=True)
    with repository.connection(write=True) as db:
        task = repository.require_lease(db, lease)
        snapshot = require_current(repository, db, task, assets)
        file_id = snapshot['file']['id']
        if (candidate['file_id']!=file_id or candidate['setup_revision']!=snapshot['setup']['revision']
                or candidate['selection']!=snapshot['setup']['selection']
                or candidate.get('source')!=snapshot['setup'].get('source')
                or candidate.get('analysis_plan')!=snapshot['setup'].get('analysis_plan')):
            raise source_conflict()
        existing = db.execute('SELECT * FROM analysis_runs WHERE file_id=%s AND setup_revision=%s AND engine_version=%s',
            (file_id,candidate['setup_revision'],candidate['engine']['id'])).fetchone()
        if existing:
            saved = assets.analysis_run_value(existing)
            if not results_match(saved, candidate):
                raise source_conflict()
        else:
            saved = candidate
            db.execute('INSERT INTO analysis_runs(id,file_id,setup_revision,engine_version,completed_at,result_json) VALUES (%s,%s,%s,%s,%s,%s)',
                (saved['id'],file_id,saved['setup_revision'],saved['engine']['id'],saved['completed_at'],json.dumps(saved,ensure_ascii=False,allow_nan=False)))
        if remaining_seconds() <= 0:
            from app.domain.regression.common import NumericError
            raise NumericError('numeric_timeout', '统计任务期限已到。')
        # Numerical verification may have consumed the lease: fence immediately before publication.
        repository.require_lease(db, lease)
        from app.domain.fixed_statistics_runtime import execution_receipts
        receipt = {**receipt,'nodes':execution_receipts(),'result_sha256':digest(saved)}
        from app.domain.statistics_execution.verification import validate_statistics_receipt
        validate_statistics_receipt(receipt)
        task.update(result_analysis_run_id=saved['id'],execution_receipt=receipt)
        db.execute('UPDATE projects SET updated_at=GREATEST(updated_at,%s) WHERE id=%s', (saved['completed_at'],task['project_id']))
        repository._finish(db, task, 'succeeded', None)
        return TaskStore.public_task(task)


def run_statistics_task(task_id, task_revision, *, config=None, directory=None):
    repository = TaskExecutionStore(config=config, directory=directory)
    lease = repository.claim(task_id, task_revision, task_type='statistics_compute')
    if lease is None: return None
    stop = Event()
    def keep_alive():
        while not stop.wait(10):
            try:
                if not repository.heartbeat(lease): return
            except StorageError:
                logger.warning('statistics heartbeat unavailable task_id=%s',task_id)
    thread = Thread(target=keep_alive,name='statistics-heartbeat',daemon=True); thread.start()
    scope = None
    try:
        with numeric_execution_scope(timeout_seconds=60) as scope, computation_scope():
            with repository.connection() as db:
                task = repository.require_lease(db,lease)
                assets = assets_for(repository,task)
                snapshot = require_current(repository,db,task,assets)
            from app.domain.descriptive import execute, RunRequest
            candidate = execute(task['project_id'],snapshot['file']['id'],RunRequest(expected_revision=snapshot['setup']['revision']),
                ComputationStore(assets,snapshot),get_excel_settings())
            receipt = dict(schema_version=1,status='succeeded',nodes=scope.execution_receipts(),resource_contract=snapshot['resources'])
            if not receipt['nodes']:
                raise source_conflict()
            return complete(repository,lease,assets,candidate,receipt)
    except LeaseLost:
        return None
    except Exception as exc:
        from app.domain.tasks.errors import safe_error_code
        detail = getattr(exc,'detail',None)
        code = safe_error_code(getattr(exc,'code',None) or (detail.get('code') if isinstance(detail,dict) else None)) or ('storage_unavailable' if isinstance(exc,OSError) else 'task_execution_failed')
        nodes = scope.execution_receipts() if scope else []
        if code=='task_source_conflict' and nodes and nodes[-1].get('error_code') in ('numeric_timeout','numeric_resource_limit','numeric_environment_unavailable'):
            code=nodes[-1]['error_code']
        try:
            with repository.connection(write=True) as db:
                task = repository.require_lease(db,lease)
                task['execution_receipt'] = dict(schema_version=1,status='failed',nodes=nodes,error_code=code)
                repository._finish(db,task,'failed',code)
                return TaskStore.public_task(task)
        except LeaseLost: return None
    finally:
        stop.set(); thread.join(timeout=1)
