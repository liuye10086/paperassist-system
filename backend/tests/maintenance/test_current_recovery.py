"""Fixture-only failure checks, distinct from a real independent restore."""
import json
from pathlib import Path
import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def test_recovery_environment_never_inherits_secrets_or_queue(monkeypatch, tmp_path):
    from app.maintenance.recovery_current import recovery_environment
    monkeypatch.setenv('OPENAI_API_KEY_FILE', '/secret')
    monkeypatch.setenv('HTTPS_PROXY', 'secret-proxy')
    monkeypatch.setenv('PAPERASSIST_BROKER_URL', 'secret-queue')
    value = recovery_environment()
    assert value['OPENAI_API_KEY_FILE'] == ''
    assert 'HTTPS_PROXY' not in value and 'PAPERASSIST_BROKER_URL' not in value
    assert value['PAPERASSIST_WRITING_LIVE_ENABLED'] == '0'


def test_cluster_start_failure_stops_only_new_cluster_and_preserves_artifacts(monkeypatch, tmp_path):
    from app.maintenance import recovery_current as m
    from app.maintenance import recovery_drill as d
    calls = []
    monkeypatch.setattr(d, 'free_port', lambda: 24567)
    monkeypatch.setattr(d, 'private_file', lambda path, content: path.write_text(content))
    def run(args, **kwargs):
        (tmp_path / 'cluster').mkdir()
        (tmp_path / 'cluster' / 'postgresql.conf').write_text('')
    monkeypatch.setattr(d, 'run', run)
    def ctl(args, **kwargs):
        calls.append(args)
        if args[-1] == 'start':
            (tmp_path / 'cluster' / 'postmaster.pid').write_text('123')
            raise d.DrillError('injected_start_failure')
        (tmp_path / 'cluster' / 'postmaster.pid').unlink()
    monkeypatch.setattr(d, 'run_pg_ctl', ctl)
    monkeypatch.setattr(d, 'port_closed', lambda port: True)
    with pytest.raises(d.DrillError, match='injected_start_failure'):
        with m.owned_cluster(tmp_path, tmp_path / 'pg', {}):
            pytest.fail('Unverified cluster cannot be yielded')
    assert calls[-1][-1] == 'stop' and str(tmp_path / 'cluster') in list(map(str, calls[-1]))
    assert (tmp_path / 'cluster').exists()
    assert json.loads((tmp_path / 'cluster-stop.json').read_text())['port_closed'] is True


def test_interrupted_capture_retains_started_partial_and_no_final_manifest(monkeypatch, tmp_path):
    from app.maintenance import backup_capture as m
    from app.maintenance.recovery_drill import DrillError
    source = tmp_path / 'assets'
    source.mkdir()
    (source / '.hidden').write_bytes(b'research receipt')
    output = tmp_path / 'attempt'
    import psycopg
    from types import SimpleNamespace
    schema = 'pa_test_' + 'a' * 32
    backend = tmp_path / 'backend'
    backend.mkdir()
    (backend / 'alembic.ini').write_text('fixture')
    expected = tmp_path / 'expected.json'
    expected.write_text(json.dumps(dict(source_schema=schema)))
    statements = []
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, query):
            statements.append(str(query))
            return SimpleNamespace(fetchone=lambda: ('paperassist_system_test',) if 'current_database' in str(query) else ('snapshot-id',),
                                   fetchall=lambda: [(m.SCHEMA_HEAD,)])
    monkeypatch.setattr(psycopg, 'connect', lambda **kwargs: Connection())
    monkeypatch.setattr(m.manifest, 'database_fingerprints', lambda *args: {})
    monkeypatch.setattr(m.drill, 'sequence_state', lambda *args: {})
    monkeypatch.setattr(m.drill, 'run', lambda *args, **kwargs: (output / 'database.dump').write_bytes(b'partial-attempt-dump'))
    with pytest.raises(DrillError, match='injected_backup_interruption'):
        m.capture(output=output, schema=schema, assets=source, backend=backend,
                  connection_config=dict(dbname='paperassist_system_test', host='127.0.0.1', port=5432, user='fixture', password='fixture'),
                  expected_api=expected, pg_bin=tmp_path, env={}, write_window=dict(writers_stopped=True), interrupt_after_dump=True)
    assert (output / 'started.json').exists() and (output / 'failure.json').exists()
    assert (output / 'database.dump').exists() and statements[-1] == 'ROLLBACK'
    assert not (output / 'manifest.json').exists()
    assert (source / '.hidden').read_bytes() == b'research receipt'


def test_operational_changes_are_bound_to_exact_http_receipts():
    from app.maintenance.backup_manifest import verify_operational_delta
    from app.maintenance.recovery_drill import DrillError
    before = dict(sessions=[], auth_login_attempts=[], operational_request_events=[])
    after = dict(sessions=[dict(token_hash='new-token', user_id='owner')], auth_login_attempts=[],
                 operational_request_events=[dict(request_id='request', method='GET', status=200)])
    http = dict(identities=[dict(id='owner')], requests=[dict(request_id='request', method='GET', status=200)])
    assert verify_operational_delta(before, after, http, 1000)['sessions']['added'] == 1
    after['operational_request_events'][0]['method'] = 'DELETE'
    with pytest.raises(DrillError, match='request_receipt_mismatch'):
        verify_operational_delta(before, after, http, 1000)
