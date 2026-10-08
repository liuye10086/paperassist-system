"""Unified admission and accounting. All database effects fit one short transaction."""
from datetime import datetime, timezone
import hashlib
import json
import re
from uuid import uuid4

from pydantic import ValidationError

from app.adapters.model_usage_store import ModelUsageStore
from app.core.exceptions import StorageError
from app.domain.model_usage.contracts import CallRequest, MAX_ACCOUNTED_MICRO_USD, MAX_MICRO_USD, PriceSnapshot
from app.domain.model_usage.pricing import estimate_usage, reserve_micro_usd

TERMINAL = {'completed', 'incomplete', 'failed', 'cancelled'}


def _error(code, message, status=409):
    return StorageError(code, message, status)


def _key(value, maximum=128):
    return isinstance(value, str) and bool(re.fullmatch(r'[\x21-\x7e]{1,' + str(maximum) + '}', value))


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


class ModelUsageService:
    def __init__(self, user_id, config=None):
        self.store = ModelUsageStore(user_id, config)

    def get_budget(self, scope_type, scope_key):
        if scope_type not in ('user', 'project', 'task') or not _key(scope_key, 64):
            raise _error('model_usage_input_invalid', '预算查询参数无效。', 422)
        with self.store.connection() as db:
            self.store.require_scope(db, scope_type, scope_key)
            return self.store.budget_view(db, scope_type, self.store.budget(db, scope_type, scope_key))

    def set_budget(self, scope_type, scope_key, limit_micro_usd, expected_revision):
        if (scope_type not in ('user', 'project', 'task') or not _key(scope_key, 64)
                or type(limit_micro_usd) is not int or not 0 <= limit_micro_usd <= MAX_MICRO_USD
                or type(expected_revision) is not int or not 0 <= expected_revision < 2_147_483_647):
            raise _error('model_usage_input_invalid', '预算参数无效。', 422)
        with self.store.connection(write=True) as db:
            project, task = self.store.require_scope(db, scope_type, scope_key)
            budget = self.store.budget(db, scope_type, scope_key)
            if expected_revision != (budget['revision'] if budget else 0):
                raise _error('model_budget_revision_conflict', '预算版本已变化，请重新读取。')
            now = datetime.now(timezone.utc)
            if budget:
                db.execute('''UPDATE model_budgets SET limit_micro_usd=%s,revision=revision+1,
                    updated_at=%s WHERE id=%s''', (limit_micro_usd, now, budget['id']))
            else:
                db.execute('''INSERT INTO model_budgets
                    (id,user_id,scope_type,scope_key,project_id,task_id,limit_micro_usd,
                     revision,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,1,%s,%s)''',
                    (str(uuid4()), self.store.user_id, scope_type, scope_key, project, task,
                     limit_micro_usd, now, now))
            return self.store.budget_view(db, scope_type, self.store.budget(db, scope_type, scope_key))

    @staticmethod
    def _require_running(task, revision):
        if task['revision'] != revision:
            raise _error('task_revision_conflict', '任务版本已变化，请重新读取。')
        if task['status'] != 'running' or task['task_type'] == 'word_report':
            raise _error('task_transition_invalid', '当前任务不能执行模型调用。')

    @staticmethod
    def _require_execution_lease(db, task, lease):
        from app.adapters.task_execution_store import LeaseLost, TaskLease
        if not isinstance(lease, TaskLease) or lease.task_id != task['id']:
            raise LeaseLost()
        row = db.execute('''SELECT a.id FROM task_attempts a
            WHERE a.task_id=%s AND a.attempt_no=%s AND a.attempt_no=%s
              AND a.status='running' AND a.lease_owner=%s AND a.lease_expires_at>clock_timestamp()''',
            (task['id'], task['current_attempt'], lease.attempt_no, lease.lease_owner)).fetchone()
        if row is None or task['status'] != 'running':
            raise LeaseLost()

    def reserve_call(self, request, execution_lease=None):
        try:
            request = CallRequest.model_validate(request.model_dump() if isinstance(request, CallRequest) else request)
            reserved = reserve_micro_usd(request.policy, request.input_token_allowance,
                                         request.tool_reserve_micro_usd)
        except (ValidationError, TypeError, ValueError) as exc:
            raise _error('model_usage_input_invalid', '模型调用参数或价格无效。', 422) from exc
        policy = {**request.policy.model_dump(), 'input_token_allowance': request.input_token_allowance,
                  'tool_reserve_micro_usd': request.tool_reserve_micro_usd,
                  'tool_reserve_version': request.tool_reserve_version}
        with self.store.connection(write=True) as db:
            task = self.store.require_task(db, request.task_id)
            if execution_lease is not None:
                self._require_execution_lease(db, task, execution_lease)
                self._require_running(task, request.expected_task_revision)
            row = db.execute('SELECT * FROM model_calls WHERE task_id=%s AND call_key=%s',
                             (request.task_id, request.call_key)).fetchone()
            if row:
                existing = dict(row)
                old_policy = {key: value for key, value in existing['policy_snapshot'].items()
                              if key != 'expected_task_revision'}
                old_policy.setdefault('output_format', 'text')
                old_policy.setdefault('tool_reserve_version', None)
                if existing['input_digest'] != request.input_digest or old_policy != policy:
                    raise _error('model_call_idempotency_conflict', '同一调用标识已用于不同输入或策略。')
                return existing
            self._require_running(task, request.expected_task_revision)
            budgets = []
            for scope, key in [('user', self.store.user_id), ('project', task['project_id']), ('task', task['id'])]:
                budget = self.store.budget(db, scope, key)
                if not budget:
                    raise _error('model_budget_missing', '模型调用所需预算尚未配置。')
                if self.store.budget_view(db, scope, budget)['available_micro_usd'] < reserved:
                    raise _error('model_budget_exceeded', '模型调用预算不足。')
                budgets.append(budget)
            now = datetime.now(timezone.utc)
            policy['expected_task_revision'] = request.expected_task_revision
            call = dict(id=str(uuid4()), user_id=self.store.user_id, project_id=task['project_id'],
                task_id=task['id'], attempt_no=task['current_attempt'], call_key=request.call_key,
                input_digest=request.input_digest, provider='openai', model=request.policy.model,
                policy_snapshot=policy, price_snapshot=request.policy.price.model_dump(), status='reserved',
                provider_status=None, provider_request_id=None, provider_response_id=None, error_code=None,
                estimated_cost_micro_usd=None, usage_status='pending', created_at=now, updated_at=now)
            self.store.insert_call(db, call)
            for budget in budgets:
                db.execute('''INSERT INTO budget_reservations
                    (call_id,budget_id,reserved_micro_usd,accounted_micro_usd,status,updated_at)
                    VALUES (%s,%s,%s,0,'held',%s)''', (call['id'], budget['id'], reserved, now))
            return call

    def begin_submission(self, call_id, execution_lease=None, expected_task_revision=None):
        with self.store.connection(write=True) as db:
            call = self.store.require_call(db, call_id)
            if call['status'] != 'reserved':
                return False
            task = self.store.require_task(db, call['task_id'])
            revision = call['policy_snapshot']['expected_task_revision']
            if execution_lease is not None:
                self._require_execution_lease(db, task, execution_lease)
                if expected_task_revision is not None:
                    revision = expected_task_revision
            self._require_running(task, revision)
            call.update(status='submitting', updated_at=datetime.now(timezone.utc))
            self.store.update_call(db, call)
            return True

    def get_call(self, call_id):
        with self.store.connection() as db:
            return self.store.require_call(db, call_id)

    def begin_plot_step(self, call_id, step, *, execution_lease, expected_task_revision):
        """Commit a single POST fence before returning permission to use the network."""
        phases = {'container': (None, 'container_creating'),
                  'upload': ('container_ready', 'file_uploading'),
                  'response': ('file_ready', 'response_creating')}
        if step not in phases:
            raise _error('model_usage_input_invalid', '图表执行阶段无效。', 422)
        with self.store.connection(write=True) as db:
            call = self.store.require_call(db, call_id)
            task = self.store.require_task(db, call['task_id'])
            self._require_execution_lease(db, task, execution_lease)
            self._require_running(task, expected_task_revision)
            policy = call['policy_snapshot']
            if (task['task_type'] != 'boxplot' or policy.get('tools') != ['code_interpreter']
                    or not policy.get('tool_reserve_version') or policy.get('tool_reserve_micro_usd', 0) <= 0):
                raise _error('model_usage_input_invalid', '图表调用必须配置工具预算。', 422)
            state = dict(call.get('provider_state') or {})
            previous, following = phases[step]
            if (call['provider_response_id'] or state.get('phase') != previous
                    or call['status'] != ('reserved' if step == 'container' else 'submitting')):
                return False
            # Excel reconstruction happens outside a write transaction. Recheck
            # its frozen sources under the same lock that authorizes this POST.
            from app.adapters.task_execution_store import TaskExecutionStore
            TaskExecutionStore(config=self.store.config).sources(db, task)
            state.update(version=1, phase=following)
            call.update(provider_state=state, status='submitting', updated_at=datetime.now(timezone.utc))
            self.store.update_call(db, call)
            return True

    def record_plot_step(self, call_id, step, *, container_id=None, input_file_id=None,
                         input_file_path=None, request_id=None):
        """Save known side effects even if their worker lease expired during the POST."""
        from app.adapters.models.openai_plot import CONTAINER_ID, FILE_ID, valid_file_path
        if request_id is not None and not _key(request_id, 256):
            raise _error('model_usage_input_invalid', '图表回执标识无效。', 422)
        if step == 'container' and isinstance(container_id, str) and CONTAINER_ID.fullmatch(container_id):
            before, after = 'container_creating', 'container_ready'
            values = dict(container_id=container_id, container_request_id=request_id)
        elif (step == 'upload' and isinstance(input_file_id, str) and FILE_ID.fullmatch(input_file_id)
                and valid_file_path(input_file_path)):
            before, after = 'file_uploading', 'file_ready'
            values = dict(input_file_id=input_file_id, input_file_path=input_file_path, upload_request_id=request_id)
        else:
            raise _error('model_usage_input_invalid', '图表供应商回执无效。', 422)
        with self.store.connection(write=True) as db:
            call = self.store.require_call(db, call_id)
            state = dict(call.get('provider_state') or {})
            # Duplicate acknowledgements must never overwrite IDs or roll phases back.
            identifiers = {key: value for key, value in values.items() if not key.endswith('request_id')}
            if all(state.get(key) == value for key, value in identifiers.items()):
                return call
            if (state.get('phase') != before or call['provider_response_id']
                    or call['status'] not in ('submitting', 'submission_unknown')):
                raise _error('model_call_transition_invalid', '图表执行回执与已保存阶段不一致。')
            state.update(values, phase=after)
            call.update(provider_state=state, status='submitting', error_code=None,
                        updated_at=datetime.now(timezone.utc))
            self.store.update_call(db, call)
            return call

    def fail_plot_preparation(self, call_id, *, error_code, request_id=None):
        """A definite upload-to-expired-container response is not a lost POST receipt."""
        if error_code != 'plot_container_expired' or (request_id is not None and not _key(request_id, 256)):
            raise _error('model_usage_input_invalid', '图表准备失败回执无效。', 422)
        with self.store.connection(write=True) as db:
            call = self.store.require_call(db, call_id)
            state = dict(call.get('provider_state') or {})
            if call['status'] == 'failed' and call['error_code'] == error_code:
                return call
            if (call['provider_response_id'] or state.get('phase') != 'file_uploading'
                    or call['status'] not in ('submitting', 'submission_unknown')):
                raise _error('model_call_transition_invalid', '图表准备失败与已保存阶段不一致。')
            if request_id is not None:
                state['upload_request_id'] = request_id
            call.update(status='failed', error_code=error_code, provider_state=state,
                        updated_at=datetime.now(timezone.utc))
            self.store.update_call(db, call)
            # A container was created; its unknown tool cost remains held in every budget.
            return call

    def mark_submission_unknown(self, call_id, *, error_code, request_id=None):
        if not _key(error_code) or (request_id is not None and not _key(request_id, 256)):
            raise _error('model_usage_input_invalid', '模型提交状态参数无效。', 422)
        with self.store.connection(write=True) as db:
            call = self.store.require_call(db, call_id)
            if call['status'] in ('completed', 'failed', 'released'):
                return call
            # A lost COMMIT acknowledgement must not erase a durable receipt.
            # Read it again under the write lock before declaring uncertainty.
            if (call.get('provider_response_id') or (call['status'] == 'submitting'
                    and (call.get('provider_state') or {}).get('phase') in ('container_ready', 'file_ready'))):
                return call
            if call['status'] not in ('submitting', 'submitted', 'submission_unknown'):
                raise _error('model_call_transition_invalid', '此调用尚未开始提交。')
            call.update(status='submission_unknown', error_code=error_code,
                        updated_at=datetime.now(timezone.utc))
            if request_id is not None:
                call['provider_request_id'] = request_id
            self.store.update_call(db, call)
            return call

    def record_response(self, call_id, *, event_key, response_id, request_id, model,
                        status, usage, tool_cost_micro_usd=None):
        if (not _key(event_key) or not _key(response_id, 256) or not _key(model)
                or (request_id is not None and not _key(request_id, 256))
                or not isinstance(status, str) or status not in TERMINAL | {'queued', 'in_progress'}
                or (tool_cost_micro_usd is not None and (type(tool_cost_micro_usd) is not int
                    or not 0 <= tool_cost_micro_usd <= MAX_ACCOUNTED_MICRO_USD))):
            raise _error('model_usage_input_invalid', '模型回执参数无效。', 422)
        try:
            digest = _digest(dict(response_id=response_id, model=model, status=status,
                                  usage=usage, tool_cost_micro_usd=tool_cost_micro_usd))
        except (TypeError, ValueError) as exc:
            raise _error('model_usage_input_invalid', '模型用量回执格式无效。', 422) from exc
        with self.store.connection(write=True) as db:
            call = self.store.require_call(db, call_id)
            event = self.store.find_event(db, call_id, event_key)
            if event and event['event_digest'] != digest:
                raise _error('model_usage_event_conflict', '同一用量事件标识已用于不同内容。')
            if call['provider_response_id'] and call['provider_response_id'] != response_id:
                raise _error('model_usage_event_conflict', '模型回执与已记录响应不一致。')
            if call['status'] == 'released' or call['status'] == 'reserved':
                raise _error('model_call_transition_invalid', '此调用不能保存供应商回执。')
            other = db.execute('SELECT id FROM model_calls WHERE provider=%s AND provider_response_id=%s AND id<>%s',
                               (call['provider'], response_id, call_id)).fetchone()
            if other:
                raise _error('model_usage_event_conflict', '供应商响应已属于其他模型调用。')
            terminal_saved = call['provider_status'] in TERMINAL
            if event or (terminal_saved and status not in TERMINAL):
                if request_id is not None:
                    call.update(provider_request_id=request_id, updated_at=datetime.now(timezone.utc))
                    self.store.update_call(db, call)
                return call
            same_receipt = db.execute('''SELECT * FROM usage_events
                WHERE call_id=%s AND event_type='observation' AND event_digest=%s''',
                (call_id, digest)).fetchone()
            if terminal_saved and call['usage_status'] == 'estimated':
                if not same_receipt:
                    raise _error('model_usage_event_conflict', '已结算的供应商终态用量不能变更。')
                # Bind the new audit key without reapplying historical pending evidence.
                replay = dict(same_receipt)
                replay.update(id=str(uuid4()), event_key=event_key, created_at=datetime.now(timezone.utc))
                self.store.insert_event(db, replay)
                return call
            price = PriceSnapshot.model_validate(call['price_snapshot'])
            measured = estimate_usage(price, usage, tools=call['policy_snapshot']['tools'],
                                      tool_cost_micro_usd=tool_cost_micro_usd)
            if model != call['model']:
                measured.update(estimated_cost_micro_usd=None, usage_status='pending', reason_code='model_mismatch')
            settled = status in TERMINAL and measured['usage_status'] == 'estimated'
            if not settled:
                measured['usage_status'] = 'pending'
            # Evidence cannot erase a larger previously observed partial estimate.
            amount = measured['estimated_cost_micro_usd']
            if not settled and call['estimated_cost_micro_usd'] is not None:
                amount = max(call['estimated_cost_micro_usd'], amount or 0)
            now = datetime.now(timezone.utc)
            self.store.insert_event(db, dict(id=str(uuid4()), call_id=call_id, event_key=event_key,
                event_digest=digest, event_type='observation', provider_usage=measured['provider_usage'],
                price_snapshot=call['price_snapshot'], estimated_cost_micro_usd=measured['estimated_cost_micro_usd'],
                usage_status=measured['usage_status'], reason_code=measured['reason_code'], created_at=now))
            call.update(status=('completed' if status in ('completed', 'incomplete') else 'failed')
                if status in TERMINAL else 'submitted', provider_status=status,
                provider_request_id=request_id or call['provider_request_id'], provider_response_id=response_id,
                estimated_cost_micro_usd=amount, usage_status=measured['usage_status'], error_code=None, updated_at=now)
            if call.get('provider_state'):
                call['provider_state'] = {**call['provider_state'], 'phase': 'response_ready'}
            self.store.update_call(db, call)
            db.execute('''UPDATE budget_reservations SET accounted_micro_usd=%s,status=%s,updated_at=%s
                WHERE call_id=%s''', (amount or 0, 'settled' if settled else 'held', now, call_id))
            return call

    def release_unsubmitted(self, call_id, *, event_key, reason_code):
        if not _key(event_key) or not _key(reason_code):
            raise _error('model_usage_input_invalid', '模型预留释放参数无效。', 422)
        digest = _digest(dict(event_type='release', reason_code=reason_code))
        with self.store.connection(write=True) as db:
            call = self.store.require_call(db, call_id)
            existing = self.store.find_event(db, call_id, event_key)
            if existing:
                if existing['event_digest'] != digest:
                    raise _error('model_usage_event_conflict', '预留释放事件标识内容冲突。')
                return call
            if call['status'] != 'reserved':
                raise _error('model_call_transition_invalid', '已开始提交或结果未知的调用不能释放预留。')
            now = datetime.now(timezone.utc)
            self.store.insert_event(db, dict(id=str(uuid4()), call_id=call_id, event_key=event_key,
                event_digest=digest, event_type='release', provider_usage=None, price_snapshot=call['price_snapshot'],
                estimated_cost_micro_usd=0, usage_status='estimated', reason_code=reason_code, created_at=now))
            call.update(status='released', estimated_cost_micro_usd=0, usage_status='estimated', updated_at=now)
            self.store.update_call(db, call)
            db.execute("UPDATE budget_reservations SET status='released',accounted_micro_usd=0,updated_at=%s WHERE call_id=%s",
                       (now, call_id))
            return call

    def project_usage(self, project_id, *, page=1, page_size=10):
        return self._usage(project_id, None, page, page_size)

    def task_usage(self, task_id, *, page=1, page_size=10):
        return self._usage(None, task_id, page, page_size)

    def _usage(self, project_id, task_id, page, page_size):
        if (type(page) is not int or not 1 <= page <= 1_000_000
                or type(page_size) is not int or not 1 <= page_size <= 50):
            raise _error('model_usage_input_invalid', '模型用量分页参数无效。', 422)
        with self.store.connection() as db:
            if task_id:
                task = self.store.require_task(db, task_id)
                project_id = task['project_id']
            else:
                self.store.require_project(db, project_id)
            views = {}
            for scope, key in [('user', self.store.user_id), ('project', project_id)] + ([('task', task_id)] if task_id else []):
                views[scope + '_budget'] = self.store.budget_view(db, scope, self.store.budget(db, scope, key))
            column, key = ('task_id', task_id) if task_id else ('project_id', project_id)
            where = ' WHERE c.user_id=%s AND c.' + column + '=%s'
            params = (self.store.user_id, key)
            aggregate = db.execute('''SELECT COUNT(*) AS total,
                COUNT(*) FILTER (WHERE c.usage_status='pending' AND c.status<>'released') AS pending
                FROM model_calls c''' + where, params).fetchone()
            rows = db.execute('''SELECT c.id,t.task_type,c.model,c.status,c.provider_status,c.usage_status,
                c.estimated_cost_micro_usd,c.created_at,c.updated_at
                FROM model_calls c JOIN tasks t ON t.id=c.task_id''' + where
                + ' ORDER BY c.created_at DESC,c.id LIMIT %s OFFSET %s',
                params + (page_size, (page - 1) * page_size)).fetchall()
            scope = views['task_budget' if task_id else 'project_budget']
            return dict(currency='USD', period='cumulative', enforcement_scope='unified_only', **views,
                estimated_micro_usd=scope['estimated_micro_usd'], reserved_micro_usd=scope['reserved_micro_usd'],
                pending_count=int(aggregate['pending']), items=[dict(row) for row in rows],
                total=int(aggregate['total']), page=page, page_size=page_size)
