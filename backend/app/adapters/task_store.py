"""Owner-scoped task persistence. Reads never dispatch or advance execution."""
import json
import re
from uuid import uuid4
from pathlib import Path
from app.core.config import get_data_dir

from psycopg.types.json import Jsonb

from app.adapters.storage import _storage_connection, ProjectStore
from app.core.exceptions import StorageError
from app.core.errors import PUBLIC_CODES
from app.db.database import get_database_config
from app.domain.tasks.contracts import TaskView, TaskEventView, display_status
from app.domain.tasks.errors import safe_error_code, error_category


def source_conflict():
    return StorageError('task_source_conflict', '任务资料已变化或来源不一致，请重新读取当前版本。', 409)


def workflow_version(task_type, value):
    if task_type in ('figure_projection','figure_workbench','figure_explanation','collection_word_report'):
        return task_type + '_v1'
    return task_type + ('_v2' if 'source' in value else '_v1')


def task_source_matches(task, result):
    snapshot = task['input_snapshot']
    expected = result.get('source')
    return snapshot.get('source') == expected and snapshot['result'].get('source') == expected


def snapshots_match(current, original, *, explanation=True):
    keys = ['file', 'result', 'figure', 'versions', 'output_language']
    if explanation:
        keys.append('explanation')
    if 'processing' in current or 'processing' in original:
        keys.append('processing')
    if 'source' in current or 'source' in original:
        keys.extend(('source', 'schema_version'))
    return all(key in current and key in original and current[key] == original[key] for key in keys)


def _source_json(value):
    parsed = json.loads(value)
    # Legacy TEXT JSON must be representable as JSONB, including nested fields.
    json.dumps(parsed, allow_nan=False)
    return parsed


class DatasetTaskAssets:
    """Owner-scoped dataset reader with explicit database and asset roots."""
    def __init__(self, owner_id, config, directory=None):
        self.owner_id = owner_id
        self.db_config = config
        self.directory = Path(directory if directory is not None else get_data_dir())

    def original(self, record):
        from app.adapters.file_objects import LocalFileObjects
        return LocalFileObjects(self.directory).original(record)

    def file(self, project_id, file_id):
        scoped = TaskStore(self.owner_id, self.db_config)
        with scoped.connection() as db:
            scoped.require_project(db, project_id)
            row = db.execute('SELECT * FROM files WHERE id=%s AND project_id=%s', (file_id, project_id)).fetchone()
            if row is None:
                raise source_conflict()
            return ProjectStore.file_record(row)


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

    def source_snapshot(self, db, project, request, *, directory=None):
        # Only persisted records are accepted, inside the creation transaction.
        # Legacy file bytes are checked by the executor; dataset objects are
        # verified here and again at execution/publication boundaries.
        from app.domain.descriptive import result_model
        from app.domain.analysis_sources import statistics_engine, source_dict
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
            result_model(result).model_validate(result, strict=True)
            from app.domain.artifact_contracts import artifact_language, figure_renderer, explanation_version, report_version
            RENDERER=figure_renderer(result); EXPLANATION_VERSION=explanation_version(result); REPORT_VERSION=report_version(result)
            saved_setup = _source_json(setup['setup_json'])
            engine = statistics_engine(result)
            if saved_setup.get('source') != result.get('source'):
                raise source_conflict()
            if 'source' in result:
                source_dict(result['source'])
                from app.domain.dataset_analysis import load_dataset
                load_dataset(DatasetTaskAssets(self.user_id, self.config, directory), project['id'], file['id'],
                             result['source']['dataset_id'], expected_source=result['source'])
            from app.domain.analysis_plan.service import validate_plan_reference
            assets = DatasetTaskAssets(self.user_id, self.config, directory)
            validate_plan_reference(assets, project['id'], file['id'], saved_setup)
            validate_plan_reference(assets, project['id'], file['id'], result)
            if result.get('result_type') in ('regression','roc','survival'):
                from app.domain.modeling_material import load_input
                load_input(assets,project['id'],file['id'],result)
            elif result.get('result_type') == 'correlation':
                from app.domain.correlation.service import load_correlation_input
                load_correlation_input(assets, project['id'], file['id'], result)
            elif result.get('result_type') == 'group_comparison':
                from app.domain.comparison.service import load_comparison_input
                load_comparison_input(assets,project['id'],file['id'],result)
            if (run['engine_version'] != engine or result['engine']['id'] != engine
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
                        or figure.get('source') != result.get('source')
                        or figure['verification']['status'] != 'matched'
                        or not re.fullmatch(r'[0-9a-f]{64}', figure['sha256'])):
                    raise source_conflict()
                # Reuse the business input builder to require the metadata that
                # explanation/report execution will actually consume.
                if result.get('result_type') in ('group_comparison','regression','roc','survival'):
                    from app.domain.comparison_material import validate_figure_source
                    if result.get('result_type') in ('regression','roc','survival'):
                        from app.domain.modeling_material import validate_figure_source
                    validate_figure_source(assets,project['id'],file['id'],result,figure)
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
        processing = None
        if request.task_type == 'word_report':
            from app.domain.dataset_processing import load_processing
            processing = load_processing(assets, project['id'], result.get('source', {}))
        return {**({'processing': processing} if processing is not None else {}),
                'schema_version': 2 if 'source' in result else 1, 'output_language': artifact_language(result),
                **({'source': result['source']} if 'source' in result else {}),
                'project': {key: project[key] for key in ('id', 'name', 'research_topic', 'project_type', 'created_at')},
                'file': {key: file[key] for key in ('id', 'filename', 'sha256', 'size_bytes', 'file_type')},
                'result': result, 'figure': figure, 'explanation': explanation,
                'versions': {'statistics': engine, 'figure': RENDERER,
                             'explanation': EXPLANATION_VERSION, 'report': REPORT_VERSION}}

    @staticmethod
    def public_task(task):
        fields = ('id', 'project_id', 'task_type', 'status', 'phase', 'revision', 'current_attempt',
                  'reason_code', 'created_at', 'updated_at')
        snapshot = task['input_snapshot']
        code = task.get('error_code')
        from app.domain.tasks.waits import input_version
        return TaskView(**{key: task[key] for key in fields},
            result_analysis_run_id=task.get('result_analysis_run_id'),
            execution_receipt=task.get('execution_receipt'),
            result_report_id=task.get('result_report_id'),
            result_explanation_id=task.get('result_explanation_id'),
            result_figure_id=task.get('result_figure_id'),
            error_code=safe_error_code(code), retry_count=task.get('retry_count', 0),
            display_status=display_status(task['status'], task['phase']),
            input_version=input_version(task)).model_dump(mode='json')

    def get(self, task_id):
        with self.connection() as db:
            from app.domain.tasks.legacy import is_legacy_id, public_legacy_task
            if is_legacy_id(task_id):
                from app.adapters.legacy_task_query import require_legacy_task
                from app.domain.tasks.legacy_artifacts import exact_legacy_artifact
                row = require_legacy_task(db, self.user_id, task_id)
                return public_legacy_task(row, exact_legacy_artifact(db, row))
            return self.public_task(self.require_task(db, task_id))

    def require_mutable(self, task_id):
        from app.domain.tasks.legacy import is_legacy_id
        if is_legacy_id(task_id):
            from app.adapters.legacy_task_query import require_legacy_task
            with self.connection() as db:
                require_legacy_task(db, self.user_id, task_id)
            raise StorageError('task_transition_invalid', '历史任务仅支持查看，无法重试或恢复。', 409)

    def events(self, task_id, *, after=0, limit=50):
        if (type(after) is not int or not 0 <= after <= 2_147_483_647
                or type(limit) is not int or not 1 <= limit <= 100):
            raise StorageError('task_input_invalid', '任务事件查询参数无效。', 422)
        with self.connection() as db:
            from app.domain.tasks.legacy import is_legacy_id
            if is_legacy_id(task_id):
                from app.adapters.legacy_task_query import require_legacy_task
                require_legacy_task(db, self.user_id, task_id)
                return {'task_id': task_id, 'items': [], 'next_cursor': after, 'has_more': False}
            self.require_task(db, task_id)
            rows = db.execute('''SELECT * FROM task_events WHERE task_id=%s AND seq>%s
                ORDER BY seq LIMIT %s''', (task_id, after, limit + 1)).fetchall()
            items = [TaskEventView.model_validate({**dict(row), 'error_code': safe_error_code(row.get('error_code'))}).model_dump(mode='json') for row in rows[:limit]]
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
        error = safe_error_code(task.get('error_code')) if event_type in ('failed', 'waiting', 'deferred') else None
        retry_reason = task.get('_retry_reason')
        retry_count = task.get('retry_count', 0) if retry_reason or error else None
        db.execute('''INSERT INTO task_events
            (task_id,seq,task_revision,event_type,status,phase,reason_code,created_at,
             error_code,error_category,retry_reason,retry_count,retry_delay_seconds)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
            (task['id'], task['revision'], task['revision'], event_type, task['status'],
             task['phase'], task['reason_code'], task['updated_at'], error, error_category(error),
             retry_reason, retry_count, task.get('_retry_delay_seconds')))

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
        error = safe_error_code(task.get('error_code'))
        updated = db.execute('''UPDATE task_attempts SET status=%s,finished_at=%s,reason_code=%s,
                error_code=COALESCE(%s,error_code),error_category=COALESCE(%s,error_category),
                retry_reason=CASE WHEN %s::text IS NULL THEN retry_reason ELSE %s END,
                lease_owner=NULL,lease_expires_at=NULL,heartbeat_at=NULL
            WHERE task_id=%s AND attempt_no=%s AND status='running' ''',
            (task['status'], task['updated_at'], task['reason_code'], error, error_category(error),
             error, task.get('_retry_reason'), task['id'], task['current_attempt']))
        if updated.rowcount != 1:
            raise StorageError('task_transition_invalid', '当前任务执行记录不一致，请重新读取任务。', 409)

    @staticmethod
    def update_task(db, task, expected_revision):
        task['error_code'] = safe_error_code(task.get('error_code'))
        updated = db.execute('''UPDATE tasks
            SET status=%s,phase=%s,revision=%s,current_attempt=%s,reason_code=%s,updated_at=%s,
                result_report_id=%s,error_code=%s,result_explanation_id=%s,result_figure_id=%s,retry_count=%s,result_analysis_run_id=%s,execution_receipt=%s
            WHERE id=%s AND revision=%s''',
            (task['status'], task['phase'], task['revision'], task['current_attempt'], task['reason_code'],
             task['updated_at'], task.get('result_report_id'), task.get('error_code'),
             task.get('result_explanation_id'), task.get('result_figure_id'), task.get('retry_count', 0), task.get('result_analysis_run_id'), Jsonb(task['execution_receipt']) if task.get('execution_receipt') is not None else None, task['id'], expected_revision))
        if updated.rowcount != 1:
            raise StorageError('task_revision_conflict', '任务已发生变化，请重新读取后再操作。', 409)
