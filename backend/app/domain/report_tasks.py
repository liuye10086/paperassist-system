"""Word submission/retry adapters; rendering belongs to the independent worker."""
from datetime import datetime, timezone
import re

from app.adapters.task_store import TaskStore, source_conflict, workflow_version, snapshots_match, task_source_matches
from app.core.exceptions import StorageError
from app.domain import reports
from app.domain.tasks.contracts import TaskCreateRequest
from app.domain.tasks.service import TaskService


def matching_task(store, project_id, snapshot):
    figure, explanation = snapshot['figure'], snapshot['explanation']
    if not figure or not explanation:
        return None
    from app.domain.statistics_reader_reports.legacy_exports import RENDERER as reader_renderer
    with store.connection() as db:
        store.require_project(db, project_id)
        row = db.execute('''SELECT * FROM tasks WHERE project_id=%s AND user_id=%s
            AND task_type='word_report' AND workflow_version=%s
            AND input_snapshot->'result'->>'id'=%s
            AND input_snapshot->'figure'->>'id'=%s
            AND input_snapshot->'explanation'->>'id'=%s
            AND input_snapshot->'versions'->>'report'=%s
            ORDER BY created_at DESC,id DESC LIMIT 1''',
            (project_id, store.user_id, workflow_version('word_report', snapshot), snapshot['result']['id'], figure['id'], explanation['id'], reader_renderer)).fetchone()
        if row and not task_source_matches(row, snapshot['result']):
            raise source_conflict()
        return store.public_task(dict(row)) if row else None


def get_report(project_id, file_id, run_id, project_store):
    snapshot, state = reports.context(project_store, project_id, file_id, run_id,archive=True)
    return {**state, 'task': matching_task(TaskStore(project_store.owner_id), project_id, snapshot)}


def submit_report(project_id, file_id, run_id, request, project_store, idempotency_key=None):
    key = (f'word-report-r3:{request.explanation_id}:{request.expected_revision}'
           if idempotency_key is None else idempotency_key)
    if not isinstance(key, str) or not re.fullmatch(r'[\x21-\x7e]{1,128}', key):
        raise StorageError('task_input_invalid', '任务请求标识无效，请重新提交。', 422)
    typed = TaskCreateRequest(task_type='word_report', file_id=file_id, analysis_run_id=run_id,
        expected_revision=request.expected_revision, figure_id=request.figure_id, explanation_id=request.explanation_id)
    service = TaskService(project_store.owner_id)
    with service.store.connection() as db:
        existing=service.store.find_request(db,project_id,'word_report',key)
        if existing:
            from app.domain.external_processing import request_digest
            if existing['input_digest']!=request_digest(typed):
                raise StorageError('task_idempotency_conflict','同一请求标识已用于不同输入。',409)
    snapshot, state = reports.context(project_store, project_id, file_id, run_id,archive=bool(existing))
    if existing:
        if existing.get('result_report_id'):
            from app.adapters.report_store import ReportStore
            state['report']=ReportStore(project_store).by_id(project_id,file_id,run_id,existing['result_report_id'])
        return {**state,'task':service.store.public_task(existing)}, 200 if existing['status']=='succeeded' else 202
    if (not state['ready'] or request.expected_revision != snapshot['result']['setup_revision']
            or request.figure_id != snapshot['figure']['id'] or request.explanation_id != snapshot['explanation']['id']):
        raise StorageError('report_source_conflict', '请先保存配置并完成同一版本的统计、图表和解释，再重新读取报告状态。', 409)
    typed = TaskCreateRequest(task_type='word_report', file_id=file_id, analysis_run_id=run_id,
        expected_revision=request.expected_revision, figure_id=request.figure_id, explanation_id=request.explanation_id)
    service = TaskService(project_store.owner_id)
    task, _ = service.create(project_id, typed, idempotency_key=key)
    return {**state, 'task': task}, 200 if state['report'] else 202



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
    from app.domain.statistics_reader_reports.legacy_exports import is_reader_export
    if is_reader_export(task):
        from app.domain.research_results.execution import retry_in_transaction
        return retry_in_transaction(store,db,task,expected_revision)
    original = task['input_snapshot']
    request = TaskCreateRequest(task_type='word_report', file_id=original['file']['id'],
        analysis_run_id=original['result']['id'], expected_revision=original['result']['setup_revision'],
        figure_id=original['figure']['id'], explanation_id=original['explanation']['id'])
    current = store.source_snapshot(db, store.require_project(db, task['project_id']), request)
    if not snapshots_match(current, original, explanation=True):
        raise source_conflict()
    from app.domain.storage_governance import export_candidates
    from app.core.config import get_data_dir
    export_candidates.authorize(db,get_data_dir(),task)
    task.update(status='queued', phase='export', revision=expected_revision + 1,
        reason_code='retry_requested', error_code=None, retry_count=0, _retry_reason='manual_retry',
        updated_at=max(datetime.now(timezone.utc), task['updated_at']))
    store.update_task(db, task, expected_revision)
    store.append_event(db, task, 'requeued')
    store.enqueue(db, task)
    from app.domain.tasks.waits import resolve_open_wait
    resolve_open_wait(db, task)
    return store.public_task(task)
