"""Owner-scoped task persistence. Reads never dispatch or advance execution."""
import json
import re
from uuid import uuid4

from psycopg.types.json import Jsonb

from app.adapters.storage import _storage_connection
from app.core.exceptions import StorageError
from app.core.errors import PUBLIC_CODES
from app.db.database import get_database_config
from app.domain.tasks.contracts import TaskView, TaskEventView, display_status


def source_conflict():
    return StorageError('task_source_conflict', '任务资料已变化或来源不一致，请重新读取当前版本。', 409)


def _source_json(value):
    parsed = json.loads(value)
    # Legacy TEXT JSON must be representable as JSONB, including nested fields.
    json.dumps(parsed, allow_nan=False)
    return parsed


class TaskStore:
    def __init__(self, user_id: str, config=None):
        if not isinstance(user_id, str) or not user_id:
            raise ValueError('Tasks require an explicit owner.')
        self.user_id = user_id
        self.config = config or get_database_config()

    def connection(self, write=False):
        return _storage_connection(write=write, config=self.config)

    def require_project(self, db, project_id):
        row = db.execute('''SELECT p.* FROM projects p JOIN users u ON u.id=p.owner_id
            WHERE p.id=%s AND p.owner_id=%s AND u.active''', (project_id, self.user_id)).fetchone()
        if row is None:
            raise StorageError('project_not_found', '项目不存在，请刷新项目列表。', 404)
        return dict(row)

    def require_task(self, db, task_id):
        row = db.execute('''SELECT t.* FROM tasks t JOIN projects p ON p.id=t.project_id
            JOIN users u ON u.id=t.user_id
            WHERE t.id=%s AND t.user_id=%s AND p.owner_id=%s AND u.active''',
            (task_id, self.user_id, self.user_id)).fetchone()
        if row is None:
            raise StorageError('task_not_found', '任务不存在，请刷新后重试。', 404)
        return dict(row)

    def find_request(self, db, project_id, task_type, key):
        row = db.execute('''SELECT * FROM tasks
            WHERE user_id=%s AND project_id=%s AND task_type=%s AND idempotency_key=%s''',
            (self.user_id, project_id, task_type, key)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def source_snapshot(db, project, request):
        # Only persisted records are accepted, inside the creation transaction.
        # File bytes are deliberately checked by the eventual executor, outside
        # this short metadata transaction; this step does not execute any task.
        from app.domain.descriptive import AnalysisResult, ENGINE
        from app.domain.boxplot import RENDERER
        from app.domain.explanation_content import VERSION as EXPLANATION_VERSION, build_payload
        from app.domain.reports import validate_sources
        from app.adapters.report_docx import VERSION as REPORT_VERSION

        file = db.execute('SELECT * FROM files WHERE id=%s AND project_id=%s',
                          (request.file_id, project['id'])).fetchone()
        run = db.execute('SELECT * FROM analysis_runs WHERE id=%s AND file_id=%s',
                         (request.analysis_run_id, request.file_id)).fetchone()
        setup = db.execute('SELECT * FROM analysis_setups WHERE file_id=%s', (request.file_id,)).fetchone()
        if not file or not run or not setup or file['parse_status'] != 'parsed':
            raise source_conflict()
        try:
            result = _source_json(run['result_json'])
            AnalysisResult.model_validate(result, strict=True)
            saved_setup = _source_json(setup['setup_json'])
            if (run['engine_version'] != ENGINE or result['engine']['id'] != ENGINE
                    or run['setup_revision'] != request.expected_revision
                    or setup['revision'] != request.expected_revision
                    or saved_setup['revision'] != request.expected_revision
                    or result['id'] != run['id'] or result['file_id'] != file['id']
                    or result['setup_revision'] != request.expected_revision
                    or result['source_sha256'] != file['sha256']
                    or saved_setup['file_id'] != file['id'] or saved_setup['source_sha256'] != file['sha256']
                    or saved_setup['selection'] != result['selection']):
                raise source_conflict()
            figure = explanation = None
            if request.figure_id:
                row = db.execute('SELECT * FROM figures WHERE id=%s AND analysis_run_id=%s',
                                 (request.figure_id, run['id'])).fetchone()
                if not row or row['renderer_version'] != RENDERER:
                    raise source_conflict()
                figure = _source_json(row['figure_json'])
                if (figure['id'] != row['id'] or figure['analysis_run_id'] != run['id']
                        or figure['file_id'] != file['id'] or figure['setup_revision'] != request.expected_revision
                        or figure['source_sha256'] != file['sha256'] or figure['engine']['id'] != RENDERER
                        or figure['verification']['status'] != 'matched'
                        or not re.fullmatch(r'[0-9a-f]{64}', figure['sha256'])):
                    raise source_conflict()
                # Reuse the business input builder to require the metadata that
                # explanation/report execution will actually consume.
                json.dumps(build_payload(result, figure), allow_nan=False)
            if request.explanation_id:
                row = db.execute('''SELECT * FROM explanations
                    WHERE id=%s AND analysis_run_id=%s AND figure_id=%s''',
                    (request.explanation_id, run['id'], figure['id'])).fetchone()
                if not row or row['engine_version'] != EXPLANATION_VERSION:
                    raise source_conflict()
                explanation = _source_json(row['explanation_json'])
                if explanation['id'] != row['id']:
                    raise source_conflict()
                validate_sources(result, figure, explanation)
        except (KeyError, TypeError, ValueError, StorageError) as exc:
            raise source_conflict() from exc
        return {'schema_version': 1, 'output_language': 'zh-CN',
                'project': {key: project[key] for key in ('id', 'name', 'research_topic', 'project_type', 'created_at')},
                'file': {key: file[key] for key in ('id', 'filename', 'sha256', 'size_bytes', 'file_type')},
                'result': result, 'figure': figure, 'explanation': explanation,
                'versions': {'statistics': ENGINE, 'figure': RENDERER,
                             'explanation': EXPLANATION_VERSION, 'report': REPORT_VERSION}}

    @staticmethod
    def public_task(task):
        fields = ('id', 'project_id', 'task_type', 'status', 'phase', 'revision', 'current_attempt',
                  'reason_code', 'created_at', 'updated_at')
        snapshot = task['input_snapshot']
        code = task.get('error_code')
        return TaskView(**{key: task[key] for key in fields},
            result_report_id=task.get('result_report_id'),
            result_explanation_id=task.get('result_explanation_id'),
            result_figure_id=task.get('result_figure_id'),
            error_code=code if code in PUBLIC_CODES else ('internal_error' if code else None),
            display_status=display_status(task['status'], task['phase']),
            input_version={'setup_revision': snapshot['result']['setup_revision'],
                           'output_language': snapshot['output_language']}).model_dump(mode='json')

    def get(self, task_id):
        with self.connection() as db:
            return self.public_task(self.require_task(db, task_id))

    def events(self, task_id, *, after=0, limit=50):
        if (type(after) is not int or not 0 <= after <= 2_147_483_647
                or type(limit) is not int or not 1 <= limit <= 100):
            raise StorageError('task_input_invalid', '任务事件查询参数无效。', 422)
        with self.connection() as db:
            self.require_task(db, task_id)
            rows = db.execute('''SELECT * FROM task_events WHERE task_id=%s AND seq>%s
                ORDER BY seq LIMIT %s''', (task_id, after, limit + 1)).fetchall()
            items = [TaskEventView.model_validate(dict(row)).model_dump(mode='json') for row in rows[:limit]]
            return {'task_id': task_id, 'items': items, 'next_cursor': items[-1]['seq'] if items else after,
                    'has_more': len(rows) > limit}

    @staticmethod
    def insert_task(db, task):
        fields = ('id', 'project_id', 'user_id', 'task_type', 'idempotency_key', 'input_digest', 'input_snapshot',
                  'workflow_version', 'status', 'phase', 'revision', 'current_attempt', 'reason_code',
                  'created_at', 'updated_at')
        db.execute('INSERT INTO tasks (' + ','.join(fields) + ') VALUES (' + ','.join(['%s'] * len(fields)) + ')',
                   tuple(Jsonb(task[key]) if key == 'input_snapshot' else task[key] for key in fields))

    @staticmethod
    def append_event(db, task, event_type):
        db.execute('''INSERT INTO task_events
            (task_id,seq,task_revision,event_type,status,phase,reason_code,created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)''',
            (task['id'], task['revision'], task['revision'], event_type, task['status'],
             task['phase'], task['reason_code'], task['updated_at']))

    @staticmethod
    def enqueue(db, task):
        db.execute('''INSERT INTO task_outbox
            (id,task_id,task_revision,event_type,available_at,created_at,published_at,publish_attempts)
            VALUES (%s,%s,%s,'task_ready',%s,%s,NULL,0)''',
            (str(uuid4()), task['id'], task['revision'], task['updated_at'], task['updated_at']))

    @staticmethod
    def start_attempt(db, task):
        db.execute('''INSERT INTO task_attempts
            (id,task_id,attempt_no,status,started_at,finished_at,reason_code,lease_owner,lease_expires_at,heartbeat_at)
            VALUES (%s,%s,%s,'running',%s,NULL,NULL,NULL,NULL,NULL)''',
            (str(uuid4()), task['id'], task['current_attempt'], task['updated_at']))

    @staticmethod
    def finish_attempt(db, task):
        updated = db.execute('''UPDATE task_attempts SET status=%s,finished_at=%s,reason_code=%s
            WHERE task_id=%s AND attempt_no=%s AND status='running' ''',
            (task['status'], task['updated_at'], task['reason_code'], task['id'], task['current_attempt']))
        if updated.rowcount != 1:
            raise StorageError('task_transition_invalid', '当前任务执行记录不一致，请重新读取任务。', 409)

    @staticmethod
    def update_task(db, task, expected_revision):
        updated = db.execute('''UPDATE tasks
            SET status=%s,phase=%s,revision=%s,current_attempt=%s,reason_code=%s,updated_at=%s,
                result_report_id=%s,error_code=%s,result_explanation_id=%s,result_figure_id=%s
            WHERE id=%s AND revision=%s''',
            (task['status'], task['phase'], task['revision'], task['current_attempt'], task['reason_code'],
             task['updated_at'], task.get('result_report_id'), task.get('error_code'),
             task.get('result_explanation_id'), task.get('result_figure_id'), task['id'], expected_revision))
        if updated.rowcount != 1:
            raise StorageError('task_revision_conflict', '任务已发生变化，请重新读取后再操作。', 409)
