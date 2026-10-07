import copy
import importlib.util
import json
import sqlite3

import pytest

from tests.maintenance.test_sqlite_import import legacy
from app.maintenance.legacy_import import inspect_source, import_sqlite


def builder():
    assert importlib.util.find_spec('app.maintenance.migration_report'), 'migration report is missing'
    from app.maintenance.migration_report import build_import_verification
    return build_import_verification


def test_report_preserves_old_revisions_and_excludes_business_content(legacy):
    with sqlite3.connect(legacy[0]) as db:
        db.execute("UPDATE analysis_setups SET revision=9, setup_json='{}'")
        db.execute("UPDATE figure_jobs SET job_json=?", (json.dumps({'response_id': 'secret-cloud', 'text': 'secret-research'}),))
    snapshot = inspect_source(*legacy)
    report = builder()(snapshot, snapshot.rows)
    assert report['matches']
    assert all(value['matches'] for value in report['tables'].values())
    assert report['identity_mappings']['analysis_setups'] == [{'source_id': 'file-1', 'target_id': 'file-1', 'matches': True}]
    assert report['job_sequence_mappings']['figure_jobs'][0]['source_rowid'] == 11
    assert all(value['matches'] for value in report['relationships'].values())
    assert all(value['matches'] for value in report['assets'].values())
    assert 'unknown JSON business semantics' in report['scope']['not_verified']
    encoded = json.dumps(report)
    for private in ('secret-cloud', 'secret-research', '保留 原文', 'sections', 'setup_json'):
        assert private not in encoded


def test_report_detects_original_value_and_cross_run_relationship_mismatch(legacy):
    snapshot = inspect_source(*legacy)
    rows = copy.deepcopy(snapshot.rows)
    rows['figures'][0]['analysis_run_id'] = 'absent'
    report = builder()(snapshot, rows)
    assert not report['matches']
    assert not report['tables']['figures']['matches']
    assert not report['relationships']['explanations_figure_run']['matches']


def test_import_returns_verification(legacy):
    result = import_sqlite(*legacy)
    assert result['verification']['matches']


def test_missing_current_setup_is_legal_historical_data(legacy):
    with sqlite3.connect(legacy[0]) as db:
        db.execute('DELETE FROM analysis_setups')
    assert import_sqlite(*legacy)['verification']['matches']


def test_builder_detects_asset_changed_after_snapshot(legacy):
    snapshot = inspect_source(*legacy)
    (legacy[1] / 'files/unreferenced.xlsx').write_bytes(b'changed')
    report = builder()(snapshot, snapshot.rows)
    assert not report['assets']['files/unreferenced.xlsx']['matches']
    assert not report['matches']


def cli(monkeypatch, legacy, report, *extra):
    from scripts import migrate_sqlite
    monkeypatch.setattr('sys.argv', ['migrate_sqlite', '--source', str(legacy[0]), '--data-dir', str(legacy[1]), '--report', str(report), *extra])
    return migrate_sqlite.main()


def test_cli_report_exclusive_and_outside_source(legacy, tmp_path, monkeypatch):
    destination = tmp_path / 'report.json'
    assert cli(monkeypatch, legacy, destination) == 0
    assert json.loads(destination.read_text())['verification']['matches']
    before = destination.read_bytes()
    assert cli(monkeypatch, legacy, destination) == 1
    assert destination.read_bytes() == before
    assert cli(monkeypatch, legacy, legacy[1] / 'forbidden.json') == 1
    assert not (legacy[1] / 'forbidden.json').exists()


def test_cli_reports_postcommit_write_failure_honestly(legacy, tmp_path, monkeypatch, capsys):
    from scripts import migrate_sqlite
    def fail(*args):
        raise OSError('secret connection')
    monkeypatch.setattr(migrate_sqlite, '_write_report', fail, raising=False)
    assert cli(monkeypatch, legacy, tmp_path / 'report.json') == 1
    error = capsys.readouterr().err
    assert 'committed' in error and 'report' in error
    assert 'secret connection' not in error
    assert import_sqlite(*legacy)['status'] == 'already_imported'


def test_cli_failure_report_does_not_claim_rollback_or_leak_driver(legacy, tmp_path, monkeypatch, capsys):
    from contextlib import contextmanager
    from app.db import database
    @contextmanager
    def disconnected(*args, **kwargs):
        raise RuntimeError('secret-driver-password')
        yield
    monkeypatch.setattr(database, 'migration_connection', disconnected)
    destination = tmp_path / 'failure.json'
    assert cli(monkeypatch, legacy, destination) == 1
    report = json.loads(destination.read_text())
    assert report['database_outcome'] == 'unknown'
    error = capsys.readouterr().err
    assert 'unknown' in error
    assert 'rolled back' not in error and 'secret-driver-password' not in error


def test_cli_generic_failure_also_produces_safe_failure_report(legacy, tmp_path, monkeypatch):
    from scripts import migrate_sqlite
    def fail(*args):
        raise RuntimeError('private-driver-value')
    monkeypatch.setattr(migrate_sqlite, 'import_sqlite', fail)
    destination = tmp_path / 'failure.json'
    assert cli(monkeypatch, legacy, destination) == 1
    assert json.loads(destination.read_text())['database_outcome'] == 'unknown'
    assert 'private-driver-value' not in destination.read_text()


def test_cli_migration_failure_has_unknown_database_outcome(legacy, tmp_path, monkeypatch):
    from app.db import database
    def fail():
        raise RuntimeError('migration driver secret')
    monkeypatch.setattr(database, 'migrate_database', fail)
    destination = tmp_path / 'migration-failure.json'
    assert cli(monkeypatch, legacy, destination, '--migrate') == 1
    assert json.loads(destination.read_text())['database_outcome'] == 'unknown'


def test_cli_report_close_failure_is_reported_after_commit(legacy, tmp_path, monkeypatch, capsys):
    from pathlib import Path
    destination = tmp_path / 'close-report.json'
    original = Path.open
    class CloseFailure:
        def __init__(self, stream):
            self.stream = stream
        def __getattr__(self, name):
            return getattr(self.stream, name)
        def close(self):
            self.stream.close()
            raise OSError('private-close-error')
    def opener(path, *args, **kwargs):
        stream = original(path, *args, **kwargs)
        return CloseFailure(stream) if path == destination else stream
    monkeypatch.setattr(Path, 'open', opener)
    assert cli(monkeypatch, legacy, destination) == 1
    error = capsys.readouterr().err
    assert 'committed' in error and 'private-close-error' not in error
