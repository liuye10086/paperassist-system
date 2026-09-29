"""PostgreSQL project metadata with immutable local file assets."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError

from .config import get_data_dir
from .database import database_connection, ensure_schema_current, get_database_config, SchemaVersionError


class StorageError(Exception):
    def __init__(self, code: str, message: str, status: int = 503):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


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
        raise StorageError("storage_unavailable", "PostgreSQL暂不可用，请检查数据库连接和权限后重试。") from exc


def check_database_ready():
    with _storage_connection() as db:
        ensure_schema_current(db)


class ProjectStore:
    def __init__(self, directory: Path):
        self.directory = directory
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
        with self.connection() as db:
            return [dict(row) for row in db.execute("""
                SELECT projects.*, (SELECT count(*) FROM files WHERE project_id = projects.id) AS file_count
                FROM projects ORDER BY updated_at DESC, id
            """)]

    def project(self, project_id: str):
        with self.connection() as db:
            row = db.execute("""
                SELECT projects.*, (SELECT count(*) FROM files WHERE project_id = projects.id) AS file_count
                FROM projects WHERE id = %s
            """, (project_id,)).fetchone()
        if row is None:
            raise StorageError("project_not_found", "项目不存在，请刷新项目列表。", 404)
        return dict(row)

    def create_project(self, name: str, research_topic: str, project_type: str):
        project_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self.connection(write=True) as db:
            db.execute("INSERT INTO projects VALUES (%s, %s, %s, %s, %s, %s)",
                       (project_id, name, research_topic, project_type, now, now))
        return self.project(project_id)

    @staticmethod
    def file_record(row):
        result = dict(row)
        error = result.pop("error_json")
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
        file_id = str(uuid4())
        temporary = self.files_dir / f"{file_id}.part"
        target = self.files_dir / f"{file_id}.xlsx"
        now = datetime.now(timezone.utc).isoformat()
        try:
            with temporary.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.rename(target)
            with self.connection(write=True) as db:
                db.execute("INSERT INTO files VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", (
                    file_id, project_id, filename, "xlsx", len(content), hashlib.sha256(content).hexdigest(),
                    now, "failed" if error else "parsed", json.dumps(error, ensure_ascii=False) if error else None, preview,
                ))
                db.execute("UPDATE projects SET updated_at = GREATEST(updated_at, %s) WHERE id = %s", (now, project_id))
        except (OSError, StorageError) as exc:
            # Remove only the two UUID paths created for this failed upload.
            for path in (temporary, target):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass  # An orphan may require cleanup if the disk itself is unavailable.
            if isinstance(exc, StorageError):
                raise
            raise StorageError("storage_unavailable", "文件保存失败，请检查目录权限和磁盘空间后重试。") from exc
        return self.file_record(self.file(project_id, file_id))

    def original(self, record: dict) -> bytes:
        path = self.files_dir / f'{record["id"]}.xlsx'
        try:
            with path.open("rb") as stream:
                content = stream.read(record["size_bytes"] + 1)
        except FileNotFoundError as exc:
            raise StorageError("file_missing", "原始文件已缺失，请恢复数据目录或重新上传。", 410) from exc
        except OSError as exc:
            raise StorageError("storage_unavailable", "无法读取原始文件，请检查目录权限后重试。") from exc
        if len(content) != record["size_bytes"] or hashlib.sha256(content).hexdigest() != record["sha256"]:
            raise StorageError("file_changed", "原始文件已发生变化，请恢复原文件或重新上传。", 409)
        return content

    def analysis_setup(self, project_id: str, file_id: str):
        self.file(project_id, file_id)
        with self.connection() as db:
            row = db.execute('SELECT setup_json FROM analysis_setups WHERE file_id = %s', (file_id,)).fetchone()
        return json.loads(row['setup_json']) if row else None

    def save_analysis_setup(self, project_id: str, file_id: str, expected_revision: int, setup: dict):
        self.file(project_id, file_id)
        with self.connection(write=True) as db:
            row = db.execute('SELECT revision FROM analysis_setups WHERE file_id = %s', (file_id,)).fetchone()
            revision = row['revision'] if row else 0
            if revision != expected_revision:
                raise StorageError('setup_conflict', '分析配置已在其他页面更新，请重新载入配置后再修改。', 409)
            saved = {**setup, 'revision': revision + 1, 'updated_at': datetime.now(timezone.utc).isoformat()}
            db.execute('''INSERT INTO analysis_setups VALUES (%s, %s, %s)
                ON CONFLICT(file_id) DO UPDATE SET revision = excluded.revision, setup_json = excluded.setup_json''',
                (file_id, saved['revision'], json.dumps(saved, ensure_ascii=False, allow_nan=False)))
            db.execute('UPDATE projects SET updated_at = GREATEST(updated_at, %s) WHERE id = %s', (saved['updated_at'], project_id))
        return saved

    def analysis_run(self, project_id: str, file_id: str, revision: int, engine: str):
        self.file(project_id, file_id)
        with self.connection() as db:
            # Check the revision and cache together in one read snapshot.
            self.require_analysis_revision(db, file_id, revision)
            row = db.execute('''SELECT result_json FROM analysis_runs
                WHERE file_id = %s AND setup_revision = %s AND engine_version = %s''',
                (file_id, revision, engine)).fetchone()
        return json.loads(row['result_json']) if row else None

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
            existing = db.execute('''SELECT result_json FROM analysis_runs
                WHERE file_id = %s AND setup_revision = %s AND engine_version = %s''',
                (file_id, revision, engine)).fetchone()
            if existing:
                return json.loads(existing['result_json'])
            saved = {**result, 'id': str(uuid4())}
            db.execute('INSERT INTO analysis_runs VALUES (%s, %s, %s, %s, %s, %s)',
                (saved['id'], file_id, revision, engine, saved['completed_at'],
                 json.dumps(saved, ensure_ascii=False, allow_nan=False)))
            db.execute('UPDATE projects SET updated_at = GREATEST(updated_at, %s) WHERE id = %s',
                (saved['completed_at'], project_id))
        return saved

    def latest_analysis_result(self, project_id: str, file_id: str, engine: str):
        self.file(project_id, file_id)
        with self.connection() as db:
            setup = db.execute('SELECT revision FROM analysis_setups WHERE file_id = %s', (file_id,)).fetchone()
            row = db.execute('''SELECT result_json FROM analysis_runs WHERE file_id = %s
                ORDER BY setup_revision DESC, completed_at DESC, id DESC LIMIT 1''', (file_id,)).fetchone()
        revision = setup['revision'] if setup else None
        result = json.loads(row['result_json']) if row else None
        return {'current_revision': revision, 'result': result,
                'is_current': bool(result and result['setup_revision'] == revision and result['engine']['id'] == engine)}

    def analysis_result_by_id(self, project_id: str, file_id: str, run_id: str):
        self.file(project_id, file_id)
        with self.connection() as db:
            row = db.execute('SELECT result_json FROM analysis_runs WHERE id = %s AND file_id = %s',
                             (run_id, file_id)).fetchone()
        if row is None:
            raise StorageError('result_not_found', '当前文件中没有此统计结果，请重新读取统计结果。', 404)
        return json.loads(row['result_json'])

    def figure_state(self, result: dict, renderer: str, engine: str):
        with self.connection() as db:
            setup = db.execute('SELECT revision FROM analysis_setups WHERE file_id = %s', (result['file_id'],)).fetchone()
            row = db.execute('SELECT figure_json FROM figures WHERE analysis_run_id = %s AND renderer_version = %s',
                             (result['id'], renderer)).fetchone()
        revision = setup['revision'] if setup else None
        return {'current_revision': revision,
                'is_current': revision == result['setup_revision'] and result['engine']['id'] == engine,
                'figure': json.loads(row['figure_json']) if row else None}

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
                existing = db.execute('SELECT figure_json FROM figures WHERE analysis_run_id = %s AND renderer_version = %s',
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
                db.execute('INSERT INTO figures VALUES (%s, %s, %s, %s)', (figure_id, figure['analysis_run_id'],
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
    return ProjectStore(get_data_dir())
