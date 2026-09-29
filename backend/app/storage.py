"""Local project metadata and immutable original files; no shared DB connections."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from .config import get_data_dir


class StorageError(Exception):
    def __init__(self, code: str, message: str, status: int = 503):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


class ProjectStore:
    def __init__(self, directory: Path):
        self.directory = directory
        self.files_dir = directory / "files"
        try:
            self.files_dir.mkdir(parents=True, exist_ok=True)
            with self.connection() as db:
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, 1, 2, 3):
                    raise StorageError("storage_version", "数据版本不兼容，请使用对应版本的程序。")
                if version == 3:
                    return
                db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE IF NOT EXISTS projects (
                        id TEXT PRIMARY KEY, name TEXT NOT NULL, research_topic TEXT NOT NULL,
                        project_type TEXT NOT NULL CHECK(project_type IN ('sci', 'thesis')),
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS files (
                        id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                        filename TEXT NOT NULL, file_type TEXT NOT NULL, size_bytes INTEGER NOT NULL,
                        sha256 TEXT NOT NULL, uploaded_at TEXT NOT NULL,
                        parse_status TEXT NOT NULL CHECK(parse_status IN ('parsed', 'failed')),
                        error_json TEXT, preview_json TEXT
                    );
                    CREATE INDEX IF NOT EXISTS files_project ON files(project_id, uploaded_at DESC);
                    CREATE TABLE IF NOT EXISTS analysis_setups (
                        file_id TEXT PRIMARY KEY REFERENCES files(id),
                        revision INTEGER NOT NULL, setup_json TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS analysis_runs (
                        id TEXT PRIMARY KEY, file_id TEXT NOT NULL REFERENCES files(id),
                        setup_revision INTEGER NOT NULL, engine_version TEXT NOT NULL,
                        completed_at TEXT NOT NULL, result_json TEXT NOT NULL,
                        UNIQUE(file_id, setup_revision, engine_version)
                    );
                    PRAGMA user_version = 3;
                    COMMIT;
                """)
        except OSError as exc:
            raise StorageError("storage_unavailable", "无法访问数据目录，请检查目录权限和磁盘空间。") from exc

    @contextmanager
    def connection(self):
        db = None
        try:
            db = sqlite3.connect(self.directory / "paperassist.sqlite3", timeout=10)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys = ON")
            with db:
                yield db
        except sqlite3.Error as exc:
            raise StorageError("storage_unavailable", "数据存储暂不可用，请检查磁盘空间或稍后重试。") from exc
        finally:
            if db is not None:
                db.close()

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
                FROM projects WHERE id = ?
            """, (project_id,)).fetchone()
        if row is None:
            raise StorageError("project_not_found", "项目不存在，请刷新项目列表。", 404)
        return dict(row)

    def create_project(self, name: str, research_topic: str, project_type: str):
        project_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as db:
            db.execute("INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?)",
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
                FROM files WHERE project_id = ? ORDER BY uploaded_at DESC, id
            """, (project_id,))]

    def file(self, project_id: str, file_id: str):
        self.project(project_id)
        with self.connection() as db:
            row = db.execute("SELECT * FROM files WHERE project_id = ? AND id = ?", (project_id, file_id)).fetchone()
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
            with self.connection() as db:
                db.execute("INSERT INTO files VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
                    file_id, project_id, filename, "xlsx", len(content), hashlib.sha256(content).hexdigest(),
                    now, "failed" if error else "parsed", json.dumps(error, ensure_ascii=False) if error else None, preview,
                ))
                db.execute("UPDATE projects SET updated_at = MAX(updated_at, ?) WHERE id = ?", (now, project_id))
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
            row = db.execute('SELECT setup_json FROM analysis_setups WHERE file_id = ?', (file_id,)).fetchone()
        return json.loads(row['setup_json']) if row else None

    def save_analysis_setup(self, project_id: str, file_id: str, expected_revision: int, setup: dict):
        self.file(project_id, file_id)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT revision FROM analysis_setups WHERE file_id = ?', (file_id,)).fetchone()
            revision = row['revision'] if row else 0
            if revision != expected_revision:
                raise StorageError('setup_conflict', '分析配置已在其他页面更新，请重新载入配置后再修改。', 409)
            saved = {**setup, 'revision': revision + 1, 'updated_at': datetime.now(timezone.utc).isoformat()}
            db.execute('''INSERT INTO analysis_setups VALUES (?, ?, ?)
                ON CONFLICT(file_id) DO UPDATE SET revision = excluded.revision, setup_json = excluded.setup_json''',
                (file_id, saved['revision'], json.dumps(saved, ensure_ascii=False, allow_nan=False)))
            db.execute('UPDATE projects SET updated_at = MAX(updated_at, ?) WHERE id = ?', (saved['updated_at'], project_id))
        return saved

    def analysis_run(self, project_id: str, file_id: str, revision: int, engine: str):
        self.file(project_id, file_id)
        with self.connection() as db:
            # Check the revision and cache together in one read snapshot.
            db.execute('BEGIN')
            self.require_analysis_revision(db, file_id, revision)
            row = db.execute('''SELECT result_json FROM analysis_runs
                WHERE file_id = ? AND setup_revision = ? AND engine_version = ?''',
                (file_id, revision, engine)).fetchone()
        return json.loads(row['result_json']) if row else None

    @staticmethod
    def require_analysis_revision(db, file_id, revision):
        current = db.execute('SELECT revision FROM analysis_setups WHERE file_id = ?', (file_id,)).fetchone()
        if current is None or current['revision'] != revision:
            raise StorageError('setup_conflict', '分析配置已变化或尚未保存，请重新载入配置后再执行。', 409)

    def save_analysis_run(self, project_id: str, file_id: str, result: dict):
        self.file(project_id, file_id)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            revision, engine = result['setup_revision'], result['engine']['id']
            self.require_analysis_revision(db, file_id, revision)
            existing = db.execute('''SELECT result_json FROM analysis_runs
                WHERE file_id = ? AND setup_revision = ? AND engine_version = ?''',
                (file_id, revision, engine)).fetchone()
            if existing:
                return json.loads(existing['result_json'])
            saved = {**result, 'id': str(uuid4())}
            db.execute('INSERT INTO analysis_runs VALUES (?, ?, ?, ?, ?, ?)',
                (saved['id'], file_id, revision, engine, saved['completed_at'],
                 json.dumps(saved, ensure_ascii=False, allow_nan=False)))
            db.execute('UPDATE projects SET updated_at = MAX(updated_at, ?) WHERE id = ?',
                (saved['completed_at'], project_id))
        return saved

    def latest_analysis_result(self, project_id: str, file_id: str, engine: str):
        self.file(project_id, file_id)
        with self.connection() as db:
            db.execute('BEGIN')
            setup = db.execute('SELECT revision FROM analysis_setups WHERE file_id = ?', (file_id,)).fetchone()
            row = db.execute('''SELECT result_json FROM analysis_runs WHERE file_id = ?
                ORDER BY setup_revision DESC, completed_at DESC, id DESC LIMIT 1''', (file_id,)).fetchone()
        revision = setup['revision'] if setup else None
        result = json.loads(row['result_json']) if row else None
        return {'current_revision': revision, 'result': result,
                'is_current': bool(result and result['setup_revision'] == revision and result['engine']['id'] == engine)}


def get_project_store() -> ProjectStore:
    return ProjectStore(get_data_dir())
