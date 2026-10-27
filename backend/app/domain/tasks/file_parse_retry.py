"""Explicit retry of the immutable first parse input only."""
from datetime import datetime, timezone

from app.adapters.file_objects import LocalFileObjects
from app.core.config import get_data_dir
from app.core.exceptions import StorageError
from app.domain.file_parsing import RETRYABLE_CODES, require_parse_source, sync_file_status
from app.domain.storage_governance.deterministic import STORAGE_RETRY_CODES, authorize_rebuild


def retryable_codes(task):
    return RETRYABLE_CODES | STORAGE_RETRY_CODES if task['workflow_version'] in (
        'docx_document_v1','pdf_document_v1','ocr_document_v1') else RETRYABLE_CODES


def retry_parse_in_transaction(store, db, task, expected_revision):
    if task['task_type'] != 'parse_file' or task['status'] != 'failed' or task.get('error_code') not in retryable_codes(task):
        raise StorageError('task_transition_invalid', '当前解析失败不能安全重试。', 409)
    if task['revision'] != expected_revision:
        raise StorageError('task_revision_conflict', '任务已更新，请重新读取。', 409)
    store.require_project(db, task['project_id'])
    snapshot = require_parse_source(db, task)
    file_id = snapshot['file']['id']
    db.execute('SELECT id FROM files WHERE id=%s FOR UPDATE', (file_id,)).fetchone()
    if db.execute('SELECT id FROM file_parse_results WHERE file_id=%s AND version>%s', (file_id,snapshot.get('parse_version',1))).fetchone():
        raise StorageError('task_transition_invalid', '此解析已被更新版本取代，请使用最新解析。', 409)
    LocalFileObjects(get_data_dir()).original(snapshot['file'])
    if task['workflow_version'] in ('docx_document_v1','pdf_document_v1','ocr_document_v1'):
        import re
        identifier=snapshot['parse_id']
        authorize_rebuild(db,get_data_dir(),task,allowed={'document':('documents',identifier,
            re.escape('document:'+identifier+':')+r'(json|image:.+)')})
    task.update(status='queued', phase='parse', revision=expected_revision+1, error_code=None,
        reason_code='retry_requested', _retry_reason='manual_retry', retry_count=0,
        updated_at=max(datetime.now(timezone.utc), task['updated_at']))
    store.update_task(db, task, expected_revision)
    store.append_event(db, task, 'requeued')
    store.enqueue(db, task)
    if task['workflow_version'] in ('docx_document_v1', 'pdf_document_v1', 'ocr_document_v1'):
        db.execute('UPDATE file_parse_results SET completed_at=NULL WHERE task_id=%s AND result_json IS NULL',(task['id'],))
    sync_file_status(db, task, 'queued')
    return store.public_task(task)


def retry_parse_task(store, task_id, expected_revision):
    with store.connection(write=True) as db:
        task = store.require_task(db, task_id)
        repeated = db.execute("SELECT seq FROM task_events WHERE task_id=%s AND seq=%s AND event_type='requeued' AND reason_code='retry_requested'",
                              (task_id, expected_revision+1)).fetchone()
        if repeated:
            return store.public_task(task)
        return retry_parse_in_transaction(store, db, task, expected_revision)
