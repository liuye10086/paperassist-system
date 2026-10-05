"""Offline legacy fixtures only; destination tests use the isolated PostgreSQL fixture."""

import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest


LEGACY_SCHEMA = """
CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, research_topic TEXT NOT NULL,
 project_type TEXT NOT NULL CHECK(project_type IN ('sci','thesis')), created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE files (id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), filename TEXT NOT NULL,
 file_type TEXT NOT NULL, size_bytes INTEGER NOT NULL, sha256 TEXT NOT NULL, uploaded_at TEXT NOT NULL,
 parse_status TEXT NOT NULL CHECK(parse_status IN ('parsed','failed')), error_json TEXT, preview_json TEXT);
CREATE TABLE analysis_setups (file_id TEXT PRIMARY KEY REFERENCES files(id), revision INTEGER NOT NULL, setup_json TEXT NOT NULL);
CREATE TABLE analysis_runs (id TEXT PRIMARY KEY, file_id TEXT NOT NULL REFERENCES files(id), setup_revision INTEGER NOT NULL,
 engine_version TEXT NOT NULL, completed_at TEXT NOT NULL, result_json TEXT NOT NULL, UNIQUE(file_id,setup_revision,engine_version));
CREATE TABLE figures (id TEXT PRIMARY KEY, analysis_run_id TEXT NOT NULL REFERENCES analysis_runs(id),
 renderer_version TEXT NOT NULL, figure_json TEXT NOT NULL, UNIQUE(analysis_run_id,renderer_version));
CREATE TABLE figure_jobs (id TEXT PRIMARY KEY, analysis_run_id TEXT NOT NULL REFERENCES analysis_runs(id),
 renderer_version TEXT NOT NULL, created_at TEXT NOT NULL, job_json TEXT NOT NULL);
CREATE TABLE explanations (id TEXT PRIMARY KEY, analysis_run_id TEXT NOT NULL REFERENCES analysis_runs(id),
 figure_id TEXT NOT NULL REFERENCES figures(id), engine_version TEXT NOT NULL, explanation_json TEXT NOT NULL,
 UNIQUE(figure_id,engine_version));
CREATE TABLE explanation_jobs (id TEXT PRIMARY KEY, analysis_run_id TEXT NOT NULL REFERENCES analysis_runs(id),
 figure_id TEXT NOT NULL REFERENCES figures(id), engine_version TEXT NOT NULL, created_at TEXT NOT NULL, job_json TEXT NOT NULL);
CREATE TABLE reports (id TEXT PRIMARY KEY, analysis_run_id TEXT NOT NULL REFERENCES analysis_runs(id),
 explanation_id TEXT NOT NULL REFERENCES explanations(id), renderer_version TEXT NOT NULL, report_json TEXT NOT NULL,
 input_json TEXT NOT NULL, UNIQUE(explanation_id,renderer_version));
PRAGMA user_version=6;
"""


def sha(content):
    return hashlib.sha256(content).hexdigest()


@pytest.fixture
def legacy(tmp_path):
    directory = tmp_path / 'legacy'
    directory.mkdir()
    source = directory / 'paperassist.sqlite3'
    originals = {'files/file-1.xlsx': b'original workbook', 'figures/figure-1.png': b'original PNG',
                 'reports/report-1.docx': b'original DOCX', 'files/unreferenced.xlsx': b'keep orphan too'}
    for relative, content in originals.items():
        target = directory / relative
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(content)
    timestamp = '2026-09-29T01:23:45.123456+00:00'
    figure = json.dumps({'id': 'figure-1', 'size_bytes': len(originals['figures/figure-1.png']),
                         'sha256': sha(originals['figures/figure-1.png'])}, ensure_ascii=False)
    report = json.dumps({'id': 'report-1', 'size_bytes': len(originals['reports/report-1.docx']),
                         'sha256': sha(originals['reports/report-1.docx'])}, ensure_ascii=False)
    with sqlite3.connect(source) as db:
        db.executescript(LEGACY_SCHEMA)
        db.execute('INSERT INTO projects VALUES (?,?,?,?,?,?)', ('project-1', '保留 原文', 'x', 'sci', timestamp, timestamp))
        db.execute('INSERT INTO files VALUES (?,?,?,?,?,?,?,?,?,?)', ('file-1', 'project-1', '原件.xlsx', 'xlsx',
                   len(originals['files/file-1.xlsx']), sha(originals['files/file-1.xlsx']), timestamp, 'parsed', None, '{ "a": 1 }'))
        db.execute('INSERT INTO analysis_setups VALUES (?,?,?)', ('file-1', 2, '{ "revision" : 2, "中文": "值" }'))
        db.execute('INSERT INTO analysis_runs VALUES (?,?,?,?,?,?)', ('run-1', 'file-1', 2, 'engine', timestamp, '{"id": "run-1"}'))
        db.execute('INSERT INTO figures VALUES (?,?,?,?)', ('figure-1', 'run-1', 'renderer', figure))
        for rowid in (3, 11):
            db.execute('INSERT INTO figure_jobs(rowid,id,analysis_run_id,renderer_version,created_at,job_json) VALUES (?,?,?,?,?,?)',
                       (rowid, f'fj-{rowid}', 'run-1', 'renderer', timestamp, '{ "status" : "completed" }'))
        db.execute('INSERT INTO explanations VALUES (?,?,?,?,?)', ('explanation-1', 'run-1', 'figure-1', 'engine', '{"sections": []}'))
        for rowid in (5, 19):
            db.execute('INSERT INTO explanation_jobs(rowid,id,analysis_run_id,figure_id,engine_version,created_at,job_json) VALUES (?,?,?,?,?,?,?)',
                       (rowid, f'ej-{rowid}', 'run-1', 'figure-1', 'engine', timestamp, '{ "status": "completed" }'))
        db.execute('INSERT INTO reports VALUES (?,?,?,?,?,?)', ('report-1', 'run-1', 'explanation-1', 'renderer', report, '{ "preserve" : "空格" }'))
    return source, directory


def importer():
    assert importlib.util.find_spec('app.legacy_import') is not None, 'offline SQLite import implementation is missing'
    from app import legacy_import
    return legacy_import


def target_rows():
    from app.database import database_connection
    module = importer()
    with database_connection() as db:
        return {table: [dict(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY {columns[0]}')]
                for table, columns in module.TABLE_COLUMNS.items()}


def test_inspection_preserves_source_and_records_all_assets(legacy):
    module = importer()
    source, directory = legacy
    before = source.read_bytes()
    snapshot = module.inspect_source(source, directory)
    assert source.read_bytes() == before
    assert snapshot.counts == {name: (2 if name.endswith('_jobs') else 1) for name in module.TABLE_COLUMNS}
    assert snapshot.rows['analysis_setups'][0]['setup_json'] == '{ "revision" : 2, "中文": "值" }'
    assert sorted(row['seq'] for row in snapshot.rows['figure_jobs']) == [3, 11]
    assert snapshot.assets['files/unreferenced.xlsx']['sha256'] == sha(b'keep orphan too')


@pytest.mark.parametrize('change, message', [
    ('version', 'schema'), ('missing_table', 'schema'), ('broken_fk', 'foreign'), ('bad_json', 'JSON'),
])
def test_bad_source_is_rejected_without_changing_it(legacy, change, message):
    module = importer()
    source, directory = legacy
    with sqlite3.connect(source) as db:
        if change == 'version':
            db.execute('PRAGMA user_version=5')
        elif change == 'missing_table':
            db.execute('DROP TABLE reports')
        elif change == 'broken_fk':
            db.execute("UPDATE files SET project_id='missing'")
        else:
            db.execute("UPDATE figure_jobs SET job_json='not JSON'")
    before = source.read_bytes()
    with pytest.raises(module.ImportError, match=message):
        module.inspect_source(source, directory)
    assert source.read_bytes() == before


@pytest.mark.parametrize('relative', ['files/file-1.xlsx', 'figures/figure-1.png', 'reports/report-1.docx'])
@pytest.mark.parametrize('change', ['missing', 'size', 'hash'])
def test_asset_validation_prevents_import(legacy, relative, change):
    module = importer()
    source, directory = legacy
    asset = directory / relative
    if change == 'missing':
        asset.unlink()
    else:
        original = asset.read_bytes()
        asset.write_bytes(b'x' * (len(original) + (change == 'size')))
    with pytest.raises(module.ImportError, match='asset'):
        module.inspect_source(source, directory)


def test_missing_source_is_not_created(tmp_path):
    module = importer()
    missing = tmp_path / 'missing.sqlite3'
    with pytest.raises(module.ImportError, match='source'):
        module.inspect_source(missing, tmp_path)
    assert not missing.exists()


def test_import_preserves_every_value_and_job_order_then_is_idempotent(legacy):
    module = importer()
    source, directory = legacy
    before = source.read_bytes()
    expected = module.inspect_source(source, directory)
    result = module.import_sqlite(source, directory)
    assert result['status'] == 'imported'
    assert result['counts'] == expected.counts
    assert result['hashes'] == expected.hashes
    expected_target = {name: list(rows) for name, rows in expected.rows.items()}
    # Offline imported projects remain unclaimed until first-admin bootstrap.
    expected_target["projects"] = [{**row, "owner_id": None, "default_output_language": "zh-CN"}
                                   for row in expected_target["projects"]]
    assert target_rows() == expected_target
    again = module.import_sqlite(source, directory)
    assert again['status'] == 'already_imported'
    assert source.read_bytes() == before
    from app.database import database_connection
    with database_connection(write=True) as db:
        row = db.execute("INSERT INTO figure_jobs(id,analysis_run_id,renderer_version,created_at,job_json) "
                         "VALUES ('new-fj','run-1','renderer','same','{}') RETURNING seq").fetchone()
        assert row['seq'] == 12
        row = db.execute("INSERT INTO explanation_jobs(id,analysis_run_id,figure_id,engine_version,created_at,job_json) "
                         "VALUES ('new-ej','run-1','figure-1','engine','same','{}') RETURNING seq").fetchone()
        assert row['seq'] == 20


def test_existing_unrelated_target_data_is_never_overwritten(legacy):
    module = importer()
    from app.database import database_connection
    with database_connection(write=True) as db:
        db.execute("INSERT INTO projects (id, name, research_topic, project_type, created_at, updated_at) VALUES ('unrelated','keep','topic','sci','before','before')")
    before = target_rows()
    with pytest.raises(module.ImportError, match='target'):
        module.import_sqlite(*legacy)
    assert target_rows() == before


@pytest.mark.parametrize('version_state', ['wrong_head', 'missing_head', 'missing_table'])
def test_target_without_current_schema_version_is_rejected(legacy, version_state):
    module = importer()
    from app.database import database_connection
    with database_connection(write=True) as db:
        if version_state == 'wrong_head':
            db.execute("UPDATE alembic_version SET version_num='unsupported_version'")
        elif version_state == 'missing_head':
            db.execute('DELETE FROM alembic_version')
        else:
            db.execute('DROP TABLE alembic_version')
    with pytest.raises(module.ImportError):
        module.import_sqlite(*legacy)
    assert all(not rows for rows in target_rows().values())


def test_matching_ids_with_changed_values_are_not_treated_as_same_import(legacy):
    module = importer()
    module.import_sqlite(*legacy)
    from app.database import database_connection
    with database_connection(write=True) as db:
        db.execute("UPDATE projects SET name='changed' WHERE id='project-1'")
    before = target_rows()
    with pytest.raises(module.ImportError, match='target'):
        module.import_sqlite(*legacy)
    assert target_rows() == before


def test_late_insert_failure_rolls_back_all_tables(legacy):
    module = importer()
    from app.database import database_connection
    with database_connection(write=True) as db:
        db.execute("ALTER TABLE reports ADD CONSTRAINT test_reject_report CHECK (id <> 'report-1')")
    with pytest.raises(module.ImportError, match='transaction'):
        module.import_sqlite(*legacy)
    assert all(not rows for rows in target_rows().values())


def test_empty_legacy_database_imports_with_usable_job_sequences(legacy):
    module = importer()
    with sqlite3.connect(legacy[0]) as db:
        for table in reversed(module.TABLE_COLUMNS):
            db.execute(f'DELETE FROM {table}')
    result = module.import_sqlite(*legacy)
    assert result['status'] == 'imported'
    assert all(count == 0 for count in result['counts'].values())
    from app.database import database_connection
    with database_connection(write=True) as db:
        for table in module.JOB_TABLES:
            row = db.execute(f"SELECT nextval(pg_get_serial_sequence('{table}','seq')) AS value").fetchone()
            assert row['value'] == 1


def test_source_changed_during_import_rolls_back(legacy, monkeypatch):
    module = importer()
    from sqlalchemy.engine import Connection
    original_execute = Connection.execute

    def concurrent_change(connection, statement, *args, **kwargs):
        result = original_execute(connection, statement, *args, **kwargs)
        if str(statement).startswith('INSERT INTO reports '):
            with sqlite3.connect(legacy[0]) as writer:
                writer.execute("UPDATE projects SET name='concurrent change'")
        return result

    monkeypatch.setattr(Connection, 'execute', concurrent_change)
    with pytest.raises(module.ImportError, match='source'):
        module.import_sqlite(*legacy)
    assert all(not rows for rows in target_rows().values())


def test_asset_changed_during_import_rolls_back(legacy, monkeypatch):
    module = importer()
    original_verify = module.verify_assets
    calls = 0

    def change_before_verification(snapshot):
        nonlocal calls
        calls += 1
        if calls == 2:
            (legacy[1] / 'reports/report-1.docx').write_bytes(b'changed mid-import')
        return original_verify(snapshot)

    monkeypatch.setattr(module, 'verify_assets', change_before_verification)
    with pytest.raises(module.ImportError, match='asset'):
        module.import_sqlite(*legacy)
    assert all(not rows for rows in target_rows().values())


def test_backup_uses_consistent_database_and_copies_every_asset(legacy, tmp_path):
    module = importer()
    source, directory = legacy
    before = source.read_bytes()
    backup = tmp_path / 'backup'
    result = module.snapshot_source(source, directory, backup)
    assert Path(result['source']) == backup / 'paperassist.sqlite3'
    original = module.inspect_source(source, directory)
    copied = module.inspect_source(backup / 'paperassist.sqlite3', backup)
    assert original.hashes == copied.hashes
    assert original.assets == copied.assets
    assert source.read_bytes() == before
    assert json.loads((backup / 'manifest.json').read_text(encoding='utf-8'))['hashes'] == original.hashes
    with pytest.raises(module.ImportError, match='backup'):
        module.snapshot_source(source, directory, backup)


def test_backup_rejects_destination_within_live_directory(legacy):
    module = importer()
    with pytest.raises(module.ImportError, match='backup'):
        module.snapshot_source(*legacy, legacy[1] / 'backup')


def test_backup_detects_source_changes_while_assets_are_copied(legacy, tmp_path, monkeypatch):
    module = importer()
    original_copy = module.shutil.copytree

    def copy_then_change(source, destination, *args, **kwargs):
        result = original_copy(source, destination, *args, **kwargs)
        with sqlite3.connect(legacy[0]) as writer:
            writer.execute("UPDATE projects SET name='changed during backup'")
        return result

    monkeypatch.setattr(module.shutil, 'copytree', copy_then_change)
    destination = tmp_path / 'backup'
    with pytest.raises(module.ImportError, match='backup'):
        module.snapshot_source(*legacy, destination)
    assert destination.is_dir()
    assert not (destination / 'manifest.json').exists()


def test_backup_includes_committed_wal_contents(legacy, tmp_path):
    module = importer()
    writer = sqlite3.connect(legacy[0])
    try:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute("UPDATE projects SET name='committed in WAL'")
        writer.commit()
        destination = tmp_path / 'wal-backup'
        module.snapshot_source(*legacy, destination)
        snapshot = module.inspect_source(destination / 'paperassist.sqlite3', destination)
        assert snapshot.rows['projects'][0]['name'] == 'committed in WAL'
    finally:
        writer.close()
