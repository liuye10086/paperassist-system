import hashlib
import json
from uuid import uuid4
from contextlib import nullcontext
from app.adapters.task_store import TaskStore, source_conflict
from app.core.exceptions import StorageError

WORKFLOW = 'statistics_compute_v1'
RESOURCE_CONTRACT = {'version': 'fixed_statistics_v2', 'sandbox_version': 'fixed_statistics_linux_v1_as1073741824_cpu30_wall30', 'timeout_seconds': 60, 'memory_bytes':1073741824, 'cpu_seconds':30, 'cpu_affinity_count':1, 'paid': False}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def input_version(task):
    snapshot = require_snapshot(task)
    setup = snapshot['setup']
    plan = setup.get('analysis_plan') or {}
    return dict(kind='statistics_compute', setup_revision=setup['revision'], output_language=snapshot['output_language'],
        source=setup.get('source'), analysis_plan_id=plan.get('plan_id') or plan.get('id'), workflow_version=WORKFLOW)


def require_snapshot(task):
    try:
        snapshot = task['input_snapshot']
        if (task['workflow_version'] != WORKFLOW or set(snapshot) != {'schema_version','file','setup','plan','resources','output_language'}
                or type(snapshot['schema_version']) is not int or snapshot['schema_version'] != 1
                or snapshot['resources'] != RESOURCE_CONTRACT or digest(snapshot) != task['input_digest']
                or snapshot['file']['id'] != snapshot['setup']['file_id']
                or snapshot['file']['sha256'] != snapshot['setup']['source_sha256']):
            raise source_conflict()
        return snapshot
    except (KeyError,TypeError,ValueError) as exc:
        raise source_conflict() from exc


def validate_setup(store, project_id, file_id, setup, *, recompute=False):
    from app.domain.analysis_plan.service import validate_plan_reference
    from app.domain.dataset_analysis import load_dataset
    from app.domain.analysis import source
    if setup.get('source') is not None:
        if not setup.get('analysis_plan'):
            raise source_conflict()
        load_dataset(store, project_id, file_id, setup['source']['dataset_id'], expected_source=setup['source'])
    else:
        if setup.get('schema_version') is not None or setup['selection']['task_type'] != 'descriptive_boxplot':
            raise source_conflict()
        source(store, project_id, file_id)
    # v5 validates read-only by default; the worker explicitly asks for numerical verification.
    return validate_plan_reference(store, project_id, file_id, setup, recompute=recompute)


def create(project_id, file_id, request, assets, *, db=None):
    """Optionally commit the public queue with its caller's persisted intent."""
    scoped = TaskStore(assets.owner_id, assets.db_config)
    with (nullcontext(db) if db is not None else scoped.connection(write=True)) as db:
        project = scoped.require_project(db, project_id)
        row = db.execute('SELECT setup_json FROM analysis_setups WHERE file_id=%s', (file_id,)).fetchone()
        if not row:
            raise StorageError('setup_conflict', '分析配置尚未保存。', 409)
        setup = json.loads(row['setup_json'])
        if setup['revision'] != request.expected_revision:
            raise StorageError('setup_conflict', '分析配置已变化，请重新读取。', 409)
        record = assets.file(project_id, file_id)
        plan = validate_setup(assets, project_id, file_id, setup)
        from app.domain.artifact_contracts import artifact_language
        snapshot = dict(schema_version=1, file={'id':file_id,'filename':record['filename'],'sha256':record['sha256']},
            setup=setup, plan=plan, resources=RESOURCE_CONTRACT, output_language=(plan.get('research_request',{}).get('output_language','zh-CN') if plan else artifact_language(setup)))
        fingerprint = digest(snapshot)
        key = request.idempotency_key or fingerprint
        existing = scoped.find_request(db, project_id, 'statistics_compute', key)
        if existing:
            if existing['input_digest'] != fingerprint:
                raise StorageError('task_idempotency_conflict', '同一请求标识已用于不同输入。', 409)
            return scoped.public_task(existing)
        now = db.execute('SELECT clock_timestamp() AS now').fetchone()['now']
        task = dict(id=str(uuid4()),project_id=project_id,user_id=assets.owner_id,task_type='statistics_compute',
            idempotency_key=key,input_digest=fingerprint,input_snapshot=snapshot,workflow_version=WORKFLOW,
            status='queued',phase='compute',revision=1,current_attempt=0,reason_code=None,created_at=now,updated_at=now)
        scoped.insert_task(db, task); scoped.append_event(db, task, 'created'); scoped.enqueue(db, task)
        return scoped.public_task(task)


def retry_in_transaction(store, db, task, expected_revision):
    if task['revision'] != expected_revision:
        raise StorageError('task_revision_conflict', '任务已变化。', 409)
    if task['status'] != 'failed' or task.get('error_code') not in ('storage_unavailable','task_worker_interrupted'):
        raise StorageError('task_transition_invalid', '此统计失败须修正输入或运行环境后重新提交。', 409)
    snapshot = require_snapshot(task)
    row = db.execute('SELECT setup_json FROM analysis_setups WHERE file_id=%s', (snapshot['file']['id'],)).fetchone()
    if not row or json.loads(row['setup_json']) != snapshot['setup']:
        raise source_conflict()
    task.update(status='queued',revision=expected_revision+1,reason_code='retry_requested',error_code=None,
        execution_receipt=None,updated_at=db.execute('SELECT clock_timestamp() AS now').fetchone()['now'])
    store.update_task(db, task, expected_revision); store.append_event(db, task, 'requeued'); store.enqueue(db,task)
    return store.public_task(task)
