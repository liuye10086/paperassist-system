"""Short PostgreSQL transactions and fenced task execution/publication."""
from dataclasses import dataclass
from app.domain.statistics_execution.verification import local_numeric_node
from datetime import timedelta, timezone
import hashlib
import json
import os
import re
from pathlib import Path
from uuid import UUID, uuid4, uuid5

from app.adapters.storage import _storage_connection, ProjectStore
from app.adapters.file_objects import LocalFileObjects
from app.adapters.task_store import TaskStore, DatasetTaskAssets, source_conflict, workflow_version, snapshots_match
from app.adapters.report_store import ReportStore
from app.adapters.report_docx import VERSION
from app.core.config import get_data_dir
from app.core.exceptions import StorageError
from app.db.database import get_database_config, ensure_schema_current
from app.domain.tasks.contracts import TaskCreateRequest
from app.domain.tasks.errors import safe_error_code, error_category


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
        self.objects = LocalFileObjects(self.directory)
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
            if (not row or row['task_type'] not in ('word_report', 'explanation', 'boxplot', 'parse_file', 'extract_dataset', 'prepare_dataset', 'review_ocr', 'analysis_plan', 'analysis_recommendation', 'figure_projection', 'figure_workbench', 'figure_explanation', 'collection_word_report', 'statistics_compute', 'literature_search', 'literature_assistance', 'manuscript_draft', 'manuscript_docx', 'pdf_export', 'layout_docx', 'manuscript_writing', 'school_template_parse', 'journal_recommendation', 'journal_format_check', 'journal_adaptation')
                    or (task_type is not None and row['task_type'] != task_type)
                    or row['revision'] != task_revision):
                return None
            task = dict(row)
            now = self.now(db)
            token = str(uuid4())
            if task['status'] == 'running' and task['task_type'] in ('explanation', 'boxplot', 'analysis_recommendation', 'figure_workbench', 'figure_explanation', 'literature_search', 'literature_assistance', 'manuscript_writing'):
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
            if task['task_type'] == 'parse_file':
                from app.domain.file_parsing import sync_file_status
                sync_file_status(db, task, 'parsing')
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
            if task['task_type'] not in ('explanation', 'boxplot', 'analysis_recommendation', 'figure_workbench', 'figure_explanation', 'literature_search', 'literature_assistance', 'manuscript_writing'):
                raise source_conflict()
            revision = task['revision']
            task.update(revision=revision + 1, updated_at=max(self.now(db), task['updated_at']), error_code=None)
            db.execute('''UPDATE task_attempts SET lease_owner=NULL,lease_expires_at=NULL,heartbeat_at=NULL
                WHERE task_id=%s AND attempt_no=%s''', (lease.task_id, lease.attempt_no))
            TaskStore.update_task(db, task, revision)
            TaskStore.append_event(db, task, 'deferred')
            TaskStore.enqueue(db, task)
            db.execute('''UPDATE task_outbox SET available_at=%s
                WHERE task_id=%s AND task_revision=%s AND event_type='task_ready' ''',
                (task['updated_at'] + timedelta(seconds=seconds), task['id'], task['revision']))
            return TaskStore.public_task(task)

    def retry_failure(self, lease, error_code):
        """Atomically record an observed failure and schedule at most three GET retries."""
        with self.connection(write=True) as db:
            task = self.require_lease(db, lease)
            code = safe_error_code(error_code) or 'internal_error'
            if code == 'model_observation_expired':
                self._wait_explanation(db, task, 'observation_expired', code)
                return TaskStore.public_task(task)
            literature_retry = task['task_type'] == 'literature_search' and code == 'ncbi_unavailable'
            if not literature_retry and (code != 'model_provider_unavailable' or task['task_type'] not in ('explanation', 'boxplot', 'analysis_recommendation', 'figure_workbench', 'figure_explanation', 'literature_search', 'literature_assistance', 'manuscript_writing')):
                self._finish(db, task, 'failed', code)
                return TaskStore.public_task(task)
            task['_retry_reason'] = 'temporary_provider_error'
            if task['retry_count'] >= 3:
                self._finish(db, task, 'failed', code)
                return TaskStore.public_task(task)
            revision = task['revision']
            task['retry_count'] += 1
            seconds = (10, 30, 90)[task['retry_count'] - 1]
            task.update(revision=revision + 1, updated_at=max(self.now(db), task['updated_at']), error_code=code,
                        _retry_delay_seconds=seconds)
            db.execute('''UPDATE task_attempts SET error_code=%s,error_category=%s,retry_reason=%s,
                    lease_owner=NULL,lease_expires_at=NULL,heartbeat_at=NULL
                WHERE task_id=%s AND attempt_no=%s''',
                (code, error_category(code), task['_retry_reason'], task['id'], task['current_attempt']))
            TaskStore.update_task(db, task, revision)
            TaskStore.append_event(db, task, 'deferred')
            TaskStore.enqueue(db, task)
            db.execute('''UPDATE task_outbox SET available_at=%s WHERE task_id=%s AND task_revision=%s
                AND event_type='task_ready' ''',
                (task['updated_at'] + timedelta(seconds=seconds), task['id'], task['revision']))
            return TaskStore.public_task(task)

    def sources(self, db, task):
        self.require_owner(db, task)
        if task['task_type'] in ('figure_workbench','figure_explanation'):
            from app.domain.figure_workbench.tasks import require_task_sources
            return require_task_sources(self, db, task)
        snapshot = task['input_snapshot']
        try:
            if task['workflow_version'] != workflow_version(task['task_type'], snapshot):
                raise source_conflict()
            request = TaskCreateRequest(task_type=task['task_type'], file_id=snapshot['file']['id'],
                analysis_run_id=snapshot['result']['id'], expected_revision=snapshot['result']['setup_revision'],
                figure_id=snapshot['figure']['id'] if snapshot['figure'] is not None else None,
                explanation_id=snapshot['explanation']['id'] if task['task_type'] == 'word_report' else None)
            scoped = TaskStore(task['user_id'], self.config)
            project = scoped.require_project(db, task['project_id'])
            current = scoped.source_snapshot(db, project, request, directory=self.assets.directory)
            if not snapshots_match(current, snapshot):
                raise source_conflict()
            from app.domain.descriptive import verify_result
            verify_result(DatasetTaskAssets(task['user_id'],self.config,self.assets.directory),task['project_id'],snapshot['file']['id'],snapshot['result'])
        except (KeyError, TypeError, ValueError) as exc:
            raise source_conflict() from exc
        from app.domain.external_processing import validate_frozen
        if 'source' in snapshot and task['task_type'] in ('boxplot', 'explanation') and snapshot.get('external_processing') is None:
            raise source_conflict()
        if snapshot.get('external_processing') is not None:
            validate_frozen(snapshot, task['task_type'], task['user_id'], snapshot['external_processing'])
        return {key: snapshot[key] for key in ('project', 'result', 'figure', 'explanation', 'external_processing', 'source', 'processing') if key in snapshot}

    def source_file(self, db, task):
        """Resolve current storage only after checking the immutable v1 identity.

        Locator fields belong to the asset record, not the historical statistical
        snapshot. Keep five-field snapshots unchanged so existing equality and
        recovery contracts remain valid, including already queued batch tasks.
        """
        self.require_owner(db, task)
        expected = task['input_snapshot']['file']
        row = db.execute('SELECT * FROM files WHERE id=%s AND project_id=%s',
                         (expected['id'], task['project_id'])).fetchone()
        if (row is None or row['parse_status'] != 'parsed'
                or any(row[key] != expected[key] for key in ('id', 'filename', 'sha256', 'size_bytes', 'file_type'))):
            raise source_conflict()
        return dict(row)

    def dataset(self, task):
        from app.domain.dataset_analysis import load_dataset
        scoped = DatasetTaskAssets(task['user_id'], self.config, self.assets.directory)
        source = task['input_snapshot']['source']
        return load_dataset(scoped, task['project_id'], source['file_id'], source['dataset_id'], expected_source=source)

    def verify_input_asset(self, db, task):
        if 'source' in task['input_snapshot']:
            return self.dataset(task)
        return self.assets.original(self.source_file(db, task))

    @local_numeric_node
    def load(self, lease):
        with self.connection() as db:
            task = self.require_lease(db, lease)
            snapshot = self.sources(db, task)
            record = self.source_file(db, task)
        if 'source' in task['input_snapshot']:
            self.dataset(task)
        else:
            self.assets.original(record)
        png = self.assets.figure_png(snapshot['figure'])
        metadata = ReportStore.metadata(snapshot)
        report_id = str(uuid5(REPORT_NAMESPACE, lease.task_id))
        from app.domain.artifact_contracts import artifact_language
        title="analysis-report" if artifact_language(snapshot["result"])=="en" else "分析报告"
        metadata.update(id=report_id, created_at=task['created_at'].astimezone(timezone.utc).isoformat(),
                        filename=f"{title}-v{snapshot['result']['setup_revision']}-{report_id[:8]}.docx")
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

    @local_numeric_node
    def load_boxplot(self, lease):
        from app.core.config import get_excel_settings
        from app.domain.boxplot_material import build_material
        with self.connection() as db:
            task = self.require_lease(db, lease)
            if task['task_type'] != 'boxplot':
                raise source_conflict()
            snapshot = self.sources(db, task)
            record = self.source_file(db, task)
        if snapshot['result'].get('result_type') in ('regression','roc','survival'):
            from app.domain.modeling_material import load_input,build_material as modeling_material
            data=load_input(DatasetTaskAssets(task['user_id'],self.config,self.assets.directory),task['project_id'],snapshot['result']['file_id'],snapshot['result'])
            payload,expected=modeling_material(snapshot['result'],data['rows'],external=snapshot.get('external_processing'))
        elif snapshot['result'].get('result_type')=='group_comparison':
            from app.domain.comparison.service import load_comparison_input
            from app.domain.comparison_material import build_material as comparison_material
            data=load_comparison_input(DatasetTaskAssets(task['user_id'],self.config,self.assets.directory),task['project_id'],snapshot['result']['file_id'],snapshot['result'])
            payload,expected=comparison_material(snapshot['result'],data['groups'],external=snapshot.get('external_processing'))
        elif snapshot['result'].get('result_type')=='correlation':
            from app.domain.correlation.service import load_correlation_input
            from app.domain.correlation_material import build_material as correlation_material
            data=load_correlation_input(DatasetTaskAssets(task['user_id'],self.config,self.assets.directory),task['project_id'],snapshot['result']['file_id'],snapshot['result'])
            payload,expected=correlation_material(snapshot['result'],data['rows'],external=snapshot.get('external_processing'))
        elif 'source' in task['input_snapshot']:
            record, _, sheet = self.dataset(task)
            payload, expected = build_material(snapshot['result'], record, None, get_excel_settings(),
                external=snapshot.get('external_processing'), dataset_sheet=sheet)
        else:
            payload, expected = build_material(snapshot['result'], record, self.assets.original(record), get_excel_settings(),
                                               external=snapshot.get('external_processing'))
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
            row = db.execute('SELECT figure_json FROM figures WHERE analysis_run_id=%s AND renderer_version=%s AND figure_config_version_id IS NULL',
                             (task['input_snapshot']['result']['id'], task['input_snapshot']['versions']['figure'])).fetchone()
            try:
                return json.loads(row['figure_json']) if row else None
            except (TypeError, ValueError) as exc:
                raise source_conflict() from exc

    @staticmethod
    def _validate_boxplot_figure(snapshot, figure, content, expected):
        from app.adapters.openai_plot import PROMPT_VERSION, validate_output
        result = snapshot['result']
        from app.domain.artifact_contracts import artifact_language,figure_renderer
        PROMPT_VERSION=figure_renderer(result)
        try:
            if snapshot.get('external_processing') is not None and figure.get('external_processing') != snapshot['external_processing']:
                raise source_conflict()
            if (figure['analysis_run_id'] != result['id'] or figure['file_id'] != result['file_id']
                    or figure['source_sha256'] != result['source_sha256']
                    or figure.get('source') != result.get('source')
                    or figure['setup_revision'] != result['setup_revision']
                    or figure['language'] != artifact_language(result) or figure['figure_number'] != 1
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
        from app.domain.external_material import plot_instructions
        instructions = plot_instructions(task['input_snapshot'].get('external_processing'),
                                         result=task['input_snapshot']['result'])
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
                    or input_digest(instructions=instructions, payload=payload) != call['input_digest']
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

    @local_numeric_node
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

    @local_numeric_node
    def complete_boxplot(self, lease, snapshot, payload, expected, *, cached=None):
        from app.domain.artifact_contracts import figure_renderer
        PROMPT_VERSION=figure_renderer(snapshot['result'])
        with self.connection(write=True) as db:
            task = self.require_lease(db, lease)
            if task['task_type'] != 'boxplot' or self.sources(db, task) != snapshot:
                raise source_conflict()
            self.verify_input_asset(db, task)
            existing = db.execute('SELECT figure_json FROM figures WHERE analysis_run_id=%s AND renderer_version=%s AND figure_config_version_id IS NULL',
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

    @local_numeric_node
    def load_explanation(self, lease):
        from app.domain.explanation_content import build_payload
        with self.connection() as db:
            task = self.require_lease(db, lease)
            if task['task_type'] != 'explanation':
                raise source_conflict()
            snapshot = self.sources(db, task)
            record = self.source_file(db, task)
        if 'source' in task['input_snapshot']:
            self.dataset(task)
        else:
            self.assets.original(record)
        self.assets.figure_png(snapshot['figure'])
        from app.domain.external_material import explanation_material
        local, _ = explanation_material(snapshot['result'], snapshot['figure'], snapshot.get('external_processing'))
        return task, snapshot, local

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
                (task['input_snapshot']['figure']['id'], task['input_snapshot']['versions']['explanation'])).fetchone()
            if not row:
                return None
            try:
                return json.loads(row['explanation_json'])
            except (TypeError, ValueError) as exc:
                raise source_conflict() from exc

    @local_numeric_node
    def complete_explanation(self, lease, snapshot, explanation):
        from app.domain.artifact_contracts import explanation_version
        EXPLANATION_VERSION=explanation_version(snapshot['result'])
        from app.domain.reports import validate_sources
        with self.connection(write=True) as db:
            task = self.require_lease(db, lease)
            if task['task_type'] != 'explanation' or self.sources(db, task) != snapshot:
                raise source_conflict()
            self.verify_input_asset(db, task)
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
        if reason_code not in ('submission_unknown', 'budget_exceeded', 'observation_expired'):
            raise ValueError('Invalid explanation waiting reason.')
        with self.connection(write=True) as db:
            task = self.require_lease(db, lease)
            self._wait_explanation(db, task, reason_code, error_code)
            return TaskStore.public_task(task)

    def _wait_explanation(self, db, task, reason_code, error_code):
        revision = task['revision']
        task.update(status='waiting_confirmation', revision=revision + 1,
                    updated_at=max(self.now(db), task['updated_at']),
                    reason_code=reason_code, error_code=safe_error_code(error_code))
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

    @local_numeric_node
    def complete(self, lease, snapshot, report, staged, content):
        with self.connection(write=True) as db:
            task = self.require_lease(db, lease)
            current = self.sources(db, task)
            if current != snapshot:
                raise source_conflict()
            # These final reads close source races during rendering; no model or broker I/O.
            self.verify_input_asset(db, task)
            self.assets.figure_png(snapshot['figure'])
            from app.domain.artifact_contracts import saved_report_version
            existing = ReportStore.cached(db, snapshot['explanation']['id'], saved_report_version(snapshot['explanation']))
            if existing:
                self.reports.content(existing)
                if existing.get('source') != snapshot['result'].get('source'):
                    raise source_conflict()
                saved = existing
            else:
                expected_id = str(uuid5(REPORT_NAMESPACE, lease.task_id))
                if report['id'] != expected_id or report.get('source') != snapshot['result'].get('source'):
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
                    (saved['id'], snapshot['result']['id'], snapshot['explanation']['id'], saved['engine']['id'],
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
                    reason_code='execution_failed' if status == 'failed' else None, error_code=safe_error_code(error))
        TaskStore.finish_attempt(db, task)
        TaskStore.update_task(db, task, revision)
        TaskStore.append_event(db, task, status)
        if task['task_type'] == 'parse_file':
            from app.domain.file_parsing import sync_file_status
            sync_file_status(db, task, 'parsed' if status == 'succeeded' else 'failed', task.get('error_code'))
        if task['task_type'] == 'parse_file' and task['workflow_version'] in ('docx_document_v1', 'pdf_document_v1', 'ocr_document_v1') and status == 'failed':
            db.execute('UPDATE file_parse_results SET completed_at=%s WHERE task_id=%s AND result_json IS NULL',
                       (task['updated_at'],task['id']))
        if task['task_type'] == 'extract_dataset' and status == 'failed':
            db.execute('UPDATE file_structure_versions SET completed_at=%s WHERE task_id=%s AND manifest_json IS NULL',
                       (task['updated_at'],task['id']))
        from app.domain.tasks.waits import resolve_open_wait
        resolve_open_wait(db, task, status='superseded')

    def fail(self, lease, error_code, *, execution_receipt=None):
        if execution_receipt is not None:
            from app.domain.statistics_execution.verification import validate_statistics_receipt
            validate_statistics_receipt(execution_receipt)
            if execution_receipt['status'] != 'failed': raise source_conflict()
        with self.connection(write=True) as db:
            task = self.require_lease(db, lease)
            if execution_receipt is not None: task['execution_receipt'] = execution_receipt
            self._finish(db, task, 'failed', error_code)
            return TaskStore.public_task(task)

    def record_plot_mismatch(self, lease, *, differences, manifest, provenance):
        """Persist bounded numerical mismatch evidence and fail in the same transaction."""
        from psycopg.types.json import Jsonb
        def scalar(value):
            if value is None or type(value) in (bool,int): return value
            if type(value) is float:
                from math import isfinite
                return value if isfinite(value) else str(value)
            if isinstance(value,str): return value[:500]
            return '[structured value omitted]'
        safe_differences=[]
        for difference in list(differences)[:100]:
            if not isinstance(difference,dict): continue
            path=str(difference.get('path',''))[:200]
            if any(word in path.lower() for word in ('rows','values','payload','input','research')): continue
            safe_differences.append(dict(path=path,expected=scalar(difference.get('expected')),
                actual=scalar(difference.get('actual')),reason=scalar(difference.get('reason'))))
        manifest=manifest if isinstance(manifest,dict) else {}
        summary={k:scalar(manifest[k]) for k in ('schema_version','task_type','language','method',
            'figure_kind','correlation_method','mode') if k in manifest}
        statistics=manifest.get('statistics')
        if isinstance(statistics,dict):
            summary['statistics']={k:scalar(statistics[k]) for k in ('n','coefficient') if k in statistics}
        with self.connection(write=True) as db:
            task=self.require_lease(db,lease);self.require_owner(db,task)
            if task['task_type']!='boxplot': raise source_conflict()
            call=db.execute("SELECT * FROM model_calls WHERE task_id=%s AND call_key='boxplot:v1'",(task['id'],)).fetchone()
            if not call or not call['provider_response_id']: raise source_conflict()
            evidence=dict(schema_version=1,status='mismatched',differences=safe_differences,manifest=summary,
                provenance=dict(model_call_id=call['id'],response_id=call['provider_response_id'],
                    model=call['model'],model_input_digest=call['input_digest'],
                    container_id=(call.get('provider_state') or {}).get('container_id')),
                recorded_at=self.now(db).astimezone(timezone.utc).isoformat())
            if isinstance(provenance,dict):
                evidence['provenance'].update({key:scalar(provenance[key])
                    for key in ('png_file_id','result_file_id') if key in provenance})
            db.execute('UPDATE tasks SET verification_failure=%s WHERE id=%s',(Jsonb(evidence),task['id']))
            self._finish(db,task,'failed','plot_result_mismatch')
            return TaskStore.public_task(task)

    def recover_expired(self, limit=20):
        with self.connection(write=True) as db:
            rows = db.execute('''SELECT t.* FROM tasks t JOIN task_attempts a
                ON a.task_id=t.id AND a.attempt_no=t.current_attempt
                WHERE t.task_type IN ('word_report','explanation','boxplot','parse_file','extract_dataset','prepare_dataset', 'review_ocr', 'analysis_plan', 'analysis_recommendation', 'figure_projection', 'figure_workbench', 'figure_explanation', 'collection_word_report', 'statistics_compute', 'literature_search', 'literature_assistance', 'manuscript_draft', 'manuscript_docx', 'pdf_export', 'layout_docx', 'manuscript_writing', 'school_template_parse', 'journal_recommendation', 'journal_format_check', 'journal_adaptation') AND t.status='running' AND a.status='running'
                AND a.lease_expires_at<=clock_timestamp()
                ORDER BY a.lease_expires_at,t.id LIMIT %s''', (limit,)).fetchall()
            for row in rows:
                task = dict(row)
                if task['task_type'] in ('boxplot','figure_workbench'):
                    call = db.execute("""SELECT status,provider_response_id,provider_state,error_code FROM model_calls
                        WHERE task_id=%s AND call_key=%s""", (task['id'], 'figure_workbench:v1' if task['task_type']=='figure_workbench' else 'boxplot:v1')).fetchone()
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
                if task['task_type'] in ('explanation','analysis_recommendation','figure_explanation','literature_assistance','manuscript_writing'):
                    call = db.execute("""SELECT status,provider_response_id FROM model_calls
                        WHERE task_id=%s AND call_key=%s""", (task['id'],('manuscript-writing-v2' if task['workflow_version']=='manuscript_writing_v2' else 'manuscript-writing-v1') if task['task_type']=='manuscript_writing' else 'literature-assistance-v1' if task['task_type']=='literature_assistance' else 'analysis_recommendation:v1' if task['task_type']=='analysis_recommendation' else 'figure_explanation:v1' if task['task_type']=='figure_explanation' else 'explanation:v1')).fetchone()
                    if (call and not call['provider_response_id']
                            and call['status'] in ('submitting', 'submission_unknown')):
                        self._wait_explanation(db, task, 'submission_unknown', 'model_submission_unknown')
                        continue
                if task['task_type'] in ('pdf_export','layout_docx'):
                    # A publication may commit after the scan snapshot. Serialize
                    # recovery with that transaction before touching its files.
                    fresh=db.execute('SELECT * FROM tasks WHERE id=%s FOR UPDATE',(task['id'],)).fetchone()
                    if fresh['status']!='running' or fresh['revision']!=task['revision']: continue
                    expired=db.execute("SELECT id FROM task_attempts WHERE task_id=%s AND attempt_no=%s AND status='running' AND lease_expires_at<=clock_timestamp() FOR UPDATE",(task['id'],task['current_attempt'])).fetchone()
                    if not expired: continue
                    if task['task_type']=='layout_docx':
                        from app.domain.layout_exports.execution import clean_expired_attempt
                    else:
                        from app.domain.pdf_exports.execution import clean_expired_attempt
                    clean_expired_attempt(self,db,task)
                self._finish(db, task, 'failed', 'task_worker_interrupted')
                # Three automatic attempts total. A later explicit user retry still
                # gets one execution, but a lost manual attempt does not restart a loop.
                # Human OCR review saves each start a fresh finite local node;
                # lifetime attempt ordinals include successful human wait cycles.
                if (task['task_type'] in ('review_ocr', 'analysis_plan') and task['retry_count'] >= AUTO_ATTEMPTS-1
                        or task['task_type'] not in ('review_ocr', 'analysis_plan') and task['current_attempt'] >= AUTO_ATTEMPTS):
                    continue
                try:
                    self.require_owner(db, task)
                except StorageError:
                    continue
                revision = task['revision']
                if task['task_type'] in ('review_ocr', 'analysis_plan'):
                    task['retry_count'] += 1
                task.update(status='queued', revision=revision + 1, updated_at=max(self.now(db), task['updated_at']),
                            reason_code='retry_requested', error_code=None, _retry_reason='worker_interrupted')
                TaskStore.update_task(db, task, revision)
                TaskStore.append_event(db, task, 'requeued')
                if task['task_type'] == 'extract_dataset':
                    db.execute('UPDATE file_structure_versions SET completed_at=NULL WHERE task_id=%s AND manifest_json IS NULL',(task['id'],))
                if task['task_type'] == 'parse_file':
                    if task['workflow_version'] in ('docx_document_v1', 'pdf_document_v1', 'ocr_document_v1'):
                        db.execute('UPDATE file_parse_results SET completed_at=NULL WHERE task_id=%s AND result_json IS NULL',
                                   (task['id'],))
                    from app.domain.file_parsing import sync_file_status
                    sync_file_status(db, task, 'queued')
                TaskStore.enqueue(db, task)
            return len(rows) + self._recover_boxplot_receipts(db, limit) + self._recover_recommendation_receipts(db, limit)

    def _recover_recommendation_receipts(self, db, limit):
        rows=db.execute("""SELECT t.* FROM tasks t JOIN model_calls c ON c.task_id=t.id
            JOIN projects p ON p.id=t.project_id AND p.owner_id=t.user_id
            JOIN users u ON u.id=t.user_id AND u.active
            WHERE t.task_type IN ('analysis_recommendation','figure_explanation','literature_assistance','manuscript_writing') AND t.status='waiting_confirmation'
                AND t.reason_code='submission_unknown' AND c.call_key=CASE WHEN t.task_type='manuscript_writing' THEN CASE WHEN t.workflow_version='manuscript_writing_v2' THEN 'manuscript-writing-v2' ELSE 'manuscript-writing-v1' END WHEN t.task_type='literature_assistance' THEN 'literature-assistance-v1' WHEN t.task_type='figure_explanation' THEN 'figure_explanation:v1' ELSE 'analysis_recommendation:v1' END
                AND c.user_id=t.user_id AND c.project_id=t.project_id AND c.provider_response_id IS NOT NULL
            ORDER BY t.updated_at,t.id LIMIT %s""",(limit,)).fetchall()
        from app.domain.tasks.waits import resolve_open_wait
        for row in rows:
            task=dict(row);previous=task['revision']
            task.update(status='queued',revision=previous+1,reason_code='confirmation_received',error_code=None,
                updated_at=max(self.now(db),task['updated_at']))
            TaskStore.update_task(db,task,previous);resolve_open_wait(db,task)
            TaskStore.append_event(db,task,'requeued');TaskStore.enqueue(db,task)
        return len(rows)

    def _recover_boxplot_receipts(self, db, limit):
        """Resume only when a late durable receipt has removed submission uncertainty."""
        rows = db.execute('''SELECT t.*,c.provider_response_id AS recovery_response_id,
                c.status AS recovery_call_status,c.error_code AS recovery_error_code
            FROM tasks t JOIN model_calls c ON c.task_id=t.id AND c.call_key=CASE WHEN t.task_type='figure_workbench' THEN 'figure_workbench:v1' ELSE 'boxplot:v1' END
            JOIN projects p ON p.id=t.project_id AND p.owner_id=t.user_id
            JOIN users u ON u.id=t.user_id AND u.active
            WHERE t.task_type IN ('boxplot','figure_workbench') AND t.status='waiting_confirmation'
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
                        reason_code='execution_failed',lease_owner=NULL,lease_expires_at=NULL,heartbeat_at=NULL,
                        error_code='plot_container_expired',error_category='source'
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
