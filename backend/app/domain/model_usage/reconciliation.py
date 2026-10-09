"""Append owner-scoped evidence and adjust all budgets in one schema-locked transaction."""
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import ValidationError

from app.adapters.model_usage_store import ModelUsageStore
from app.domain.model_usage.accounting import accounting_projection, public_reconciliation, reconciliation_status, tool_applicable
from app.domain.model_usage.contracts import MAX_ACCOUNTED_MICRO_USD
from app.domain.model_usage.reconciliation_contracts import ReconciliationRequest
from app.domain.model_usage.service import _digest, _error


class ModelReconciliationService:
    def __init__(self, user_id, config=None):
        self.store = ModelUsageStore(user_id, config)

    def inspect(self, call_id):
        with self.store.connection() as db:
            call = self.store.require_call(db, call_id)
            history = [dict(row) for row in db.execute("""SELECT event_key,created_at,reconciliation FROM usage_events
                WHERE call_id=%s AND event_type='reconciliation' ORDER BY created_at,id""", (call_id,)).fetchall()]
            return dict(call_id=call_id, status=call['status'], provider_response_id=call['provider_response_id'],
                provider_state=call.get('provider_state'), policy_snapshot=call['policy_snapshot'],
                estimated_cost_micro_usd=call['estimated_cost_micro_usd'], usage_status=call['usage_status'],
                reconciliation_revision=call['reconciliation_revision'],
                reconciliation=public_reconciliation(call, history[-1]['created_at'] if history else None), history=history)

    def preview(self, call_id, request):
        return self._apply(call_id, request, write=False)

    def reconcile(self, call_id, request):
        return self._apply(call_id, request, write=True)

    def _apply(self, call_id, request, *, write):
        try:
            request = ReconciliationRequest.model_validate(request.model_dump() if isinstance(request, ReconciliationRequest) else request)
        except (ValidationError, TypeError, ValueError) as exc:
            raise _error('model_reconciliation_input_invalid', '实际费用核对参数或凭证格式无效。', 422) from exc
        body, digest = request.model_dump(), _digest(request.model_dump())
        with self.store.connection(write=write) as db:
            call = self.store.require_call(db, call_id)
            existing = self.store.find_event(db, call_id, request.event_key)
            if existing:
                if existing['event_type'] != 'reconciliation' or existing['event_digest'] != digest:
                    raise _error('model_reconciliation_event_conflict', '同一核对事件标识已用于不同内容。')
                return existing['reconciliation']['receipt']
            if call['reconciliation_revision'] != request.expected_revision:
                raise _error('model_reconciliation_revision_conflict', '核对版本已变化，请重新读取。')
            if call['status'] not in ('completed', 'failed'):
                raise _error('model_reconciliation_transition_invalid', '仅已结束的模型调用可以核对实际费用。')
            if request.component == 'token':
                expected = call['provider_response_id']
            else:
                expected = (call.get('provider_state') or {}).get('container_id') if tool_applicable(call) else None
            if not expected or request.provider_object_id != expected:
                raise _error('model_reconciliation_object_mismatch', '费用凭证与已保存的供应商对象不一致。')
            if request.component == 'tool' and db.execute("""SELECT id FROM model_calls
                WHERE provider=%s AND provider_state->>'container_id'=%s AND id<>%s LIMIT 1""",
                (call['provider'], expected, call_id)).fetchone():
                raise _error('model_reconciliation_container_ambiguous', '容器关联多个调用，不能分摊实际费用。')
            rows = [dict(row) for row in db.execute('SELECT * FROM budget_reservations WHERE call_id=%s', (call_id,)).fetchall()]
            if len(rows) != 3:
                raise _error('model_reconciliation_accounting_invalid', '模型调用预算记录不完整。')
            if len({(row['reserved_micro_usd'], row['accounted_micro_usd'], row['status']) for row in rows}) != 1:
                raise _error('model_reconciliation_accounting_invalid', '模型调用预算记录不一致。')
            before, _ = accounting_projection(call, rows[0])
            previous = dict(token_micro_usd=call.get('actual_token_micro_usd'), tool_micro_usd=call.get('actual_tool_micro_usd'))
            changed = {**call, 'actual_' + request.component + '_micro_usd': request.amount_micro_usd,
                'reconciliation_revision': call['reconciliation_revision'] + 1}
            after, reserved = accounting_projection(changed, rows[0])
            if after > MAX_ACCOUNTED_MICRO_USD:
                raise _error('model_reconciliation_input_invalid', '实际费用合计超出支持范围。', 422)
            actual = (changed.get('actual_token_micro_usd') or 0) + (changed.get('actual_tool_micro_usd') or 0)
            if actual > MAX_ACCOUNTED_MICRO_USD:
                raise _error('model_reconciliation_input_invalid', '实际费用合计超出支持范围。', 422)
            state = reconciliation_status(changed)
            receipt = dict(call_id=call_id, revision=changed['reconciliation_revision'], component=request.component,
                actual_micro_usd=actual, reconciliation_status=state, accounted_before_micro_usd=before,
                accounted_after_micro_usd=after, delta_micro_usd=after-before, reserved_after_micro_usd=reserved)
            if not write:
                return receipt
            now = datetime.now(timezone.utc)
            payload = dict(request=body, operator=request.operator, revision=changed['reconciliation_revision'],
                previous_actual_micro_usd=previous,
                actual_micro_usd=dict(token_micro_usd=changed.get('actual_token_micro_usd'), tool_micro_usd=changed.get('actual_tool_micro_usd')),
                accounted_before_micro_usd=before, accounted_after_micro_usd=after, delta_micro_usd=after-before, receipt=receipt)
            self.store.insert_event(db, dict(id=str(uuid4()), call_id=call_id, event_key=request.event_key,
                event_digest=digest, event_type='reconciliation', provider_usage=None, price_snapshot=call['price_snapshot'],
                estimated_cost_micro_usd=None, usage_status=call['usage_status'], reason_code=None, created_at=now,
                reconciliation=payload))
            db.execute('''UPDATE model_calls SET actual_token_micro_usd=%s,actual_tool_micro_usd=%s,
                reconciliation_revision=%s WHERE id=%s''', (changed.get('actual_token_micro_usd'), changed.get('actual_tool_micro_usd'),
                changed['reconciliation_revision'], call_id))
            # The old reservation column is capped at the configuration ceiling. Keep
            # its original baseline for partial evidence; effective holds are projected.
            db.execute('''UPDATE budget_reservations SET accounted_micro_usd=%s,
                status=%s,updated_at=%s WHERE call_id=%s''',
                (after, 'settled' if state == 'reconciled' else 'held', now, call_id))
            return receipt
