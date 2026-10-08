"""Short PostgreSQL transactions and fenced task execution/publication."""
from dataclasses import dataclass
from datetime import timedelta, timezone
import hashlib
import json
import os
import re
from pathlib import Path
from uuid import UUID, uuid4, uuid5

from app.adapters.storage import _storage_connection, ProjectStore
from app.adapters.task_store import TaskStore, source_conflict
from app.adapters.report_store import ReportStore
from app.adapters.report_docx import VERSION
from app.core.config import get_data_dir
from app.core.exceptions import StorageError
from app.db.database import get_database_config, ensure_schema_current
from app.domain.tasks.contracts import TaskCreateRequest


LEASE_SECONDS = 60
AUTO_ATTEMPTS = 3
REPORT_NAMESPACE = UUID('b699a78d-78b0-43cf-9e1c-297d17186642')
EXPLANATION_NAMESPACE = UUID('067a7749-a01d-4751-b7b5-a6060956c58f')
FIGURE_NAMESPACE = UUID('03015332-5b69-49ea-a3b6-93b7f88030c7')


class LeaseLost(Exception):
    """This attempt can no longer write task state or publish its artifact."""


@dataclass(frozen=True)
class TaskLease:
    task_id: str
    attempt_no: int
    lease_owner: str


class ExecutionAssets:
    """Reuse byte-integrity readers without opening an unrelated DB connection."""
    def __init__(self, directory):
        self.directory = Path(directory)
        self.files_dir = self.directory / 'files'
        self.figures_dir = self.directory / 'figures'

    original = ProjectStore.original
    figure_png = ProjectStore.figure_png


class TaskExecutionStore:
    def __init__(self, *, config=None, directory=None):
        self.config = config or get_database_config()
        self.assets = ExecutionAssets(directory if directory is not None else get_data_dir())
        self.reports = ReportStore(self.assets)

    def connection(self, write=False):
        return _storage_connection(write=write, config=self.config)

    @staticmethod
    def now(db):
        return db.execute('SELECT clock_timestamp() AS now').fetchone()['now']

    @staticmethod
    def require_owner(db, task):
        row = db.execute('''SELECT p.id FROM projects p JOIN users u ON u.id=p.owner_id
            WHERE p.id=%s AND p.owner_id=%s AND u.active''', (task['project_id'], task['user_id'])).fetchone()
        if row is None:
            raise StorageError('task_owner_unavailable', '任务所属账号或项目已不可用。', 409)

    def claim(self, task_id, task_revision, *, task_type=None):
        if not isinstance(task_id, str) or type(task_revision) is not int:
            return None
        with self.connection(write=True) as db:
            ensure_schema_current(db)
            row = db.execute('SELECT * FROM tasks WHERE id=%s', (task_id,)).fetchone()
            if (not row or row['task_type'] not in ('word_report', 'explanation', 'boxplot')
                    or (task_type is not None and row['task_type'] != task_type)
                    or row['revision'] != task_revision):
                return None
            task = dict(row)
            now = self.now(db)
            token = str(uuid4())
            if task['status'] == 'running' and task['task_type'] in ('explanation', 'boxplot'):
                updated = db.execute('''UPDATE task_attempts
                    SET lease_owner=%s,lease_expires_at=%s,heartbeat_at=%s
                    WHERE task_id=%s AND attempt_no=%s AND status='running' AND lease_owner IS NULL''',
                    (token, now + timedelta(seconds=LEASE_SECONDS), now, task_id, task['current_attempt']))
                if updated.rowcount != 1:
                    return None
                lease = TaskLease(task_id, task['current_attempt'], token)
                try:
                    self.require_owner(db, task)
                except StorageError:
                    self._finish(db, task, 'failed', 'task_owner_unavailable')
                    return None
                return lease
            if task['status'] != 'queued':
                return None
            task.update(status='running', revision=task['revision'] + 1, current_attempt=task['current_attempt'] + 1,
                        updated_at=max(now, task['updated_at']), reason_code=None, error_code=None)
            db.execute('''INSERT INTO task_attempts
                (id,task_id,attempt_no,status,started_at,finished_at,reason_code,lease_owner,lease_expires_at,heartbeat_at)
                VALUES (%s,%s,%s,'running',%s,NULL,NULL,%s,%s,%s)''',
                (str(uuid4()), task_id, task['current_attempt'], now, token, now + timedelta(seconds=LEASE_SECONDS), now))
            TaskStore.update_task(db, task, task_revision)
            TaskStore.append_event(db, task, 'started')
            lease = TaskLease(task_id, task['current_attempt'], token)
            try:
                self.require_owner(db, task)
            except StorageError:
                self._finish(db, task, 'failed', 'task_owner_unavailable')
                return None
            return lease

    def require_lease(self, db, lease):
        row = db.execute('''SELECT t.* FROM tasks t JOIN task_attempts a
            ON a.task_id=t.id AND a.attempt_no=t.current_attempt
            WHERE t.id=%s AND t.current_attempt=%s AND t.status='running'
              AND a.status='running' AND a.lease_owner=%s AND a.lease_expires_at>clock_timestamp()''',
            (lease.task_id, lease.attempt_no, lease.lease_owner)).fetchone()
        if row is None:
            raise LeaseLost()
        return dict(row)

    def heartbeat(self, lease):
        with self.connection(write=True) as db:
            try:
                self.require_lease(db, lease)
            except LeaseLost:
                return False
            now = self.now(db)
            db.execute('''UPDATE task_attempts SET heartbeat_at=%s,lease_expires_at=%s
                WHERE task_id=%s AND attempt_no=%s AND lease_owner=%s''',
                (now, now + timedelta(seconds=LEASE_SECONDS), lease.task_id, lease.attempt_no, lease.lease_owner))
        return True

    def defer(self, lease, seconds=5):
        if type(seconds) is not int or not 0 <= seconds <= 3600:
            raise ValueError('Invalid task continuation delay.')
        with self.connection(write=True) as db:
            task = self.require_lease(db, lease)
            if task['task_type'] not in ('explanation', 'boxplot'):
                raise source_conflict()
            revision = task['revision']
            task.update(revision=revision + 1, updated_at=max(self.now(db), task['updated_at']))
            db.execute('''UPDATE task_attempts SET lease_owner=NULL,lease_expires_at=NULL,heartbeat_at=NULL
                WHERE task_id=%s AND attempt_no=%s''', (lease.task_id, lease.attempt_no))
            TaskStore.update_task(db, task, revision)
            TaskStore.append_event(db, task, 'deferred')
            TaskStore.enqueue(db, task)
            db.execute('''UPDATE task_outbox SET available_at=%s
                WHERE task_id=%s AND task_revision=%s AND event_type='task_ready' ''',
                (task['updated_at'] + timedelta(seconds=seconds), task['id'], task['revision']))
            return TaskStore.public_task(task)

    def sources(self, db, task):
        self.require_owner(db, task)
        snapshot = task['input_snapshot']
        try:
            if task['workflow_version'] != task['task_type'] + '_v1':
                raise source_conflict()
            request = TaskCreateRequest(task_type=task['task_type'], file_id=snapshot['file']['id'],
                analysis_run_id=snapshot['result']['id'], expected_revision=snapshot['result']['setup_revision'],
                figure_id=snapshot['figure']['id'] if snapshot['figure'] is not None else None,
                explanation_id=snapshot['explanation']['id'] if task['task_type'] == 'word_report' else None)
            scoped = TaskStore(task['user_id'], self.config)
            project = scoped.require_project(db, task['project_id'])
            current = scoped.source_snapshot(db, project, request)
            if any(current[key] != snapshot[key] for key in (
                    'file', 'result', 'figure', 'explanation', 'versions', 'output_language')):
                raise source_conflict()
        except (KeyError, TypeError, ValueError) as exc:
            raise source_conflict() from exc
        return {key: snapshot[key] for key in ('project', 'result', 'figure', 'explanation')}

    def load(self, lease):
        with self.connection() as db:
            task = self.require_lease(db, lease)
            snapshot = self.sources(db, task)
        self.assets.original(task['input_snapshot']['file'])
        png = self.assets.figure_png(snapshot['figure'])
        metadata = ReportStore.metadata(snapshot)
        report_id = str(uuid5(REPORT_NAMESPACE, lease.task_id))
        metadata.update(id=report_id, created_at=task['created_at'].astimezone(timezone.utc).isoformat(),
                        filename=f"分析报告-v{snapshot['result']['setup_revision']}-{report_id[:8]}.docx")
        return snapshot, metadata, png

    def load_explanation_task(self, lease):
        """Authorize receipt recovery independently of mutable source validity."""
        with self.connection() as db:
            task = self.require_lease(db, lease)
            if task['task_type'] != 'explanation':
                raise source_conflict()
            self.require_owner(db, task)
            return task

    def load_boxplot_task(self, lease):
        with self.connection() as db:
            task = self.require_lease(db, lease)
            if task['task_type'] != 'boxplot':
                raise source_conflict()
            self.require_owner(db, task)
            return task

    def load_boxplot(self, lease):
        from app.core.config import get_excel_settings
        from app.domain.boxplot_material import build_material
        with self.connection() as db:
            task = self.require_lease(db, lease)
            if task['task_type'] != 'boxplot':
                raise source_conflict()
            snapshot = self.sources(db, task)
        record = task['input_snapshot']['file']
        payload, expected = build_material(snapshot['result'], record, self.assets.original(record), get_excel_settings())
        return task, snapshot, payload, expected

    def boxplot_call(self, lease):
        with self.connection() as db:
            self.require_lease(db, lease)
            row = db.execute("SELECT * FROM model_calls WHERE task_id=%s AND call_key='boxplot:v1'",
                             (lease.task_id,)).fetchone()
            return dict(row) if row else None

    def cached_boxplot(self, lease):
        from app.adapters.openai_plot import PROMPT_VERSION
        with self.connection() as db:
            task = self.require_lease(db, lease)
            row = db.execute('SELECT figure_json FROM figures WHERE analysis_run_id=%s AND renderer_version=%s',
                             (task['input_snapshot']['result']['id'], PROMPT_VERSION)).fetchone()
            try:
                return json.loads(row['figure_json']) if row else None
            except (TypeError, ValueError) as exc:
                raise source_conflict() from exc

    @staticmethod
    def _validate_boxplot_figure(snapshot, figure, content, expected):
        from app.adapters.openai_plot import PROMPT_VERSION, validate_output
        result = snapshot['result']
        try:
            if (figure['analysis_run_id'] != result['id'] or figure['file_id'] != result['file_id']
                    or figure['source_sha256'] != result['source_sha256']
                    or figure['setup_revision'] != result['setup_revision']
                    or figure['language'] != 'zh-CN' or figure['figure_number'] != 1
                    or figure['engine']['id'] != PROMPT_VERSION
                    or figure['engine']['provider'] != 'openai_code_interpreter'
                    or figure['verification']['status'] != 'matched'
                    or str(UUID(figure['id'])) != figure['id']
                    or type(figure['size_bytes']) is not int or not 0 < figure['size_bytes'] <= 12 * 1024 * 1024
                    or len(content) != figure['size_bytes']
                    or hashlib.sha256(content).hexdigest() != figure['sha256']):
                raise source_conflict()
            validate_output({'manifest': figure, 'png': content}, expected)
        except (KeyError, TypeError, ValueError) as exc:
            raise source_conflict() from exc

    @staticmethod
    def _require_boxplot_provenance(db, task, figure, payload):
        from app.adapters.models.openai_responses import canonical_payload
        from app.adapters.openai_plot import INSTRUCTIONS
        from app.domain.model_usage.gateway import input_digest
        call = db.execute("SELECT * FROM model_calls WHERE task_id=%s AND call_key='boxplot:v1'",
                          (task['id'],)).fetchone()
        try:
            provenance = figure['provenance']
            if (not call or call['provider_status'] != 'completed'
                    or provenance['model_call_id'] != call['id']
                    or provenance['response_id'] != call['provider_response_id']
                    or provenance['container_id'] != call['provider_state']['container_id']
                    or provenance['model_input_digest'] != call['input_digest']
                    or input_digest(instructions=INSTRUCTIONS, payload=payload) != call['input_digest']
                    or provenance['input_sha256'] != hashlib.sha256(canonical_payload(payload).encode('utf-8')).hexdigest()
                    or provenance['model'] != call['model'] or figure['engine']['model'] != call['model']):
                raise source_conflict()
        except (KeyError, TypeError, ValueError) as exc:
            raise source_conflict() from exc

    def _figure_candidate_paths(self, task, candidate):
        try:
            basename = candidate['path']
            pattern = re.escape(task['id']) + r'-[1-9][0-9]*-[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}'
            expected_id = str(uuid5(FIGURE_NAMESPACE, task['id']))
            if (not isinstance(basename, str) or not re.fullmatch(pattern, basename)
                    or candidate['figure']['id'] != expected_id):
                raise source_conflict()
        except (KeyError, TypeError, ValueError) as exc:
            raise source_conflict() from exc
        directory = self.assets.directory / 'task-staging'
        return (self.assets.figures_dir / (expected_id + '.png'),
                directory / (basename + '.candidate'), directory / (basename + '.part'))

    def register_figure_candidate(self, lease, snapshot, figure, content, expected, payload):
        saved = {**figure, 'id': str(uuid5(FIGURE_NAMESPACE, lease.task_id)),
                 'sha256': hashlib.sha256(content).hexdigest(), 'size_bytes': len(content)}
        self._validate_boxplot_figure(snapshot, saved, content, expected)
        candidate = {'figure': saved, 'path': f'{lease.task_id}-{lease.attempt_no}-{lease.lease_owner}'}
        with self.connection(write=True) as db:
            task = self.require_lease(db, lease)
            if task['task_type'] != 'boxplot' or self.sources(db, task) != snapshot:
                raise source_conflict()
            self._require_boxplot_provenance(db, task, saved, payload)
            self._figure_candidate_paths(task, candidate)
            db.execute('UPDATE tasks SET figure_candidate=%s::jsonb WHERE id=%s',
                       (json.dumps(candidate, ensure_ascii=False, allow_nan=False), task['id']))
        return candidate

    def write_figure_candidate(self, lease, candidate, content):
        task = self.load_boxplot_task(lease)
        if task.get('figure_candidate') != candidate:
            raise source_conflict()
        _, staged, partial = self._figure_candidate_paths(task, candidate)
        figure = candidate['figure']
        if len(content) != figure['size_bytes'] or hashlib.sha256(content).hexdigest() != figure['sha256']:
            raise source_conflict()
        staged.parent.mkdir(parents=True, exist_ok=True)
        # The durable intent precedes the bytes. A complete .part is recoverable
        # too; an expired writer never removes a registered successor's input.
        with partial.open('xb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(partial, staged)

    def complete_boxplot(self, lease, snapshot, payload, expected, *, cached=None):
        from app.adapters.openai_plot import PROMPT_VERSION
        with self.connection(write=True) as db:
            task = self.require_lease(db, lease)
            if task['task_type'] != 'boxplot' or self.sources(db, task) != snapshot:
                raise source_conflict()
            self.assets.original(task['input_snapshot']['file'])
            existing = db.execute('SELECT figure_json FROM figures WHERE analysis_run_id=%s AND renderer_version=%s',
                                  (snapshot['result']['id'], PROMPT_VERSION)).fetchone()
            if existing:
                saved = json.loads(existing['figure_json'])
                self._validate_boxplot_figure(snapshot, saved, self.assets.figure_png(saved), expected)
            else:
                candidate = task.get('figure_candidate')
                if cached is not None or candidate is None:
                    return None
                target, staged, partial = self._figure_candidate_paths(task, candidate)
                saved = candidate['figure']
                self._require_boxplot_provenance(db, task, saved, payload)
                path = None
                for candidate_path in (target, staged, partial):
                    try:
                        with candidate_path.open('rb') as stream:
                            content = stream.read(12 * 1024 * 1024 + 1)
                    except FileNotFoundError:
                        continue
                    if len(content) == saved['size_bytes'] and hashlib.sha256(content).hexdigest() == saved['sha256']:
                        path = candidate_path
                        break
                if path is None:
                    return None
                self._validate_boxplot_figure(snapshot, saved, content, expected)
                self.assets.figures_dir.mkdir(parents=True, exist_ok=True)
                self.require_lease(db, lease)
                if path != target:
                    os.replace(path, target)
                # Commit failures leave this task's stable target recoverable.
                db.execute('INSERT INTO figures (id,analysis_run_id,renderer_version,figure_json) VALUES (%s,%s,%s,%s)',
                           (saved['id'], snapshot['result']['id'], PROMPT_VERSION,
                            json.dumps(saved, ensure_ascii=False, allow_nan=False)))
                db.execute('UPDATE projects SET updated_at=GREATEST(updated_at,%s) WHERE id=%s',
                           (saved['created_at'], task['project_id']))
            self.require_lease(db, lease)
            task['result_figure_id'] = saved['id']
            db.execute('UPDATE tasks SET figure_candidate=NULL WHERE id=%s', (task['id'],))
            self._finish(db, task, 'succeeded', None)
            return TaskStore.public_task(task)

    def load_explanation(self, lease):
        from app.domain.explanation_content import build_payload
        with self.connection() as db:
            task = self.require_lease(db, lease)
            if task['task_type'] != 'explanation':
                raise source_conflict()
            snapshot = self.sources(db, task)
        self.assets.original(task['input_snapshot']['file'])
        self.assets.figure_png(snapshot['figure'])
        return task, snapshot, build_payload(snapshot['result'], snapshot['figure'])

    def explanation_call(self, lease):
        with self.connection() as db:
            self.require_lease(db, lease)
            row = db.execute("SELECT * FROM model_calls WHERE task_id=%s AND call_key='explanation:v1'",
                             (lease.task_id,)).fetchone()
            return dict(row) if row else None

    def cached_explanation(self, lease):
        from app.domain.explanation_content import VERSION as EXPLANATION_VERSION
        with self.connection() as db:
            task = self.require_lease(db, lease)
            row = db.execute('''SELECT explanation_json FROM explanations
                WHERE figure_id=%s AND engine_version=%s''',
                (task['input_snapshot']['figure']['id'], EXPLANATION_VERSION)).fetchone()
            if not row:
                return None
            try:
                return json.loads(row['explanation_json'])
            except (TypeError, ValueError) as exc:
                raise source_conflict() from exc

    def complete_explanation(self, lease, snapshot, explanation):
        from app.domain.explanation_content import VERSION as EXPLANATION_VERSION
        from app.domain.reports import validate_sources
        with self.connection(write=True) as db:
            task = self.require_lease(db, lease)
            if task['task_type'] != 'explanation' or self.sources(db, task) != snapshot:
                raise source_conflict()
            self.assets.original(task['input_snapshot']['file'])
            self.assets.figure_png(snapshot['figure'])
            self.require_lease(db, lease)
            row = db.execute('''SELECT explanation_json FROM explanations
                WHERE figure_id=%s AND engine_version=%s''',
                (snapshot['figure']['id'], EXPLANATION_VERSION)).fetchone()
            try:
                saved = (json.loads(row['explanation_json']) if row else
                         {**explanation, 'id': str(uuid5(EXPLANATION_NAMESPACE, lease.task_id))})
                validate_sources(snapshot['result'], snapshot['figure'], saved)
            except (TypeError, ValueError, StorageError) as exc:
                raise source_conflict() from exc
            if not row:
                db.execute('''INSERT INTO explanations
                    (id,analysis_run_id,figure_id,engine_version,explanation_json) VALUES (%s,%s,%s,%s,%s)''',
                    (saved['id'], snapshot['result']['id'], snapshot['figure']['id'], EXPLANATION_VERSION,
                     json.dumps(saved, ensure_ascii=False, allow_nan=False)))
                db.execute('UPDATE projects SET updated_at=GREATEST(updated_at,%s) WHERE id=%s',
                           (saved['created_at'], task['project_id']))
            task['result_explanation_id'] = saved['id']
            self._finish(db, task, 'succeeded', None)
            return TaskStore.public_task(task)

    def wait_explanation(self, lease, reason_code, error_code):
        if reason_code not in ('submission_unknown', 'budget_exceeded'):
            raise ValueError('Invalid explanation waiting reason.')
        with self.connection(write=True) as db:
            task = self.require_lease(db, lease)
            self._wait_explanation(db, task, reason_code, error_code)
            return TaskStore.public_task(task)

    def _wait_explanation(self, db, task, reason_code, error_code):
        revision = task['revision']
        task.update(status='waiting_confirmation', revision=revision + 1,
                    updated_at=max(self.now(db), task['updated_at']),
                    reason_code=reason_code, error_code=error_code)
        TaskStore.finish_attempt(db, task)
        TaskStore.update_task(db, task, revision)
        TaskStore.append_event(db, task, 'waiting')
        from app.domain.tasks.waits import persist_wait
        persist_wait(db, task)

    def stage(self, lease, content):
        # Attempt-specific paths prevent a stale worker from deleting a successor's file.
        directory = self.assets.directory / 'task-staging'
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f'{lease.task_id}-{lease.attempt_no}-{lease.lease_owner}.part'
        created = False
        try:
            with path.open('xb') as stream:
                created = True
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError:
            if created:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise
        return path

    def complete(self, lease, snapshot, report, staged, content):
        with self.connection(write=True) as db:
            task = self.require_lease(db, lease)
            current = self.sources(db, task)
            if current != snapshot:
                raise source_conflict()
            # These final reads close source races during rendering; no model or broker I/O.
            self.assets.original(task['input_snapshot']['file'])
            self.assets.figure_png(snapshot['figure'])
            existing = ReportStore.cached(db, snapshot['explanation']['id'])
            if existing:
                self.reports.content(existing)
                saved = existing
            else:
                expected_id = str(uuid5(REPORT_NAMESPACE, lease.task_id))
                if report['id'] != expected_id:
                    raise source_conflict()
                target = self.reports.directory / (expected_id + '.docx')
                if db.execute('SELECT id FROM reports WHERE id=%s', (expected_id,)).fetchone():
                    raise source_conflict()
                # A prior crash may have left only this task's unpublished candidate.
                # Never delete the target on commit failure: commit outcome may be unknown.
                self.reports.directory.mkdir(parents=True, exist_ok=True)
                self.require_lease(db, lease)
                os.replace(staged, target)
                saved = {**report, 'size_bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
                db.execute('''INSERT INTO reports
                    (id,analysis_run_id,explanation_id,renderer_version,report_json,input_json)
                    VALUES (%s,%s,%s,%s,%s,%s)''',
                    (saved['id'], snapshot['result']['id'], snapshot['explanation']['id'], VERSION,
                     json.dumps(saved, ensure_ascii=False, allow_nan=False),
                     json.dumps(snapshot, ensure_ascii=False, allow_nan=False)))
                db.execute('UPDATE projects SET updated_at=GREATEST(updated_at,%s) WHERE id=%s',
                           (saved['created_at'], task['project_id']))
            task['result_report_id'] = saved['id']
            self._finish(db, task, 'succeeded', None)
            return TaskStore.public_task(task)

    def _finish(self, db, task, status, error):
        revision = task['revision']
        task.update(status=status, revision=revision + 1, updated_at=max(self.now(db), task['updated_at']),
                    reason_code='execution_failed' if status == 'failed' else None, error_code=error)
        TaskStore.finish_attempt(db, task)
        TaskStore.update_task(db, task, revision)
        TaskStore.append_event(db, task, status)
        from app.domain.tasks.waits import resolve_open_wait
        resolve_open_wait(db, task, status='superseded')

    def fail(self, lease, error_code):
        with self.connection(write=True) as db:
            task = self.require_lease(db, lease)
            self._finish(db, task, 'failed', error_code)
            return TaskStore.public_task(task)

    def recover_expired(self, limit=20):
        with self.connection(write=True) as db:
            rows = db.execute('''SELECT t.* FROM tasks t JOIN task_attempts a
                ON a.task_id=t.id AND a.attempt_no=t.current_attempt
                WHERE t.task_type IN ('word_report','explanation','boxplot') AND t.status='running' AND a.status='running'
                AND a.lease_expires_at<=clock_timestamp()
                ORDER BY a.lease_expires_at,t.id LIMIT %s''', (limit,)).fetchall()
            for row in rows:
                task = dict(row)
                if task['task_type'] == 'boxplot':
                    call = db.execute("""SELECT status,provider_response_id,provider_state,error_code FROM model_calls
                        WHERE task_id=%s AND call_key='boxplot:v1'""", (task['id'],)).fetchone()
                    if call and not call['provider_response_id']:
                        if call['status'] == 'failed' and call['error_code'] == 'plot_container_expired':
                            self._finish(db, task, 'failed', 'plot_container_expired')
                            continue
                        state = call['provider_state'] or {}
                        uncertain = (call['status'] == 'submission_unknown' or
                            call['status'] == 'submitting' and state.get('phase') not in ('container_ready', 'file_ready'))
                        if uncertain:
                            self._wait_explanation(db, task, 'submission_unknown', 'model_submission_unknown')
                            continue
                if task['task_type'] == 'explanation':
                    call = db.execute("""SELECT status,provider_response_id FROM model_calls
                        WHERE task_id=%s AND call_key='explanation:v1'""", (task['id'],)).fetchone()
                    if (call and not call['provider_response_id']
                            and call['status'] in ('submitting', 'submission_unknown')):
                        self._wait_explanation(db, task, 'submission_unknown', 'model_submission_unknown')
                        continue
                self._finish(db, task, 'failed', 'task_worker_interrupted')
                # Three automatic attempts total. A later explicit user retry still
                # gets one execution, but a lost manual attempt does not restart a loop.
                if task['current_attempt'] >= AUTO_ATTEMPTS:
                    continue
                try:
                    self.require_owner(db, task)
                except StorageError:
                    continue
                revision = task['revision']
                task.update(status='queued', revision=revision + 1, updated_at=max(self.now(db), task['updated_at']),
                            reason_code='retry_requested', error_code=None)
                TaskStore.update_task(db, task, revision)
                TaskStore.append_event(db, task, 'requeued')
                TaskStore.enqueue(db, task)
            return len(rows) + self._recover_boxplot_receipts(db, limit)

    def _recover_boxplot_receipts(self, db, limit):
        """Resume only when a late durable receipt has removed submission uncertainty."""
        rows = db.execute('''SELECT t.*,c.provider_response_id AS recovery_response_id,
                c.status AS recovery_call_status,c.error_code AS recovery_error_code
            FROM tasks t JOIN model_calls c ON c.task_id=t.id AND c.call_key='boxplot:v1'
            JOIN projects p ON p.id=t.project_id AND p.owner_id=t.user_id
            JOIN users u ON u.id=t.user_id AND u.active
            WHERE t.task_type='boxplot' AND t.status='waiting_confirmation'
              AND t.reason_code='submission_unknown' AND c.user_id=t.user_id AND c.project_id=t.project_id
              AND (c.provider_response_id IS NOT NULL
                   OR (c.status='submitting' AND c.provider_state->>'phase' IN ('container_ready','file_ready'))
                   OR (c.status='failed' AND c.error_code='plot_container_expired'))
            ORDER BY t.updated_at,t.id LIMIT %s''', (limit,)).fetchall()
        for row in rows:
            task = dict(row)
            self.require_owner(db, task)
            revision = task['revision']
            now = max(self.now(db), task['updated_at'])
            if (not task['recovery_response_id'] and task['recovery_call_status'] == 'failed'
                    and task['recovery_error_code'] == 'plot_container_expired'):
                task.update(status='failed', revision=revision + 1, updated_at=now,
                            reason_code='execution_failed', error_code='plot_container_expired')
                # This attempt already ended as unknown. The late definitive
                # receipt resolves its outcome without starting another attempt.
                changed = db.execute('''UPDATE task_attempts SET status='failed',finished_at=%s,
                        reason_code='execution_failed',lease_owner=NULL,lease_expires_at=NULL,heartbeat_at=NULL
                    WHERE task_id=%s AND attempt_no=%s AND status='waiting_confirmation'
                      AND reason_code='submission_unknown' ''', (now, task['id'], task['current_attempt']))
                if changed.rowcount != 1:
                    raise source_conflict()
                event = 'failed'
            else:
                task.update(status='queued', revision=revision + 1, updated_at=now,
                            reason_code='confirmation_received', error_code=None)
                event = 'requeued'
            TaskStore.update_task(db, task, revision)
            TaskStore.append_event(db, task, event)
            from app.domain.tasks.waits import resolve_open_wait
            resolve_open_wait(db, task, status='resolved' if event == 'requeued' else 'superseded')
            if event == 'requeued':
                TaskStore.enqueue(db, task)
        return len(rows)
