"""Word submission/retry adapters; rendering belongs to the independent worker."""
from datetime import datetime, timezone
import re

from app.adapters.task_store import TaskStore, source_conflict
from app.core.exceptions import StorageError
from app.domain import reports
from app.domain.tasks.contracts import TaskCreateRequest
from app.domain.tasks.service import TaskService


def matching_task(store, project_id, snapshot):
    figure, explanation = snapshot['figure'], snapshot['explanation']
    if not figure or not explanation:
        return None
    from app.adapters.report_docx import VERSION
    with store.connection() as db:
        store.require_project(db, project_id)
        row = db.execute('''SELECT * FROM tasks WHERE project_id=%s AND user_id=%s
            AND task_type='word_report' AND workflow_version='word_report_v1'
            AND input_snapshot->'result'->>'id'=%s
            AND input_snapshot->'figure'->>'id'=%s
            AND input_snapshot->'explanation'->>'id'=%s
            AND input_snapshot->'versions'->>'report'=%s
            ORDER BY created_at DESC,id DESC LIMIT 1''',
            (project_id, store.user_id, snapshot['result']['id'], figure['id'], explanation['id'], VERSION)).fetchone()
        return store.public_task(dict(row)) if row else None


def get_report(project_id, file_id, run_id, project_store):
    snapshot, state = reports.context(project_store, project_id, file_id, run_id)
    return {**state, 'task': matching_task(TaskStore(project_store.owner_id), project_id, snapshot)}


def submit_report(project_id, file_id, run_id, request, project_store, idempotency_key=None):
    key = (f'word-report-v1:{request.explanation_id}:{request.expected_revision}'
           if idempotency_key is None else idempotency_key)
    if not isinstance(key, str) or not re.fullmatch(r'[\x21-\x7e]{1,128}', key):
        raise StorageError('task_input_invalid', '任务请求标识无效，请重新提交。', 422)
    snapshot, state = reports.context(project_store, project_id, file_id, run_id)
    if (not state['ready'] or request.expected_revision != snapshot['result']['setup_revision']
            or request.figure_id != snapshot['figure']['id'] or request.explanation_id != snapshot['explanation']['id']):
        raise StorageError('report_source_conflict', '请先保存配置并完成同一版本的统计、图表和解释，再重新读取报告状态。', 409)
    typed = TaskCreateRequest(task_type='word_report', file_id=file_id, analysis_run_id=run_id,
        expected_revision=request.expected_revision, figure_id=request.figure_id, explanation_id=request.explanation_id)
    service = TaskService(project_store.owner_id)
    if state['report']:
        # Cached content keeps the historical 200 behavior, without synthesizing
        # a task. An explicitly reused request key must still match its input.
        with service.store.connection(write=True) as db:
            project = service.store.require_project(db, project_id)
            service.store.source_snapshot(db, project, typed)
            existing = service.store.find_request(db, project_id, 'word_report', key)
            from app.domain.external_processing import request_digest
            digest = request_digest(typed)
            if existing and existing['input_digest'] != digest:
                raise StorageError('task_idempotency_conflict', '同一请求标识已用于不同输入，请重新读取任务。', 409)
        return {**state, 'task': matching_task(service.store, project_id, snapshot)}, 200
    task, _ = service.create(project_id, typed, idempotency_key=key)
    return {**state, 'task': task}, 202


def retry_word_task(store, task_id, expected_revision):
    with store.connection(write=True) as db:
        task = store.require_task(db, task_id)
        if task['task_type'] != 'word_report':
            raise StorageError('task_transition_invalid', '此任务不支持当前重试操作。', 409)
        repeated = db.execute('''SELECT seq FROM task_events WHERE task_id=%s AND seq=%s
            AND event_type='requeued' AND reason_code='retry_requested' ''',
            (task_id, expected_revision + 1)).fetchone()
        if repeated:
            return store.public_task(task)
        return retry_word_in_transaction(store, db, task, expected_revision)


def retry_word_in_transaction(store, db, task, expected_revision):
    task_id = task["id"]
    if task['revision'] != expected_revision:
        raise StorageError('task_revision_conflict', '任务已发生变化，请重新读取后再操作。', 409)
    if task['status'] != 'failed':
        raise StorageError('task_transition_invalid', '只有失败的 Word 任务可以重试。', 409)
    original = task['input_snapshot']
    request = TaskCreateRequest(task_type='word_report', file_id=original['file']['id'],
        analysis_run_id=original['result']['id'], expected_revision=original['result']['setup_revision'],
        figure_id=original['figure']['id'], explanation_id=original['explanation']['id'])
    current = store.source_snapshot(db, store.require_project(db, task['project_id']), request)
    if any(current[key] != original[key] for key in ('file', 'result', 'figure', 'explanation', 'versions', 'output_language')):
        raise source_conflict()
    task.update(status='queued', phase='export', revision=expected_revision + 1,
        reason_code='retry_requested', error_code=None, retry_count=0, _retry_reason='manual_retry',
        updated_at=max(datetime.now(timezone.utc), task['updated_at']))
    store.update_task(db, task, expected_revision)
    store.append_event(db, task, 'requeued')
    store.enqueue(db, task)
    from app.domain.tasks.waits import resolve_open_wait
    resolve_open_wait(db, task)
    return store.public_task(task)
