"""Explicit retry of the immutable first parse input only."""
from datetime import datetime, timezone

from app.adapters.file_objects import LocalFileObjects
from app.core.config import get_data_dir
from app.core.exceptions import StorageError
from app.domain.file_parsing import RETRYABLE_CODES as PARSE_RETRYABLE_CODES
from app.domain.datasets.snapshots import require_structure_source as require_parse_source

# Storage recovery is local and specific to deterministic sheet extraction.
# Do not widen file parsing or any paid/model producer's retry policy.
RETRYABLE_CODES = PARSE_RETRYABLE_CODES | frozenset({
    'storage_quota_exceeded', 'storage_disk_insufficient', 'storage_accounting_unknown'})


def _recover_dataset_candidates(db, task, root):
    """Explicit same-task retry only; never regenerate or replace candidate bytes."""
    from uuid import uuid5
    from app.adapters.dataset_objects import DatasetObjects
    from app.adapters.dataset_store import NAMESPACE as DATASET_NAMESPACE
    from app.domain.storage_governance.service import (
        NAMESPACE, invalid, reconcile_intents, recover_reservation)
    if reconcile_intents(db, root):
        raise invalid()
    candidates = db.execute("SELECT * FROM storage_reservations WHERE task_id=%s AND state IN ('reserved','unknown')",
                            (task['id'],)).fetchall()
    objects = DatasetObjects(root)
    for row in candidates:
        if (row['namespace'] != NAMESPACE or row['kind'] != 'dataset'
                or row['project_id'] != task['project_id'] or row['owner_id'] != task['user_id']):
            raise invalid()
        record = {key: row[key] for key in ('object_key', 'size_bytes', 'sha256')}
        content, obj = objects.read(record)
        identifier = str(uuid5(DATASET_NAMESPACE, task['id'] + ':' + str(obj.sheet.index)))
        if row['operation_key'] != 'dataset:' + identifier or objects.describe(identifier, content) != record:
            raise invalid()
    # All known candidate identities are checked before any settlement. The
    # caller transaction rolls back every settlement if any quota check fails.
    for row in candidates:
        recover_reservation(db, root, row['id'])


def retry_dataset_in_transaction(store, db, task, expected_revision):
    if task['task_type'] != 'extract_dataset' or task['status'] != 'failed' or task.get('error_code') not in RETRYABLE_CODES:
        raise StorageError('task_transition_invalid', '当前解析失败不能安全重试。', 409)
    if task['revision'] != expected_revision:
        raise StorageError('task_revision_conflict', '任务已更新，请重新读取。', 409)
    store.require_project(db, task['project_id'])
    snapshot = require_parse_source(db, task)
    if db.execute('''SELECT id FROM file_structure_versions WHERE file_id=%s AND version>
        (SELECT version FROM file_structure_versions WHERE id=%s)''',
        (snapshot['file']['id'],snapshot['structure_id'])).fetchone():
        raise StorageError('task_source_conflict','已登记后续结构版本，无法安全重试此旧输入。',409)
    if db.execute('''SELECT t.id FROM tasks t JOIN file_structure_versions s ON s.task_id=t.id WHERE s.file_id=%s AND t.id<>%s AND t.status IN ('queued','running')''', (snapshot['file']['id'],task['id'])).fetchone():
        raise StorageError('structure_task_pending', '已有结构任务正在处理。', 409)
    LocalFileObjects(get_data_dir()).original(snapshot['file'])
    _recover_dataset_candidates(db, task, get_data_dir())
    task.update(status='queued', phase='parse', revision=expected_revision+1, error_code=None,
        reason_code='retry_requested', _retry_reason='manual_retry', retry_count=0,
        updated_at=max(datetime.now(timezone.utc), task['updated_at']))
    store.update_task(db, task, expected_revision)
    store.append_event(db, task, 'requeued')
    store.enqueue(db, task)
    db.execute('UPDATE file_structure_versions SET completed_at=NULL WHERE task_id=%s AND manifest_json IS NULL',(task['id'],))
    return store.public_task(task)


def retry_dataset_task(store, task_id, expected_revision):
    with store.connection(write=True) as db:
        task = store.require_task(db, task_id)
        repeated = db.execute("SELECT seq FROM task_events WHERE task_id=%s AND seq=%s AND event_type='requeued' AND reason_code='retry_requested'",
                              (task_id, expected_revision+1)).fetchone()
        if repeated:
            return store.public_task(task)
        return retry_dataset_in_transaction(store, db, task, expected_revision)
