"""Local plot acceptance and explicit recovery; HTTP never executes cloud work."""
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from uuid import uuid4

from psycopg.types.json import Jsonb

from app.adapters.task_store import TaskStore, source_conflict
from app.core.exceptions import StorageError
from app.domain.boxplot import RENDERER, STATISTICS_ENGINE, public_job, result_source
from app.domain.tasks.contracts import TaskCreateRequest
from app.domain.tasks.service import TaskService


OUTPUT_FAILURES = frozenset({'plot_result_mismatch', 'plot_invalid_result', 'plot_invalid_image',
    'plot_no_execution', 'plot_files_missing', 'plot_output_limit', 'openai_incomplete', 'plot_container_expired', 'plot_input_limit'})


def matching_task(store, project_id, result):
    with store.connection() as db:
        store.require_project(db, project_id)
        row = db.execute('''SELECT * FROM tasks WHERE project_id=%s AND user_id=%s
            AND task_type='boxplot' AND workflow_version='boxplot_v1'
            AND input_snapshot->'result'->>'id'=%s AND input_snapshot->'versions'->>'figure'=%s
            ORDER BY created_at DESC,id DESC LIMIT 1''',
            (project_id, store.user_id, result['id'], RENDERER)).fetchone()
        return store.public_task(dict(row)) if row else None


def context(project_id, file_id, run_id, store):
    result = result_source(store, project_id, file_id, run_id)
    state = store.figure_state(result, RENDERER, STATISTICS_ENGINE)
    if state['figure']:
        store.figure_png(state['figure'])
    state['job'] = public_job(store.figure_job(run_id, RENDERER))
    return result, state


def get_boxplot(project_id, file_id, run_id, store):
    result, state = context(project_id, file_id, run_id, store)
    state['task'] = matching_task(TaskStore(store.owner_id), project_id, result)
    return state


def _last_call(db, task_id):
    row = db.execute('SELECT * FROM model_calls WHERE task_id=%s ORDER BY created_at DESC,id DESC LIMIT 1',
                     (task_id,)).fetchone()
    return dict(row) if row else None


def _can_resume(task, call):
    return task.get('error_code') not in OUTPUT_FAILURES | {'model_response_not_found'} and (
        call is None or bool(call.get('provider_response_id')) or call['status'] == 'reserved'
        or _acknowledged_preparation(call))


def _acknowledged_preparation(call):
    return call['status'] == 'submitting' and (call.get('provider_state') or {}).get('phase') in (
        'container_ready', 'file_ready')


def _unknown_submission(call):
    return call and not call.get('provider_response_id') and (
        call['status'] == 'submission_unknown' or call['status'] == 'submitting' and not _acknowledged_preparation(call))


def submit_boxplot(project_id, file_id, run_id, request, store, idempotency_key=None):
    result, state = context(project_id, file_id, run_id, store)
    if not state['is_current'] or request.expected_revision != result['setup_revision']:
        raise StorageError('setup_conflict', '配置或统计结果已变化，请重新读取当前结果。', 409)
    if idempotency_key is not None and (not isinstance(idempotency_key, str)
            or not re.fullmatch(r'[\x21-\x7e]{1,128}', idempotency_key)):
        raise StorageError('task_input_invalid', '任务请求标识无效，请重新提交。', 422)
    typed = TaskCreateRequest(task_type='boxplot', file_id=file_id, analysis_run_id=run_id,
                              expected_revision=request.expected_revision)
    service = TaskService(store.owner_id)
    previous = None
    with service.store.connection() as db:
        project = service.store.require_project(db, project_id)
        service.store.source_snapshot(db, project, typed)
        if idempotency_key is not None:
            previous = service.store.find_request(db, project_id, 'boxplot', idempotency_key)
            digest = sha256(json.dumps(typed.model_dump(), ensure_ascii=False, allow_nan=False,
                                      sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
            if previous and previous['input_digest'] != digest:
                raise StorageError('task_idempotency_conflict', '同一请求标识已用于不同输入。', 409)
    task = service.store.public_task(previous) if previous else matching_task(service.store, project_id, result)
    state['task'] = task
    if state['figure']:
        return state, 200
    if previous:
        return state, 202 if task['status'] in ('queued', 'running') else 200
    predecessor = None
    if task:
        if task['status'] != 'failed' or not request.retry:
            return state, 202 if task['status'] in ('queued', 'running') else 200
        if task.get('error_code') == 'model_response_not_found':
            return state, 200
        with service.store.connection() as db:
            call = _last_call(db, task['id'])
        if _can_resume(task, call):
            state['task'] = retry_boxplot_task(service.store, task['id'], task['revision'])
            return state, 202
        if _unknown_submission(call):
            return state, 200
        if task.get('error_code') == 'plot_container_expired' and (not call or
                not call.get('provider_response_id') and not (
                    call['status'] == 'failed' and call.get('error_code') == 'plot_container_expired')):
            return state, 200
        predecessor = task['id']
    elif state['job']:
        legacy = state['job']
        if legacy['status'] != 'failed' or not request.retry:
            return state, 202 if legacy['status'] in ('running', 'submitting') else 200
        predecessor = legacy['id']
    from app.domain.plot_policy import get_execution_policy
    frozen = get_execution_policy()
    source_key = f'{result["id"]}:{request.expected_revision}:{RENDERER}:{predecessor or "initial"}'
    key = idempotency_key or 'boxplot-v1:' + sha256(source_key.encode('utf-8')).hexdigest()
    task, _ = service.create(project_id, typed, idempotency_key=key, boxplot_policy=frozen,
                             plot_predecessor=task['id'] if task else None)
    state['task'] = task
    return state, 202 if task['status'] in ('queued', 'running') else 200


def retry_boxplot_task(store, task_id, expected_revision):
    with store.connection(write=True) as db:
        task = store.require_task(db, task_id)
        if task['task_type'] != 'boxplot':
            raise StorageError('task_transition_invalid', '此任务不支持绘图恢复。', 409)
        repeated = db.execute('''SELECT seq FROM task_events WHERE task_id=%s AND seq=%s
            AND event_type='requeued' AND reason_code IN ('retry_requested','confirmation_received')''',
            (task_id, expected_revision + 1)).fetchone()
        if repeated:
            return store.public_task(task)
        return retry_boxplot_in_transaction(store, db, task, expected_revision)


def retry_boxplot_in_transaction(store, db, task, expected_revision):
    task_id = task["id"]
    if task['revision'] != expected_revision:
        raise StorageError('task_revision_conflict', '任务已变化，请重新读取。', 409)
    budget_wait = task['status'] == 'waiting_confirmation' and task['reason_code'] == 'budget_exceeded'
    call = _last_call(db, task_id)
    if not budget_wait and not (task['status'] == 'failed' and _can_resume(task, call)):
        raise StorageError('task_transition_invalid', '此任务无法安全恢复，请核对已保存的调用状态。', 409)
    if _unknown_submission(call):
        raise StorageError('task_transition_invalid', '提交结果未知，不能自动再次调用。', 409)
    original = task['input_snapshot']
    request = TaskCreateRequest(task_type='boxplot', file_id=original['file']['id'],
        analysis_run_id=original['result']['id'], expected_revision=original['result']['setup_revision'])
    current = store.source_snapshot(db, store.require_project(db, task['project_id']), request)
    if any(current[key] != original[key] for key in ('file', 'result', 'figure', 'versions', 'output_language')):
        raise source_conflict()
    if 'boxplot_policy' not in original:
        if call is not None:
            raise StorageError('task_transition_invalid', '已有模型调用不能替换策略，请联系管理员核对。', 409)
        from app.domain.plot_policy import get_execution_policy
        frozen = get_execution_policy()
        task['input_snapshot'] = {**original, 'boxplot_policy': frozen}
        db.execute('UPDATE tasks SET input_snapshot=%s WHERE id=%s', (Jsonb(task['input_snapshot']), task_id))
        budget = db.execute("SELECT id FROM model_budgets WHERE scope_type='task' AND scope_key=%s", (task_id,)).fetchone()
        if budget is None:
            now = datetime.now(timezone.utc)
            db.execute('''INSERT INTO model_budgets
                (id,user_id,scope_type,scope_key,project_id,task_id,limit_micro_usd,revision,created_at,updated_at)
                VALUES (%s,%s,'task',%s,%s,%s,%s,1,%s,%s)''',
                (str(uuid4()), task['user_id'], task_id, task['project_id'], task_id,
                 frozen['task_limit_micro_usd'], now, now))
    task.update(status='queued', phase='compute', revision=expected_revision + 1,
        reason_code='confirmation_received' if budget_wait else 'retry_requested', error_code=None,
        updated_at=max(datetime.now(timezone.utc), task['updated_at']))
    store.update_task(db, task, expected_revision)
    store.append_event(db, task, 'requeued')
    store.enqueue(db, task)
    from app.domain.tasks.waits import resolve_open_wait
    resolve_open_wait(db, task)
    return store.public_task(task)
