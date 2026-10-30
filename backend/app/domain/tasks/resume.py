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
            if request.operation == 'resume' and wait['kind'] == 'remote_observation':
                from app.domain.model_usage.observation import continue_original
                result = continue_original(self.store, db, task, wait)
            else:
                from app.domain.plot_tasks import retry_boxplot_in_transaction
                from app.domain.explanation_tasks import retry_explanation_in_transaction
                from app.domain.report_tasks import retry_word_in_transaction
                from app.domain.tasks.file_parse_retry import retry_parse_in_transaction
                from app.domain.tasks.dataset_retry import retry_dataset_in_transaction
                from app.domain.dataset_preparation.service import retry_preparation_in_transaction
                from app.domain.ocr_review.service import retry_ocr_review_in_transaction
                from app.domain.analysis_plan.service import retry_plan_in_transaction
                from app.domain.analysis_recommendation.service import retry_in_transaction as retry_recommendation
                from app.domain.report_collections.execution import retry_collection_in_transaction
                from app.domain.figure_workbench.tasks import retry_in_transaction as retry_configured
                from app.domain.statistics_execution.service import retry_in_transaction as retry_statistics
                from app.domain.literature.service import retry_in_transaction as retry_literature
                from app.domain.literature_assistance.service import retry_in_transaction as retry_assistance
                from app.domain.manuscripts.execution import retry_in_transaction as retry_manuscript
                from app.domain.manuscript_writing.service import retry_in_transaction as retry_writing
                from app.domain.school_templates.service import retry_in_transaction as retry_school_template
                from app.domain.journals.service import retry_in_transaction as retry_journal
                from app.domain.journals.format_service import retry_in_transaction as retry_format
                from app.domain.journals.adaptation_service import retry_in_transaction as retry_adaptation
                from app.domain.review_rounds.execution import retry_in_transaction as retry_review
                from app.domain.review_rounds.revisions import retry_in_transaction as retry_revision
                from app.domain.review_rounds.document_exports import retry_in_transaction as retry_review_document
                from app.domain.school_templates.suggestion_execution import retry_in_transaction as retry_school_suggestion
                from app.domain.bioinformatics.service import retry_in_transaction as retry_bio
                from app.domain.bioinformatics.analysis_service import retry_in_transaction as retry_spatial
                retry = {'bio_analysis':retry_spatial,'bio_figure':retry_spatial,'bio_import':retry_bio,'school_rule_suggestion':retry_school_suggestion,'review_document_export':retry_review_document,'review_revision':retry_revision,'review_round_plan':retry_review,'journal_adaptation':retry_adaptation,'journal_format_check':retry_format,'journal_recommendation':retry_journal,'school_template_parse':retry_school_template,'manuscript_writing':retry_writing,'manuscript_draft':retry_manuscript,'manuscript_docx':retry_manuscript,'literature_assistance':retry_assistance,'literature_search':retry_literature,'statistics_compute':retry_statistics,'figure_projection':retry_configured,'figure_workbench':retry_configured,'figure_explanation':retry_configured,'collection_word_report': retry_collection_in_transaction, 'analysis_recommendation':retry_recommendation,'boxplot': retry_boxplot_in_transaction, 'explanation': retry_explanation_in_transaction,
                         'word_report': retry_word_in_transaction, 'parse_file': retry_parse_in_transaction,
                         'extract_dataset': retry_dataset_in_transaction, 'prepare_dataset': retry_preparation_in_transaction, 'review_ocr': retry_ocr_review_in_transaction, 'analysis_plan': retry_plan_in_transaction}[task['task_type']]
                result = retry(self.store, db, task, request.expected_task_revision)
            db.execute('''INSERT INTO task_resume_requests
                (id,task_id,user_id,idempotency_key,operation,wait_id,request_digest,expected_task_revision,
                 input_version,result_task_revision,response_json,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (str(uuid4()), task_id, task['user_id'], idempotency_key, request.operation, request.wait_id,
                 digest, request.expected_task_revision, Jsonb(material['input_version']),
                 result['revision'], Jsonb(result), task['updated_at']))
            return result
