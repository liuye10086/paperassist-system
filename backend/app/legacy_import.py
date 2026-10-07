"""Offline, read-only SQLite import. Never imported by application startup.

Stop all writers before taking a snapshot or importing. PostgreSQL must already
have the current schema. The application keeps using the original asset directory.
"""

from contextlib import closing, contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3


TABLE_COLUMNS = {
    'projects': ('id', 'name', 'research_topic', 'project_type', 'created_at', 'updated_at'),
    'files': ('id', 'project_id', 'filename', 'file_type', 'size_bytes', 'sha256', 'uploaded_at',
              'parse_status', 'error_json', 'preview_json'),
    'analysis_setups': ('file_id', 'revision', 'setup_json'),
    'analysis_runs': ('id', 'file_id', 'setup_revision', 'engine_version', 'completed_at', 'result_json'),
    'figures': ('id', 'analysis_run_id', 'renderer_version', 'figure_json'),
    'figure_jobs': ('id', 'analysis_run_id', 'renderer_version', 'created_at', 'job_json'),
    'explanations': ('id', 'analysis_run_id', 'figure_id', 'engine_version', 'explanation_json'),
    'explanation_jobs': ('id', 'analysis_run_id', 'figure_id', 'engine_version', 'created_at', 'job_json'),
    'reports': ('id', 'analysis_run_id', 'explanation_id', 'renderer_version', 'report_json', 'input_json'),
}
JOB_TABLES = ('figure_jobs', 'explanation_jobs')
ASSET_DIRECTORIES = ('files', 'figures', 'reports')


class ImportError(Exception):
    """An actionable migration failure; never contains a database URL or credentials."""


def _digest(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def _file_identity(path):
    digest = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            size += len(block)
            digest.update(block)
    return {'size_bytes': size, 'sha256': digest.hexdigest()}


@contextmanager
def _readonly_source(source):
    source = Path(source).resolve()
    if not source.is_file():
        raise ImportError('source SQLite file does not exist')
    try:
        # URI read-only mode cannot create, upgrade, checkpoint or modify the DB.
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            yield db
    except sqlite3.Error as exc:
        raise ImportError('source SQLite cannot be read or is corrupt') from exc


def _inventory(directory):
    assets = {}
    for name in ASSET_DIRECTORIES:
        root = directory / name
        if root.is_symlink():
            raise ImportError('asset directories must not be symbolic links')
        if not root.exists():
            continue
        if not root.is_dir():
            raise ImportError('asset directory is not a directory')
        for path in sorted(root.rglob('*')):
            if path.is_symlink() or not path.resolve().is_relative_to(directory):
                raise ImportError('asset paths must remain inside the data directory')
            if path.is_file():
                assets[path.relative_to(directory).as_posix()] = _file_identity(path)
    return assets


def _json_value(raw):
    def reject_constant(value):
        raise ValueError(value)
    try:
        return json.loads(raw, parse_constant=reject_constant)
    except (TypeError, ValueError) as exc:
        raise ImportError('source contains invalid JSON') from exc


def _asset_reference(identifier, folder, suffix, metadata, assets):
    if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', identifier):
        raise ImportError('asset identifier contains an unsafe path')
    relative = f'{folder}/{identifier}{suffix}'
    actual = assets.get(relative)
    if (not isinstance(metadata, dict) or type(metadata.get('size_bytes')) is not int
            or metadata['size_bytes'] < 0 or not isinstance(metadata.get('sha256'), str)):
        raise ImportError(f'asset metadata is invalid: {relative}')
    expected = {'size_bytes': metadata['size_bytes'], 'sha256': metadata['sha256']}
    if actual is None:
        raise ImportError(f'asset is missing: {relative}')
    if actual != expected:
        raise ImportError(f'asset size or SHA-256 differs: {relative}')


@dataclass(frozen=True)
class SourceSnapshot:
    source: Path
    data_directory: Path
    rows: dict
    assets: dict

    @property
    def counts(self):
        return {name: len(rows) for name, rows in self.rows.items()}

    @property
    def hashes(self):
        return {name: _digest(rows) for name, rows in self.rows.items()}

    def manifest(self):
        return {'source': str(self.source), 'data_directory': str(self.data_directory), 'schema_version': 6,
                'counts': self.counts, 'hashes': self.hashes, 'assets': self.assets}


def verify_assets(snapshot):
    """Recheck all files, including unreferenced files retained in backups."""
    try:
        actual = _inventory(snapshot.data_directory)
    except OSError as exc:
        raise ImportError('asset directory cannot be read') from exc
    if actual != snapshot.assets:
        raise ImportError('asset directory changed during the operation; stop writers and retry')
    for row in snapshot.rows['files']:
        _asset_reference(row['id'], 'files', '.xlsx', row, actual)
    for table, column, suffix in [('figures', 'figure_json', '.png'), ('reports', 'report_json', '.docx')]:
        for row in snapshot.rows[table]:
            metadata = _json_value(row[column])
            if not isinstance(metadata, dict) or metadata.get('id') != row['id']:
                raise ImportError(f'asset JSON identifier differs from {table} row')
            _asset_reference(row['id'], table, suffix, metadata, actual)


def inspect_source(source, data_dir):
    """Validate schema 6 and assets without ever changing the source database."""
    source, directory = Path(source).resolve(), Path(data_dir).resolve()
    if not directory.is_dir():
        raise ImportError('asset data directory does not exist')
    with _readonly_source(source) as db:
        if db.execute('PRAGMA user_version').fetchone()[0] != 6:
            raise ImportError('source schema must be version 6; upgrade a separate copy with the matching legacy app')
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ImportError('source integrity check failed')
        found = {row['name'] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if found != set(TABLE_COLUMNS):
            raise ImportError('source schema tables differ from the supported nine-table version')
        rows = {}
        for table, columns in TABLE_COLUMNS.items():
            if tuple(row['name'] for row in db.execute(f'PRAGMA table_info({table})')) != columns:
                raise ImportError(f'source schema columns differ: {table}')
            selected = ','.join(columns) + (',rowid AS seq' if table in JOB_TABLES else '')
            rows[table] = tuple(dict(row) for row in db.execute(f'SELECT {selected} FROM {table} ORDER BY {columns[0]}'))
            for row in rows[table]:
                for column in columns:
                    if column.endswith('_json') and row[column] is not None:
                        _json_value(row[column])
        if db.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise ImportError('source foreign key references are broken')
    try:
        snapshot = SourceSnapshot(source, directory, rows, _inventory(directory))
    except OSError as exc:
        raise ImportError('asset directory cannot be read') from exc
    verify_assets(snapshot)
    return snapshot


def _target_rows(db):
    rows = {}
    for table, columns in TABLE_COLUMNS.items():
        selected = ','.join(columns) + (',seq' if table in JOB_TABLES else '')
        rows[table] = tuple(dict(row) for row in db.execute(f'SELECT {selected} FROM {table} ORDER BY {columns[0]}'))
    return rows


def import_sqlite(source, data_dir, config=None):
    """Atomically import into an empty target, or prove an exact prior import.

    No target schema is created or upgraded here. Any partial or changed target
    fails closed, preserving all its existing data.
    """
    snapshot = inspect_source(source, data_dir)
    from sqlalchemy import text
    from app.database import migration_connection, ensure_schema_current

    try:
        with migration_connection(write=True, config=config) as db:
            ensure_schema_current(db)
            db.execute('LOCK TABLE ' + ','.join(TABLE_COLUMNS) + ' IN ACCESS EXCLUSIVE MODE')
            existing = _target_rows(db)
            if any(existing.values()):
                if existing != snapshot.rows:
                    raise ImportError('target contains unrelated, partial or changed data; import refused')
                status = 'already_imported'
            else:
                for table, columns in TABLE_COLUMNS.items():
                    columns = columns + (('seq',) if table in JOB_TABLES else ())
                    override = ' OVERRIDING SYSTEM VALUE' if table in JOB_TABLES else ''
                    statement = text(f'INSERT INTO {table} ({",".join(columns)}){override} VALUES '
                                     f'({",".join(":" + column for column in columns)})')
                    if snapshot.rows[table]:
                        db.raw_connection.execute(statement, list(snapshot.rows[table]))
                status = 'imported'
            actual = _target_rows(db)
            if actual != snapshot.rows or {name: _digest(rows) for name, rows in actual.items()} != snapshot.hashes:
                raise ImportError('target row counts or full-value hashes differ; transaction rolled back')
            latest = inspect_source(snapshot.source, snapshot.data_directory)
            if latest.rows != snapshot.rows or latest.assets != snapshot.assets:
                raise ImportError('source or asset data changed during import; transaction rolled back')
            from app.migration_report import build_import_verification
            verification = build_import_verification(snapshot, actual)
            if not verification['matches']:
                raise ImportError('target relationship or asset verification failed; transaction rolled back')
            # Unlike setval(), RESTART is transactional and rolls back on failure.
            if status == 'imported':
                for table in JOB_TABLES:
                    next_value = max(0, max((row['seq'] for row in snapshot.rows[table]), default=0)) + 1
                    db.execute(f'ALTER TABLE {table} ALTER COLUMN seq RESTART WITH {next_value}')
    except ImportError:
        raise
    except Exception as exc:
        # Do not print driver errors: they can include credentials or complete rows.
        raise ImportError('PostgreSQL import transaction failed; commit outcome may be unknown; verify or retry the identical source') from exc
    return {'status': status, **snapshot.manifest(), 'verification': verification}


def snapshot_source(source, data_dir, backup_dir):
    """Create a new verified backup; never overwrite or remove any destination."""
    source, directory, backup = Path(source).resolve(), Path(data_dir).resolve(), Path(backup_dir).resolve()
    if backup == directory or backup.is_relative_to(directory) or source.is_relative_to(backup) or backup.exists():
        raise ImportError('backup destination must be new and outside the source data directory')
    snapshot = inspect_source(source, directory)
    try:
        backup.mkdir(parents=True, exist_ok=False)
        target = backup / 'paperassist.sqlite3'
        with _readonly_source(source) as db, closing(sqlite3.connect(target)) as destination:
            db.backup(destination)
        for name in ASSET_DIRECTORIES:
            if (directory / name).exists():
                shutil.copytree(directory / name, backup / name)
        copied = inspect_source(target, backup)
        latest = inspect_source(source, directory)
        if (copied.rows != snapshot.rows or copied.assets != snapshot.assets
                or latest.rows != snapshot.rows or latest.assets != snapshot.assets):
            raise ImportError('backup differs from source; incomplete backup retained for inspection')
        result = copied.manifest()
        result['original_source'] = str(source)
        result['original_data_directory'] = str(directory)
        with (backup / 'manifest.json').open('x', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
        return result
    except OSError as exc:
        raise ImportError('backup could not be completed; partial destination retained for inspection') from exc
