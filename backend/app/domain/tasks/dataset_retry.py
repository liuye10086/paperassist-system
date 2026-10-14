"""Explicit retry of the immutable first parse input only."""
from datetime import datetime, timezone

from app.adapters.file_objects import LocalFileObjects
from app.core.config import get_data_dir
from app.core.exceptions import StorageError
from app.domain.file_parsing import RETRYABLE_CODES
from app.domain.datasets.snapshots import require_structure_source as require_parse_source


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
