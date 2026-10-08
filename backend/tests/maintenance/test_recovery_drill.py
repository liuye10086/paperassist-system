"""Pure safety tests: intentionally bypass the shared database fixture."""
import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path
import pytest
from app.db.database import SCHEMA_HEAD


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def module():
    from app.maintenance import recovery_drill
    return recovery_drill


@pytest.mark.parametrize('revision,expected_code', [(SCHEMA_HEAD, 0), ('0005_ownership_indexes', 1)])
def test_recovery_upgrade_targets_the_current_application_head(monkeypatch, tmp_path, revision, expected_code):
    """Exercise the orchestration without creating a cluster or connecting anywhere."""
    import json
    from types import SimpleNamespace
    import psycopg
    from app.db.database import SCHEMA_HEAD
    m = module()
    folder, source = tmp_path / 'run', tmp_path / 'source'
    folder.mkdir()
    source.mkdir()
    (source / 'assets').mkdir()
    (source / 'before-fingerprints.json').write_text('{}')
    (source / 'asset-manifest.json').write_text('[]')
    calls = []

    class Connection:
        def __init__(self, database):
            self.database = database

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, statement, *args):
            text = str(statement)
            if 'current_database()' in text:
                value = (self.database, 23456)
            elif 'SHOW data_directory' in text:
                value = (str(folder / 'cluster'),)
            elif 'SHOW listen_addresses' in text:
                value = ('127.0.0.1',)
            elif 'SELECT version_num' in text:
                value = (revision,)
            else:
                value = (0,)
            return SimpleNamespace(fetchone=lambda: value)

    def fake_run(args, **kwargs):
        calls.append(args)
        if str(args[0]).endswith('initdb.exe'):
            (folder / 'cluster').mkdir()
            (folder / 'cluster' / 'postgresql.conf').write_text('')
        return b'{"ok":true}' if 'app.maintenance.database_audit' in args else b''

    monkeypatch.setattr(psycopg, 'connect', lambda **kwargs: Connection(kwargs['dbname']))
    monkeypatch.setattr(m, 'run', fake_run)
    monkeypatch.setattr(m, 'run_pg_ctl', lambda *args, **kwargs: None)
    monkeypatch.setattr(m, 'free_port', lambda: 23456)
    monkeypatch.setattr(m, 'port_closed', lambda _: True)
    monkeypatch.setattr(m, 'private_file', lambda path, contents: path.write_text(contents))
    monkeypatch.setattr(m, 'safe_extract', lambda *args: None)
    monkeypatch.setattr(m, 'app_validation', lambda *args: None)
    monkeypatch.setattr(m, 'fingerprints', lambda *args, **kwargs: {})
    monkeypatch.setattr(m, 'sequence_state', lambda *args: {})
    args = SimpleNamespace(pg_bin=tmp_path, legacy_ref='a' * 40)
    assert m.execute(args, folder, source, tmp_path, {}) == expected_code
    target = json.loads((folder / 'upgrade_current_head.json').read_text())
    assert target['target_revision'] == SCHEMA_HEAD
    assert any(call[-3:] == ['-m', 'app.db.database', 'upgrade'] for call in calls)
    result = json.loads((folder / 'result.json').read_text())
    assert result['status'] == ('complete' if expected_code == 0 else 'failed')
    assert result['failure'] == (None if expected_code == 0 else 'unexpected_final_revision')


def test_prepare_rejects_existing_destination(tmp_path):
    m = module()
    with pytest.raises(m.DrillError):
        m.new_run_directory(tmp_path)


def test_archive_traversal_is_rejected_before_extraction(tmp_path):
    m = module()
    archive = tmp_path / 'bad.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('backend/app/__init__.py', '')
        z.writestr('../escape', 'unsafe')
    with pytest.raises(m.DrillError):
        m.safe_extract(archive, tmp_path / 'out')
    assert not (tmp_path / 'escape').exists()


@pytest.mark.parametrize('database,port,directory', [
    ('paperassist_system', 23456, 'cluster'),
    ('paperassist_system_test', 5432, 'cluster'),
    ('paperassist_system_test', 23456, 'other'),
])
def test_server_identity_requires_all_guards(tmp_path, database, port, directory):
    m = module()
    with pytest.raises(m.DrillError):
        m.validate_identity(database, port, tmp_path / directory,
                            expected_port=23456, expected_directory=tmp_path / 'cluster')


def test_child_environment_drops_inherited_connections_and_python_path(tmp_path):
    m = module()
    env = m.clean_environment({'PATH': 'ok', 'PGSERVICE': 'bad', 'PGOPTIONS': 'bad',
        'PYTHONPATH': 'bad', 'PAPERASSIST_DATABASE_URL': 'secret', 'OPENAI_API_KEY': 'secret'})
    assert env == {'PATH': 'ok', 'PYTHONNOUSERSITE': '1', 'OPENAI_API_KEY': '',
                   'PAPERASSIST_PLOT_WORKER_ENABLED': '0'}


def test_sequence_parser_ignores_business_text():
    m = module()
    assert m.archive_sequences(b"SELECT pg_catalog.setval('public.jobs_seq', 42, true);\n") == {'jobs_seq': [42, True]}
    with pytest.raises(m.DrillError):
        m.archive_sequences(b"SELECT pg_catalog.setval('evil.jobs_seq', 42, true);\n")


def test_fingerprint_preserves_json_original_text():
    m = module()
    assert m.rows_fingerprint([{'json': '{"a": 1}'}]) != m.rows_fingerprint([{'json': '{"a":1}'}])
    assert m.rows_fingerprint([{'id': 1}, {'id': 2}]) == m.rows_fingerprint([{'id': 2}, {'id': 1}])


def test_fingerprint_supports_native_task_wait_times_and_jsonb():
    """Match the migration backup encoding without rewriting legacy JSON text."""
    import hashlib
    import json
    m = module()
    timestamp = datetime(2026, 10, 8, 1, 2, 3, 456789, tzinfo=timezone.utc)
    rows = [{'id': 'wait', 'created_at': timestamp, 'resolved_at': None,
             'payload': {'values': [1, True, None]}, 'legacy_json': '{"a": 1}'}]
    encoded = json.dumps({**rows[0], 'created_at': timestamp.isoformat()},
                         ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    assert m.rows_fingerprint(rows) == hashlib.sha256(encoded.encode('utf-8')).hexdigest()
    assert m.rows_fingerprint(rows) != m.rows_fingerprint([
        {**rows[0], 'created_at': timestamp.replace(microsecond=456788)}])


def test_fingerprint_rejects_unknown_objects_instead_of_stringifying_them():
    class Unserializable:
        def __str__(self):
            return 'business-content'
    with pytest.raises(TypeError):
        module().rows_fingerprint([{'value': Unserializable()}])


def test_prepare_does_not_execute_cluster(monkeypatch, tmp_path, capsys):
    m = module()
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'assets').mkdir()
    (source / 'database.dump').write_bytes(b'archive')
    import json
    (source / 'backup-verification.json').write_text(json.dumps({'backup_sha256': m.sha(source / 'database.dump')}))
    (source / 'asset-manifest.json').write_text('[]')
    calls = []
    def fake_run(args, **kwargs):
        calls.append(args)
        if 'rev-parse' in args:
            return b'a' * 40
        if '--version' in args:
            return b'pg_restore (PostgreSQL) 18.1'
        return b'5; 2615 2200 SCHEMA - public pg_database_owner'
    monkeypatch.setattr(m, 'run', fake_run)
    output = tmp_path / 'output'
    monkeypatch.setattr(m, 'new_run_directory', lambda _: (output.mkdir(), output)[1])
    monkeypatch.setattr(m, 'execute', lambda *args: pytest.fail('prepare executed cluster'))
    assert m.main(['--source-backup', str(source), '--legacy-ref', 'a' * 40]) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'prepared'
    assert not any('initdb' in str(arg) for args in calls for arg in args)


@pytest.mark.parametrize('server_started', [True, False])
def test_interrupt_during_start_cleans_up_and_never_reports_complete(monkeypatch, tmp_path, server_started):
    import json
    from types import SimpleNamespace
    m = module()
    folder = tmp_path / 'run'
    folder.mkdir()
    calls = []
    def fake_run(args, **kwargs):
        calls.append([str(arg) for arg in args])
        if str(args[0]).endswith('initdb.exe'):
            (folder / 'cluster').mkdir()
            (folder / 'cluster' / 'postgresql.conf').write_text('')
        if args[-1] == 'start':
            if server_started:
                (folder / 'cluster' / 'postmaster.pid').write_text('123')
            raise KeyboardInterrupt()
        return b''
    monkeypatch.setattr(m, 'run', fake_run)
    monkeypatch.setattr(m, 'run_pg_ctl', fake_run)
    monkeypatch.setattr(m, 'private_file', lambda path, contents: path.write_text(contents))
    monkeypatch.setattr(m, 'free_port', lambda: 23456)
    monkeypatch.setattr(m, 'port_closed', lambda port: True)
    assert m.execute(SimpleNamespace(pg_bin=tmp_path), folder, tmp_path / 'source', tmp_path, {}) == 1
    result = json.loads((folder / 'result.json').read_text())
    assert result['status'] == 'failed'
    assert result['failure'] == 'interrupted'
    assert result['cleanup_succeeded'] is True
    assert any(args[-1] == 'stop' for args in calls) is server_started
    assert result['stop_state'] == ('stopped' if server_started else 'already_stopped')
    assert not (folder / '.init-password').exists()


def test_pg_ctl_uses_no_pipes_and_waits_for_own_process(monkeypatch, tmp_path):
    import subprocess
    m = module()
    observed = {}
    class Process:
        def wait(self, timeout):
            observed['timeout'] = timeout
            return 0
    def start(args, **kwargs):
        observed.update(kwargs)
        return Process()
    monkeypatch.setattr(m.subprocess, 'Popen', start)
    m.run_pg_ctl([tmp_path / 'pg_ctl.exe', 'start'], env={})
    assert observed['stdin'] == subprocess.DEVNULL
    assert observed['stdout'] == subprocess.DEVNULL
    assert observed['stderr'] == subprocess.DEVNULL
    assert observed['timeout'] == 45


def test_pg_ctl_timeout_kills_only_its_handle(monkeypatch):
    import subprocess
    m = module()
    events = []
    class Process:
        def wait(self, timeout):
            events.append(('wait', timeout))
            if len(events) == 1:
                raise subprocess.TimeoutExpired('pg_ctl', timeout)
            return 1
        def kill(self):
            events.append(('kill',))
    monkeypatch.setattr(m.subprocess, 'Popen', lambda *args, **kwargs: Process())
    with pytest.raises(m.DrillError, match='pg_ctl_timeout'):
        m.run_pg_ctl(['pg_ctl', 'start'], env={})
    assert events == [('wait', 45), ('kill',), ('wait', 10)]


def test_app_validation_uses_finite_asgi_child_without_live_server(monkeypatch, tmp_path):
    import json
    m = module()
    programs = []
    def fake_run(args, **kwargs):
        programs.append(args)
        if args[-1] == 'check':
            return b''
        return b'{"source_verified":true,"health_http_status":200}'
    monkeypatch.setattr(m, 'run', fake_run)
    monkeypatch.setattr(m.subprocess, 'Popen', lambda *a, **kw: pytest.fail('live server started'))
    m.app_validation(tmp_path / 'python', tmp_path, {}, tmp_path, 'legacy')
    result = json.loads((tmp_path / 'legacy-application.json').read_text())
    assert result['health_transport'] == 'in_process_ASGI_TestClient'
    assert result['health_http_status'] == 200
    assert any('TestClient' in str(args) and 'with TestClient' in str(args) for args in programs)
