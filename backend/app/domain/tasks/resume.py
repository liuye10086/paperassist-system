"""One transaction accepts a recovery decision, resolves its wait and queues work."""
import hashlib
import json
import re
from uuid import uuid4

from psycopg.types.json import Jsonb
from pydantic import ValidationError

from app.adapters.task_store import TaskStore
from app.core.exceptions import StorageError
from app.domain.tasks.wait_contracts import ResumeRequest
from app.domain.tasks.waits import allowed_recovery_actions, get_open_wait, input_version


class TaskResumeService:
    def __init__(self, user_id, config=None):
        self.store = TaskStore(user_id, config)

    def resume(self, task_id, request, *, idempotency_key):
        try:
            request = ResumeRequest.model_validate(request.model_dump() if isinstance(request, ResumeRequest) else request)
        except (ValidationError, TypeError, ValueError) as exc:
            raise StorageError('task_input_invalid', '恢复请求无效，请重新读取任务。', 422) from exc
        if not isinstance(idempotency_key, str) or not re.fullmatch(r'[\x21-\x7e]{1,128}', idempotency_key):
            raise StorageError('task_input_invalid', '恢复请求标识无效，请重新提交。', 422)
        material = request.model_dump(mode='json')
        digest = hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True,
            separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
        with self.store.connection(write=True) as db:
            task = self.store.require_task(db, task_id)
            existing = db.execute('''SELECT * FROM task_resume_requests
                WHERE user_id=%s AND task_id=%s AND idempotency_key=%s''',
                (self.store.user_id, task_id, idempotency_key)).fetchone()
            if existing:
                if existing['request_digest'] != digest:
                    raise StorageError('task_idempotency_conflict', '同一恢复标识已用于不同输入。', 409)
                return existing['response_json']
            if task['revision'] != request.expected_task_revision:
                raise StorageError('task_revision_conflict', '任务已变化，请重新读取后操作。', 409)
            if input_version(task) != material['input_version']:
                raise StorageError('task_source_conflict', '恢复请求的输入版本与原任务不一致。', 409)
            if request.operation not in allowed_recovery_actions(db, task):
                raise StorageError('task_transition_invalid', '此任务不能通过当前操作安全恢复。', 409)
            if request.operation == 'resume':
                wait = get_open_wait(db, task)
                if wait is None or wait['id'] != request.wait_id or wait['input_version'] != material['input_version']:
                    raise StorageError('task_revision_conflict', '待办已变化，请重新读取后操作。', 409)
            from app.domain.plot_tasks import retry_boxplot_in_transaction
            from app.domain.explanation_tasks import retry_explanation_in_transaction
            from app.domain.report_tasks import retry_word_in_transaction
            retry = {'boxplot': retry_boxplot_in_transaction, 'explanation': retry_explanation_in_transaction,
                     'word_report': retry_word_in_transaction}[task['task_type']]
            result = retry(self.store, db, task, request.expected_task_revision)
            db.execute('''INSERT INTO task_resume_requests
                (id,task_id,user_id,idempotency_key,operation,wait_id,request_digest,expected_task_revision,
                 input_version,result_task_revision,response_json,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (str(uuid4()), task_id, task['user_id'], idempotency_key, request.operation, request.wait_id,
                 digest, request.expected_task_revision, Jsonb(material['input_version']),
                 result['revision'], Jsonb(result), task['updated_at']))
            return result
