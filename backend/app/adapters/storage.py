"""PostgreSQL project metadata with immutable local file assets."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from fastapi import Request
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_data_dir
from app.adapters.file_objects import LocalFileObjects
from app.db.database import database_connection, ensure_schema_current, get_database_config, SchemaVersionError


PROJECT_UPDATE_LIMITS = {'name': 120, 'research_topic': 500}


from app.core.exceptions import StorageError


@contextmanager
def _storage_connection(write=False, config=None):
    try:
        with database_connection(write=write, config=config) as db:
            yield db
    except ValueError as exc:
        raise StorageError("database_configuration", "PostgreSQL连接配置无效，请检查本项目专用数据库配置。") from exc
    except SchemaVersionError as exc:
        raise StorageError("storage_version", "数据库结构未升级或版本不兼容，请先执行Alembic迁移。") from exc
    except SQLAlchemyError as exc:
        from app.domain.fixed_statistics_runtime import scope_active
        if scope_active() and getattr(getattr(exc,'orig',None),'sqlstate',None) in ('57014','55P03'):
            from app.domain.regression.common import NumericError
            raise NumericError('numeric_timeout','统计节点数据库等待超过期限。') from exc
        raise StorageError("storage_unavailable", "PostgreSQL暂不可用，请检查数据库连接和权限后重试。") from exc


def check_database_ready():
    with _storage_connection() as db:
        ensure_schema_current(db)


class ProjectStore:
    def __init__(self, directory: Path, *, owner_id: str | None = None):
        # None is reserved for trusted local management and recovery workers.
        if owner_id is not None and not owner_id:
            raise ValueError('An owner scope must be non-empty.')
        self.owner_id = owner_id
        self.directory = directory
        self.objects = LocalFileObjects(directory)
        self.files_dir = directory / "files"
        self.figures_dir = directory / "figures"
        try:
            self.db_config = get_database_config()
            self.files_dir.mkdir(parents=True, exist_ok=True)
            with self.connection() as db:
                ensure_schema_current(db)
        except ValueError as exc:
            raise StorageError("database_configuration", "PostgreSQL连接配置无效，请检查本项目专用数据库配置。") from exc
        except OSError as exc:
            raise StorageError("storage_unavailable", "无法访问数据目录，请检查目录权限和磁盘空间。") from exc

    @contextmanager
    def connection(self, write=False):
        with _storage_connection(write=write, config=self.db_config) as db:
            yield db

    def projects(self):
        scope = ' WHERE owner_id = %s' if self.owner_id is not None else ''
        parameters = (self.owner_id,) if self.owner_id is not None else ()
        with self.connection() as db:
            return [dict(row) for row in db.execute("""
                SELECT projects.id, name, research_topic, project_type, default_output_language, created_at, updated_at,
                    (SELECT count(*) FROM files WHERE project_id = projects.id) AS file_count
                FROM projects
            """ + scope + ' ORDER BY updated_at DESC, id', parameters)]

    def query_projects(self, *, page=1, page_size=10, q='', project_type=None) -> dict:
        invalid = StorageError('project_query_invalid',
                               '页码须为1–1000000，页面大小须为1–100，搜索最多120字符，类型仅支持sci或thesis。', 422)
        if (type(page) is not int or not 1 <= page <= 1_000_000
                or type(page_size) is not int or not 1 <= page_size <= 100
                or not isinstance(q, str) or len(q.strip()) > 120
                or (project_type is not None and project_type not in ('sci', 'thesis'))):
            raise invalid
        q = q.strip()
        conditions, parameters = [], []
        if self.owner_id is not None:
            conditions.append('owner_id = %s')
            parameters.append(self.owner_id)
        if project_type is not None:
            conditions.append('project_type = %s')
            parameters.append(project_type)
        if q:
            # strpos provides literal substring semantics without LIKE escapes:
            # percent, underscore, backslash and quotes remain bound data.
            conditions.append('strpos(lower(name), lower(%s)) > 0')
            parameters.append(q)
        where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
        parameters = tuple(parameters)
        projection = '''SELECT projects.id, name, research_topic, project_type, default_output_language, created_at, updated_at,
            (SELECT count(*) FROM files WHERE project_id = projects.id) AS file_count
            FROM projects'''
        # connection() opens one read-only REPEATABLE READ transaction; count
        # and rows use the identical predicates and the same committed snapshot.
        with self.connection() as db:
            total = db.execute('SELECT count(*) AS total FROM projects' + where, parameters).fetchone()['total']
            rows = db.execute(projection + where + ' ORDER BY updated_at DESC, id ASC LIMIT %s OFFSET %s',
                              (*parameters, page_size, (page - 1) * page_size))
            return {'items': [dict(row) for row in rows], 'total': total,
                    'page': page, 'page_size': page_size}

    def project(self, project_id: str):
        scope = ' AND owner_id = %s' if self.owner_id is not None else ''
        parameters = (project_id, self.owner_id) if self.owner_id is not None else (project_id,)
        with self.connection() as db:
            row = db.execute("""
                SELECT projects.id, name, research_topic, project_type, default_output_language, created_at, updated_at,
                    (SELECT count(*) FROM files WHERE project_id = projects.id) AS file_count
                FROM projects WHERE id = %s
            """ + scope, parameters).fetchone()
        if row is None:
            raise StorageError("project_not_found", "项目不存在，请刷新项目列表。", 404)
        return dict(row)

    def create_project(self, name: str, research_topic: str, project_type: str, default_output_language: str = 'zh-CN'):
        if default_output_language not in ('zh-CN', 'en'):
            raise StorageError('project_language_invalid', '项目默认输出语言仅支持中文或英文。', 422)
        project_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self.connection(write=True) as db:
            db.execute("""INSERT INTO projects
                (id, name, research_topic, project_type, created_at, updated_at, owner_id, default_output_language)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                       (project_id, name, research_topic, project_type, now, now, self.owner_id, default_output_language))
        return self.project(project_id)

    def update_project(self, project_id: str, changes: dict) -> dict:
        # This entry point also serves trusted local tools: never rely on HTTP
        # validation for immutable fields or dynamically constructed SQL columns.
        if isinstance(changes, dict) and 'project_type' in changes:
            raise StorageError('project_type_immutable', '项目类型创建后不可更改。', 422)
        invalid = StorageError('project_update_invalid', '请仅提交项目名称或研究主题；名称为1–120字符，主题为1–500字符。', 422)
        if not isinstance(changes, dict) or not changes or changes.keys() - PROJECT_UPDATE_LIMITS.keys():
            raise invalid
        normalized = {}
        for field, limit in PROJECT_UPDATE_LIMITS.items():
            if field in changes:
                value = changes[field]
                if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
                    raise invalid
                normalized[field] = value.strip()

        scope = ' AND owner_id = %s' if self.owner_id is not None else ''
        parameters = (project_id, self.owner_id) if self.owner_id is not None else (project_id,)
        projection = '''projects.id, name, research_topic, project_type, default_output_language, created_at, updated_at,
            (SELECT count(*) FROM files WHERE project_id = projects.id) AS file_count'''
        with self.connection(write=True) as db:
            row = db.execute('SELECT ' + projection + ' FROM projects WHERE id = %s' + scope
                             + ' FOR UPDATE OF projects', parameters).fetchone()
            if row is None:
                raise StorageError('project_not_found', '项目不存在，请刷新项目列表。', 404)
            changed_fields = [field for field in PROJECT_UPDATE_LIMITS
                              if field in normalized and normalized[field] != row[field]]
            if not changed_fields:
                return dict(row)
            # Column names come only from the fixed whitelist; all values and
            # owner identifiers remain parameters. Return within the write lock.
            assignments = ', '.join(field + ' = %s' for field in changed_fields)
            now = datetime.now(timezone.utc).isoformat()
            updated = db.execute('UPDATE projects SET ' + assignments
                                 + ', updated_at = GREATEST(updated_at, %s) WHERE id = %s'
                                 + scope + ' RETURNING ' + projection,
                                 tuple(normalized[field] for field in changed_fields) + (now,) + parameters).fetchone()
            return dict(updated)

    def update_project_language(self, project_id: str, default_output_language: str) -> dict:
        if default_output_language not in ('zh-CN', 'en'):
            raise StorageError('project_language_invalid', '项目默认输出语言仅支持中文或英文。', 422)
        scope = ' AND owner_id = %s' if self.owner_id is not None else ''
        parameters = (project_id, self.owner_id) if self.owner_id is not None else (project_id,)
        projection = '''projects.id, name, research_topic, project_type, default_output_language, created_at, updated_at,
            (SELECT count(*) FROM files WHERE project_id = projects.id) AS file_count'''
        with self.connection(write=True) as db:
            row = db.execute('SELECT ' + projection + ' FROM projects WHERE id = %s' + scope
                             + ' FOR UPDATE OF projects', parameters).fetchone()
            if row is None:
                raise StorageError('project_not_found', '项目不存在，请刷新项目列表。', 404)
            if row['default_output_language'] == default_output_language:
                return dict(row)
            now = datetime.now(timezone.utc).isoformat()
            updated = db.execute('UPDATE projects SET default_output_language = %s, '
                                 'updated_at = GREATEST(updated_at, %s) WHERE id = %s' + scope + ' RETURNING ' + projection,
                                 (default_output_language, now, *parameters)).fetchone()
            return dict(updated)

    @staticmethod
    def file_record(row):
        result = {key: row[key] for key in ('id', 'project_id', 'filename', 'file_type', 'size_bytes',
                                          'sha256', 'uploaded_at', 'parse_status')}
        error = row['error_json']
        result["error"] = json.loads(error) if error else None
        result.pop("preview_json", None)
        return result

    def files(self, project_id: str):
        self.project(project_id)
        with self.connection() as db:
            return [self.file_record(row) for row in db.execute("""
                SELECT id, project_id, filename, file_type, size_bytes, sha256,
                       uploaded_at, parse_status, error_json
                FROM files WHERE project_id = %s ORDER BY uploaded_at DESC, id
            """, (project_id,))]

    def file(self, project_id: str, file_id: str):
        self.project(project_id)
        with self.connection() as db:
            row = db.execute("SELECT * FROM files WHERE project_id = %s AND id = %s", (project_id, file_id)).fetchone()
        if row is None:
            raise StorageError("file_not_found", "当前项目中没有此文件。", 404)
        return dict(row)

    def save_file(self, project_id: str, filename: str, content: bytes, preview: str | None, error: dict | None):
        self.project(project_id)
        operation_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        descriptor = self.objects.put_original(project_id, operation_id, 'xlsx', content)
        file_id = descriptor.id
        # Published bytes survive rollback and unknown commit. Only the byte
        # adapter may clean its own exact unpublished temporary name.
        with self.connection(write=True) as db:
            db.execute("""INSERT INTO files (id, project_id, filename, file_type, size_bytes, sha256,
                uploaded_at, parse_status, error_json, preview_json, uploader_id, object_key, storage_backend)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""", (
                file_id, project_id, filename, descriptor.file_type, descriptor.size_bytes, descriptor.sha256,
                now, "failed" if error else "parsed", json.dumps(error, ensure_ascii=False) if error else None, preview,
                self.owner_id, descriptor.object_key, descriptor.storage_backend,
            ))
            db.execute("UPDATE projects SET updated_at = GREATEST(updated_at, %s) WHERE id = %s", (now, project_id))
        return self.file_record(self.file(project_id, file_id))

    def original(self, record: dict) -> bytes:
        return self.objects.original(record)

    def analysis_setup(self, project_id: str, file_id: str):
        self.file(project_id, file_id)
        with self.connection() as db:
            row = db.execute('SELECT setup_json FROM analysis_setups WHERE file_id = %s', (file_id,)).fetchone()
        saved = json.loads(row['setup_json']) if row else None
        if saved is not None:
            from app.domain.analysis_plan.service import validate_plan_reference
            validate_plan_reference(self, project_id, file_id, saved)
        return saved

    def save_analysis_setup(self, project_id: str, file_id: str, expected_revision: int, setup: dict):
        self.file(project_id, file_id)
        with self.connection(write=True) as db:
            if setup.get('source') is not None:
                from app.domain.dataset_analysis import load_dataset
                load_dataset(self, project_id, file_id, setup['source']['dataset_id'], expected_source=setup['source'])
            saved = self.save_analysis_setup_in_transaction(db, project_id, file_id, expected_revision, setup,
                datetime.now(timezone.utc))
        return saved

    @staticmethod
    def save_analysis_setup_in_transaction(db, project_id, file_id, expected_revision, setup, now):
        """Caller holds the serialized write transaction; publication stays atomic."""
        row = db.execute('SELECT revision FROM analysis_setups WHERE file_id=%s', (file_id,)).fetchone()
        revision = row['revision'] if row else 0
        if revision != expected_revision:
            raise StorageError('setup_conflict', '分析配置已在其他页面更新，请重新载入配置后再修改。', 409)
        saved = {**setup, 'revision': revision + 1, 'updated_at': now.isoformat()}
        db.execute('''INSERT INTO analysis_setups(file_id,revision,setup_json) VALUES (%s,%s,%s)
            ON CONFLICT(file_id) DO UPDATE SET revision=excluded.revision,setup_json=excluded.setup_json''',
            (file_id,saved['revision'],json.dumps(saved,ensure_ascii=False,allow_nan=False)))
        db.execute('UPDATE projects SET updated_at=GREATEST(updated_at,%s) WHERE id=%s',(saved['updated_at'],project_id))
        return saved

    def analysis_run(self, project_id: str, file_id: str, revision: int, engine: str):
        self.file(project_id, file_id)
        with self.connection() as db:
            # Check the revision and cache together in one read snapshot.
            self.require_analysis_revision(db, file_id, revision)
            row = db.execute('''SELECT * FROM analysis_runs
                WHERE file_id = %s AND setup_revision = %s AND engine_version = %s''',
                (file_id, revision, engine)).fetchone()
        result = self.analysis_run_value(row) if row else None
        if result is not None:
            self.validate_analysis_result(project_id, file_id, result)
        return result

    def validate_analysis_result(self, project_id, file_id, result):
        """Validate provenance and any trusted receipt; reads never compute."""
        from app.domain.statistics_execution.verification import require_receipt
        require_receipt(self,project_id,file_id,result)
        if result.get('result_type') in ('regression','roc','survival'):
            from app.domain.modeling_material import load_input
            load_input(self,project_id,file_id,result)
        elif result.get('result_type') == 'correlation':
            from app.domain.correlation.service import load_correlation_input
            load_correlation_input(self, project_id, file_id, result)
        elif result.get('result_type') == 'group_comparison':
            from app.domain.comparison.service import load_comparison_input
            load_comparison_input(self,project_id,file_id,result)
        else:
            from app.domain.analysis_plan.service import validate_plan_reference
            validate_plan_reference(self, project_id, file_id, result)
            from app.domain.descriptive import verify_result
            verify_result(self,project_id,file_id,result)

    @staticmethod
    def analysis_run_value(row):
        """Bind JSON revision to its stored identity before any plan lookup."""
        try:
            value=json.loads(row['result_json'])
            from app.domain.descriptive import result_model
            result_model(value).model_validate(value,strict=True)
            if (value['id']!=row['id'] or value['file_id']!=row['file_id']
                    or type(value['setup_revision']) is not int or value['setup_revision']!=row['setup_revision']
                    or value['engine']['id']!=row['engine_version']):
                raise ValueError('Analysis result identity differs.')
            return value
        except (KeyError,TypeError,ValueError) as exc:
            raise StorageError('task_source_conflict','统计结果与保存版本不一致，请重新读取。',409) from exc

    @staticmethod
    def require_analysis_revision(db, file_id, revision):
        current = db.execute('SELECT revision FROM analysis_setups WHERE file_id = %s', (file_id,)).fetchone()
        if current is None or current['revision'] != revision:
            raise StorageError('setup_conflict', '分析配置已变化或尚未保存，请重新载入配置后再执行。', 409)

    def save_analysis_run(self, project_id: str, file_id: str, result: dict):
        self.file(project_id, file_id)
        with self.connection(write=True) as db:
            revision, engine = result['setup_revision'], result['engine']['id']
            self.require_analysis_revision(db, file_id, revision)
            current = json.loads(db.execute('SELECT setup_json FROM analysis_setups WHERE file_id=%s', (file_id,)).fetchone()['setup_json'])
            from app.domain.analysis_plan.service import validate_plan_reference
            validate_plan_reference(self, project_id, file_id, current)
            validate_plan_reference(self, project_id, file_id, result)
            if current.get('analysis_plan') != result.get('analysis_plan'):
                raise StorageError('source_conflict', '统计计划与当前配置不一致。', 409)
            if current.get('source') != result.get('source'):
                raise StorageError('source_conflict', '分析配置与待发布统计来源不一致。', 409)
            if result.get('source') is not None:
                from app.domain.dataset_analysis import load_dataset
                load_dataset(self, project_id, file_id, result['source']['dataset_id'], expected_source=result['source'])
            existing = db.execute('''SELECT * FROM analysis_runs
                WHERE file_id = %s AND setup_revision = %s AND engine_version = %s''',
                (file_id, revision, engine)).fetchone()
            if existing:
                cached = self.analysis_run_value(existing)
                self.validate_analysis_result(project_id, file_id, cached)
                if cached.get('source') != result.get('source'):
                    raise StorageError('source_conflict', '缓存统计与配置来源不一致。', 409)
                return cached
            saved = {**result, 'id': str(uuid4())}
            db.execute('INSERT INTO analysis_runs(id,file_id,setup_revision,engine_version,completed_at,result_json) VALUES (%s, %s, %s, %s, %s, %s)',
                (saved['id'], file_id, revision, engine, saved['completed_at'],
                 json.dumps(saved, ensure_ascii=False, allow_nan=False)))
            db.execute('UPDATE projects SET updated_at = GREATEST(updated_at, %s) WHERE id = %s',
                (saved['completed_at'], project_id))
        return saved

    def latest_analysis_result(self, project_id: str, file_id: str, engine: str):
        self.file(project_id, file_id)
        with self.connection() as db:
            setup = db.execute('SELECT revision FROM analysis_setups WHERE file_id = %s', (file_id,)).fetchone()
            row = db.execute('''SELECT * FROM analysis_runs WHERE file_id = %s
                ORDER BY setup_revision DESC, completed_at DESC, id DESC LIMIT 1''', (file_id,)).fetchone()
        revision = setup['revision'] if setup else None
        result = self.analysis_run_value(row) if row else None
        if result is not None:
            self.validate_analysis_result(project_id, file_id, result)
        return {'current_revision': revision, 'result': result,
                'is_current': bool(result and result['setup_revision'] == revision and result['engine']['id'] == engine)}

    def analysis_result_by_id(self, project_id: str, file_id: str, run_id: str):
        self.file(project_id, file_id)
        with self.connection() as db:
            row = db.execute('SELECT * FROM analysis_runs WHERE id = %s AND file_id = %s',
                             (run_id, file_id)).fetchone()
        if row is None:
            raise StorageError('result_not_found', '当前文件中没有此统计结果，请重新读取统计结果。', 404)
        result = self.analysis_run_value(row)
        self.validate_analysis_result(project_id, file_id, result)
        return result

    def figure_state(self, result: dict, renderer: str, engine: str):
        with self.connection() as db:
            setup = db.execute('SELECT revision,setup_json FROM analysis_setups WHERE file_id = %s', (result['file_id'],)).fetchone()
            row = db.execute('SELECT figure_json FROM figures WHERE analysis_run_id = %s AND renderer_version = %s AND figure_config_version_id IS NULL',
                             (result['id'], renderer)).fetchone()
        revision = setup['revision'] if setup else None
        current_source = json.loads(setup['setup_json']).get('source') if setup else None
        figure = json.loads(row['figure_json']) if row else None
        if figure is not None and figure.get('source') != result.get('source'):
            raise StorageError('source_conflict', '图表与统计冻结来源不一致。', 409)
        if figure is not None and result.get('result_type') in ('group_comparison','regression','roc','survival'):
            from app.domain.comparison_material import validate_figure_source
            if result.get('result_type') in ('regression','roc','survival'):
                from app.domain.modeling_material import validate_figure_source
            with self.connection() as db:
                file=db.execute('SELECT project_id FROM files WHERE id=%s',(result['file_id'],)).fetchone()
            if file is None:raise StorageError('source_conflict','比较图表的文件来源不存在。',409)
            validate_figure_source(self,file['project_id'],result['file_id'],result,figure)
        return {'current_revision': revision,
                'is_current': revision == result['setup_revision'] and result['engine']['id'] == engine
                    and current_source == result.get('source'),
                'figure': figure}

    def figure_job(self, run_id: str, renderer: str):
        with self.connection() as db:
            row = db.execute('SELECT job_json FROM figure_jobs WHERE analysis_run_id = %s AND renderer_version = %s '
                             'ORDER BY created_at DESC, seq DESC LIMIT 1', (run_id, renderer)).fetchone()
        return json.loads(row['job_json']) if row else None

    def pending_figures(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute('''
                SELECT j.id AS job_id, j.analysis_run_id AS run_id, r.file_id, f.project_id
                FROM figure_jobs j JOIN analysis_runs r ON r.id = j.analysis_run_id JOIN files f ON f.id = r.file_id
                WHERE (j.job_json::jsonb ->> 'status') IN ('running', 'submitting')
                ORDER BY j.created_at
            ''')]

    def begin_figure_job(self, result: dict, renderer: str, payload: dict, expected: dict, model: str, retry: bool):
        with self.connection(write=True) as db:
            self.require_analysis_revision(db, result['file_id'], result['setup_revision'])
            row = db.execute('SELECT job_json FROM figure_jobs WHERE analysis_run_id = %s AND renderer_version = %s '
                             'ORDER BY created_at DESC, seq DESC LIMIT 1', (result['id'], renderer)).fetchone()
            existing = json.loads(row['job_json']) if row else None
            if existing and (existing['status'] not in ('failed', 'uncertain') or not retry):
                return existing, False
            job = {'id': str(uuid4()), 'analysis_run_id': result['id'], 'status': 'submitting',
                   'message_code': 'task_submitting', 'message_params': {},
                   'message': '正在向 OpenAI 提交数据，请勿重复生成。', 'response_id': None, 'container_id': None,
                   'created_at': datetime.now(timezone.utc).isoformat(), 'model': model,
                   'payload': payload, 'expected': expected}
            db.execute('INSERT INTO figure_jobs (id, analysis_run_id, renderer_version, created_at, job_json) VALUES (%s, %s, %s, %s, %s)',
                       (job['id'], result['id'], renderer, job['created_at'], json.dumps(job, ensure_ascii=False, allow_nan=False)))
        return job, True

    def update_figure_job(self, job_id: str, **changes):
        with self.connection(write=True) as db:
            row = db.execute('SELECT job_json FROM figure_jobs WHERE id = %s', (job_id,)).fetchone()
            job = json.loads(row['job_json'])
            # A concurrent poll must not revert a completed download to running/failed.
            if job['status'] == 'completed':
                return job
            job.update(changes)
            db.execute('UPDATE figure_jobs SET job_json = %s WHERE id = %s',
                       (json.dumps(job, ensure_ascii=False, allow_nan=False), job_id))
        return job

    def record_legacy_plot_mismatch(self,job_id,*,differences,manifest,provenance):
        """Commit legacy failure and bounded evidence together; keep saved figures."""
        from math import isfinite
        from app.domain.plot_response import bounded_manifest
        def scalar(value):
            if value is None or type(value) in (bool,int):return value
            if type(value) is float:return value if isfinite(value) else str(value)
            if isinstance(value,str):return value[:500]
            return '[structured value omitted]'
        safe=[]
        for item in list(differences)[:100]:
            if not isinstance(item,dict):continue
            path=str(item.get('path',''))[:200]
            if any(word in path.lower() for word in ('rows','values','payload','input','research','id_column')):continue
            safe.append(dict(path=path,expected=scalar(item.get('expected')),actual=scalar(item.get('actual')),reason=scalar(item.get('reason'))))
        evidence=dict(schema_version=1,status='mismatched',differences=safe,manifest=bounded_manifest(manifest),
            provenance={key:scalar(provenance[key]) for key in ('response_id','container_id','model','prompt_version','png_file_id','result_file_id')
                if isinstance(provenance,dict) and key in provenance},recorded_at=datetime.now(timezone.utc).isoformat())
        with self.connection(write=True) as db:
            scope=' AND p.owner_id=%s' if self.owner_id is not None else ''
            parameters=(job_id,self.owner_id) if self.owner_id is not None else (job_id,)
            row=db.execute('''SELECT j.job_json FROM figure_jobs j JOIN analysis_runs r ON r.id=j.analysis_run_id
                JOIN files f ON f.id=r.file_id JOIN projects p ON p.id=f.project_id WHERE j.id=%s'''+scope+' FOR UPDATE OF j',parameters).fetchone()
            if row is None:raise StorageError('result_not_found','绘图任务不存在或不可访问。',404)
            job=json.loads(row['job_json'])
            if job['status']=='completed':return job
            job.update(status='failed',message_code='plot_result_mismatch',message_params={},
                message='云端计算结果、标签或图注与本地核对不一致，差异已保留，未发布图表。',differences=safe,output_json=evidence)
            db.execute('UPDATE figure_jobs SET job_json=%s WHERE id=%s',(json.dumps(job,ensure_ascii=False,allow_nan=False),job_id))
        return job

    def figure_png(self, figure: dict):
        path = self.figures_dir / (figure['id'] + '.png')
        try:
            with path.open('rb') as stream:
                content = stream.read(figure['size_bytes'] + 1)
        except FileNotFoundError as exc:
            raise StorageError('figure_missing', '已保存的图片缺失，请恢复完整数据目录；也可另存配置并重新统计、生成新图。', 410) from exc
        except OSError as exc:
            raise StorageError('storage_unavailable', '无法读取图片，请检查目录权限。') from exc
        if len(content) != figure['size_bytes'] or hashlib.sha256(content).hexdigest() != figure['sha256']:
            raise StorageError('figure_changed', '已保存的图片内容发生变化，请恢复原图或另存配置生成新图。', 409)
        return content

    def save_figure(self, project_id: str, file_id: str, figure: dict, content: bytes):
        self.analysis_result_by_id(project_id, file_id, figure['analysis_run_id'])
        figure_id = str(uuid4())
        temporary, target = (self.figures_dir / (figure_id + suffix) for suffix in ('.part', '.png'))
        try:
            with self.connection(write=True) as db:
                self.require_analysis_revision(db, file_id, figure['setup_revision'])
                existing = db.execute('SELECT figure_json FROM figures WHERE analysis_run_id = %s AND renderer_version = %s AND figure_config_version_id IS NULL',
                    (figure['analysis_run_id'], figure['engine']['id'])).fetchone()
                if existing:
                    saved = json.loads(existing['figure_json'])
                    self.figure_png(saved)
                    return saved
                self.figures_dir.mkdir(parents=True, exist_ok=True)
                with temporary.open('xb') as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                temporary.rename(target)
                saved = {**figure, 'id': figure_id, 'size_bytes': len(content),
                         'sha256': hashlib.sha256(content).hexdigest()}
                db.execute('INSERT INTO figures(id,analysis_run_id,renderer_version,figure_json) VALUES (%s, %s, %s, %s)', (figure_id, figure['analysis_run_id'],
                    figure['engine']['id'], json.dumps(saved, ensure_ascii=False, allow_nan=False)))
                db.execute('UPDATE projects SET updated_at = GREATEST(updated_at, %s) WHERE id = %s',
                           (saved['created_at'], project_id))
            return saved
        except (OSError, StorageError) as exc:
            # Only clean up this attempt's new UUID paths, never existing artifacts.
            for path in (temporary, target):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            if isinstance(exc, StorageError):
                raise
            raise StorageError('storage_unavailable', '图片保存失败，请检查目录权限和磁盘空间。') from exc


def get_project_store() -> ProjectStore:
    """Trusted system scope for recovery workers and local administration only."""
    return ProjectStore(get_data_dir())


def get_request_project_store(request: Request) -> ProjectStore:
    """An HTTP request must never fall back to the system-wide store."""
    user = getattr(request.state, 'user', None)
    if not isinstance(user, dict) or not isinstance(user.get('id'), str) or not user['id']:
        raise StorageError('authentication_required', '请先登录。', 401)
    return ProjectStore(get_data_dir(), owner_id=user['id'])
