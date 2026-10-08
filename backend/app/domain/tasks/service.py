"""Internal task operations. No provider, dispatcher, or HTTP write entry point."""
from datetime import datetime, timezone
import hashlib
import json
import re
from uuid import uuid4

from pydantic import ValidationError

from app.core.exceptions import StorageError
from app.domain.tasks.contracts import TaskCreateRequest


_UNSPECIFIED_PREDECESSOR = object()


def validate_transition(old, new, reason):
    allowed = {
        ('queued', 'running'): {None}, ('running', 'running'): {None},
        ('running', 'succeeded'): {None}, ('running', 'failed'): {'execution_failed'},
        ('running', 'waiting_input'): {'input_required'},
        ('running', 'waiting_confirmation'): {'confirmation_required', 'submission_unknown', 'budget_exceeded'},
        ('waiting_input', 'queued'): {'input_provided'},
        ('waiting_confirmation', 'queued'): {'confirmation_received'},
        ('failed', 'queued'): {'retry_requested'},
    }
    if reason not in allowed.get((old, new), set()):
        raise StorageError('task_transition_invalid', '当前任务状态不允许此操作，请重新读取任务。', 409)


class TaskService:
    def __init__(self, user_id, config=None):
        from app.adapters.task_store import TaskStore
        self.store = TaskStore(user_id, config)

    def create(self, project_id, request, *, idempotency_key, explanation_policy=None,
               explanation_predecessor=_UNSPECIFIED_PREDECESSOR, boxplot_policy=None,
               plot_predecessor=_UNSPECIFIED_PREDECESSOR):
        try:
            # Revalidate copied/model-constructed values at this internal boundary too.
            request = TaskCreateRequest.model_validate(
                request.model_dump() if isinstance(request, TaskCreateRequest) else request)
        except (ValidationError, TypeError, ValueError) as exc:
            raise StorageError('task_input_invalid', '任务输入无效，请重新选择同一版本的资料。', 422) from exc
        if not isinstance(idempotency_key, str) or not re.fullmatch(r'[\x21-\x7e]{1,128}', idempotency_key):
            raise StorageError('task_input_invalid', '任务请求标识无效，请重新提交。', 422)
        digest = hashlib.sha256(json.dumps(request.model_dump(), ensure_ascii=False, allow_nan=False,
                                          sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
        with self.store.connection(write=True) as db:
            project = self.store.require_project(db, project_id)
            existing = self.store.find_request(db, project_id, request.task_type, idempotency_key)
            if existing:
                if existing['input_digest'] != digest:
                    raise StorageError('task_idempotency_conflict', '同一请求标识已用于不同输入，请重新读取任务。', 409)
                return self.store.public_task(existing), False
            snapshot = self.store.source_snapshot(db, project, request)
            if plot_predecessor is not _UNSPECIFIED_PREDECESSOR:
                if request.task_type != 'boxplot':
                    raise StorageError('task_input_invalid', '任务来源条件无效。', 422)
                latest = db.execute('''SELECT id,status FROM tasks
                    WHERE project_id=%s AND user_id=%s AND task_type='boxplot'
                      AND workflow_version='boxplot_v1' AND input_snapshot->'result'->>'id'=%s
                      AND input_snapshot->'versions'->>'figure'=%s
                    ORDER BY created_at DESC,id DESC LIMIT 1''',
                    (project_id, self.store.user_id, request.analysis_run_id, snapshot['versions']['figure'])).fetchone()
                if ((latest['id'] if latest else None) != plot_predecessor
                        or (latest is not None and latest['status'] != 'failed')):
                    raise StorageError('task_revision_conflict', '此来源的绘图任务已变化，请重新读取后操作。', 409)
            if explanation_predecessor is not _UNSPECIFIED_PREDECESSOR:
                if request.task_type != 'explanation':
                    raise StorageError('task_input_invalid', '任务来源条件无效。', 422)
                # HTTP callers observe a source before obtaining this write lock.
                # A second header must not authorize another paid task in that gap.
                latest = db.execute('''SELECT id,status FROM tasks
                    WHERE project_id=%s AND user_id=%s AND task_type='explanation'
                      AND workflow_version='explanation_v1'
                      AND input_snapshot->'result'->>'id'=%s
                      AND input_snapshot->'figure'->>'id'=%s
                      AND input_snapshot->'versions'->>'explanation'=%s
                    ORDER BY created_at DESC,id DESC LIMIT 1''',
                    (project_id, self.store.user_id, request.analysis_run_id, request.figure_id,
                     snapshot['versions']['explanation'])).fetchone()
                if ((latest['id'] if latest else None) != explanation_predecessor
                        or (latest is not None and latest['status'] != 'failed')):
                    raise StorageError('task_revision_conflict', '此来源的解释任务已变化，请重新读取后操作。', 409)
            if request.task_type == 'explanation':
                from app.domain.explanation_content import build_payload
                from app.domain.explanation_policy import get_execution_policy, validate_execution_policy
                payload = build_payload(snapshot['result'], snapshot['figure'])
                if explanation_policy is not None:
                    frozen_policy = validate_execution_policy(explanation_policy, payload)
                else:
                    try:
                        frozen_policy = get_execution_policy(payload)
                    except StorageError as exc:
                        if exc.code != 'explanation_not_configured':
                            raise
                        # The generic task contract may persist work before configuration.
                        frozen_policy = None
                if frozen_policy is not None:
                    snapshot['explanation_policy'] = frozen_policy
            if request.task_type == 'boxplot':
                from app.domain.plot_policy import get_execution_policy, validate_execution_policy
                if boxplot_policy is not None:
                    frozen_policy = validate_execution_policy(boxplot_policy)
                else:
                    try:
                        frozen_policy = get_execution_policy()
                    except StorageError as exc:
                        if exc.code != 'plot_not_configured':
                            raise
                        frozen_policy = None
                if frozen_policy is not None:
                    snapshot['boxplot_policy'] = frozen_policy
            now = datetime.now(timezone.utc)
            task = dict(id=str(uuid4()), project_id=project_id, user_id=self.store.user_id,
                        task_type=request.task_type, idempotency_key=idempotency_key, input_digest=digest,
                        input_snapshot=snapshot, workflow_version=request.task_type + '_v1', status='queued',
                        phase={'boxplot': 'compute', 'explanation': 'interpret', 'word_report': 'export'}[request.task_type],
                        revision=1, current_attempt=0, reason_code=None, created_at=now, updated_at=now)
            self.store.insert_task(db, task)
            frozen_budget = snapshot.get('explanation_policy') or snapshot.get('boxplot_policy')
            if frozen_budget is not None:
                db.execute('''INSERT INTO model_budgets
                    (id,user_id,scope_type,scope_key,project_id,task_id,limit_micro_usd,
                     revision,created_at,updated_at) VALUES (%s,%s,'task',%s,%s,%s,%s,1,%s,%s)''',
                    (str(uuid4()), self.store.user_id, task['id'], project_id, task['id'],
                     frozen_budget['task_limit_micro_usd'], now, now))
            self.store.append_event(db, task, 'created')
            self.store.enqueue(db, task)
            return self.store.public_task(task), True

    def transition(self, task_id, *, expected_revision, status, phase=None, reason_code=None):
        phases = {'parse', 'plan', 'compute', 'search', 'interpret', 'write', 'export', 'verify'}
        if (type(expected_revision) is not int or not 1 <= expected_revision < 2_147_483_647
                or not isinstance(status, str)
                or (phase is not None and (not isinstance(phase, str) or phase not in phases))
                or (reason_code is not None and not isinstance(reason_code, str))):
            raise StorageError('task_transition_invalid', '任务状态参数无效，请重新读取任务。', 409)
        with self.store.connection(write=True) as db:
            task = self.store.require_task(db, task_id)
            if task['revision'] != expected_revision:
                raise StorageError('task_revision_conflict', '任务已发生变化，请重新读取后再操作。', 409)
            target_phase = phase if phase is not None else task['phase']
            if (status, target_phase, reason_code) == (task['status'], task['phase'], task['reason_code']):
                return self.store.public_task(task)
            validate_transition(task['status'], status, reason_code)
            if target_phase != task['phase'] and status != 'running':
                raise StorageError('task_transition_invalid', '只有执行中的任务可以变更处理阶段。', 409)
            now = max(datetime.now(timezone.utc), task['updated_at'])
            old_status = task['status']
            task.update(status=status, phase=target_phase, reason_code=reason_code,
                        revision=task['revision'] + 1, updated_at=now)
            if old_status == 'queued':
                task['current_attempt'] += 1
                self.store.start_attempt(db, task)
                event_type = 'started'
            elif status == 'queued':
                self.store.enqueue(db, task)
                event_type = 'requeued'
            elif status == 'running':
                event_type = 'phase_changed'
            else:
                self.store.finish_attempt(db, task)
                event_type = 'waiting' if status.startswith('waiting_') else status
            self.store.update_task(db, task, expected_revision)
            self.store.append_event(db, task, event_type)
            from app.domain.tasks.waits import persist_wait, resolve_open_wait
            if status.startswith('waiting_'):
                persist_wait(db, task)
            elif old_status.startswith('waiting_'):
                resolve_open_wait(db, task, status='resolved' if status == 'queued' else 'superseded')
            return self.store.public_task(task)
