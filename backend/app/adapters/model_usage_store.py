"""Short owner-scoped PostgreSQL operations, using the existing schema write lock."""
from psycopg.types.json import Jsonb

from app.adapters.task_store import TaskStore
from app.core.exceptions import StorageError


class ModelUsageStore(TaskStore):
    def require_call(self, db, call_id):
        row = db.execute('''SELECT c.* FROM model_calls c
            JOIN tasks t ON t.id=c.task_id JOIN projects p ON p.id=c.project_id
            JOIN users u ON u.id=c.user_id
            WHERE c.id=%s AND c.user_id=%s AND t.user_id=%s AND p.owner_id=%s AND u.active''',
            (call_id, self.user_id, self.user_id, self.user_id)).fetchone()
        if row is None:
            raise StorageError('model_call_not_found', '模型调用记录不存在。', 404)
        return dict(row)

    @staticmethod
    def insert_call(db, call):
        fields = tuple(call)
        db.execute('INSERT INTO model_calls (' + ','.join(fields) + ') VALUES ('
                   + ','.join(['%s'] * len(fields)) + ')',
                   tuple(Jsonb(call[key]) if key in ('policy_snapshot', 'price_snapshot') else call[key]
                         for key in fields))

    @staticmethod
    def update_call(db, call):
        fields = ('status', 'provider_status', 'provider_request_id', 'provider_response_id',
                  'error_code', 'estimated_cost_micro_usd', 'usage_status', 'updated_at', 'provider_state')
        db.execute('UPDATE model_calls SET ' + ','.join(key + '=%s' for key in fields) + ' WHERE id=%s',
                   tuple(Jsonb(call[key]) if key == 'provider_state' and call.get(key) is not None
                         else call.get(key) for key in fields) + (call['id'],))

    @staticmethod
    def find_event(db, call_id, event_key):
        row = db.execute('SELECT * FROM usage_events WHERE call_id=%s AND event_key=%s',
                         (call_id, event_key)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def insert_event(db, event):
        fields = tuple(event)
        db.execute('INSERT INTO usage_events (' + ','.join(fields) + ') VALUES ('
                   + ','.join(['%s'] * len(fields)) + ')',
                   tuple(Jsonb(event[key]) if key in ('provider_usage', 'price_snapshot', 'reconciliation')
                         and event[key] is not None else event[key] for key in fields))
