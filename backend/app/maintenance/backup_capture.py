"""Capture one explicitly quiescent synthetic schema using one exported snapshot."""
import importlib.metadata
import os
from pathlib import Path
import shutil
import time
from uuid import uuid4

from app.db.database import SCHEMA_HEAD
from app.maintenance import backup_manifest as manifest
from app.maintenance import recovery_drill as drill


def code_files(backend):
    paths = [p for name in ('app', 'alembic') for p in (backend / name).rglob('*') if p.is_file()
             and not any(part.startswith('.env') or part in {'__pycache__', 'data', 'backups', '.venv', 'keys', 'private'} for part in p.relative_to(backend).parts)
             and p.suffix not in {'.pyc', '.key', '.pem'}]
    paths += [backend / 'alembic.ini', *backend.glob('requirements*.txt')]
    return sorted(paths)


def capture(*, output, schema, assets, **kwargs):
    output = drill.new_run_directory(Path(output))
    started = time.monotonic()
    identity = str(uuid4())
    drill.write_json(output / 'started.json', dict(consistency_id=identity, source_schema=schema,
                     started_at=manifest.utc(), synthetic_only=True, status='started'))
    try:
        return _capture(output=output, schema=schema, assets=Path(assets), identity=identity, started=started, **kwargs)
    except BaseException as exc:
        code = str(exc) if isinstance(exc, drill.DrillError) else 'capture_failed'
        drill.write_json(output / 'failure.json', dict(status='failed', failure=code, finished_at=manifest.utc(),
                         duration_seconds=round(time.monotonic() - started, 3), source_preserved=True))
        raise drill.DrillError(code) from None


def _capture(*, output, schema, assets, identity, started, backend, connection_config, expected_api,
             pg_bin, env, write_window, interrupt_after_dump=False):
    import psycopg
    from psycopg import sql
    backend, pg_bin = Path(backend), Path(pg_bin)
    drill.require(manifest.SCHEMA.fullmatch(schema) and write_window['writers_stopped'] is True, 'source_not_quiescent')
    drill.require(connection_config['dbname'] == 'paperassist_system_test'
                  and connection_config['host'] in ('localhost', '127.0.0.1', '::1'), 'unsafe_capture_database')
    drill.require(manifest.read_json(Path(expected_api))['source_schema'] == schema, 'expected_api_wrong_source')
    expected_sha = drill.sha(Path(expected_api))
    paths = code_files(backend)
    original_code = {p.relative_to(backend).as_posix(): drill.sha(p) for p in paths}
    asset_entries = manifest.file_manifest(assets)
    with psycopg.connect(**connection_config, autocommit=True) as connection:
        connection.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
        try:
            drill.require(connection.execute('SELECT current_database()').fetchone()[0] == 'paperassist_system_test', 'wrong_database')
            revision = connection.execute(sql.SQL('SELECT version_num FROM {}.alembic_version').format(sql.Identifier(schema))).fetchall()
            drill.require(revision == [(SCHEMA_HEAD,)], 'unexpected_source_revision')
            snapshot = connection.execute('SELECT pg_export_snapshot()').fetchone()[0]
            before = manifest.database_fingerprints(connection, schema)
            sequences = drill.sequence_state(connection, schema)
            snapshot_at = manifest.utc()
            drill.write_json(output / 'before-fingerprints.json', before)
            drill.write_json(output / 'sequences.json', sequences)
            drill.run([pg_bin / 'pg_dump.exe', '-h', connection_config['host'], '-p', connection_config['port'],
                       '-U', connection_config['user'], '-d', 'paperassist_system_test', '-Fc', '--strict-names',
                       '--schema=' + schema, '--snapshot=' + snapshot, '--no-owner', '--no-acl', '--no-password',
                       '-f', output / 'database.dump'], env={**env, 'PGPASSWORD': connection_config['password']})
            if interrupt_after_dump:
                raise drill.DrillError('injected_backup_interruption')
            shutil.copytree(assets, output / 'assets')
            manifest.validate_files(output / 'assets', asset_entries)
            for path in paths:
                target = output / 'code' / 'backend' / path.relative_to(backend)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
            drill.require(original_code == {p.relative_to(backend).as_posix(): drill.sha(p) for p in code_files(backend)}, 'source_code_changed')
            drill.require(all(drill.sha(output / 'code' / 'backend' / name) == value for name, value in original_code.items()), 'code_copy_mismatch')
            manifest.validate_files(assets, asset_entries)
            drill.require(drill.sequence_state(connection, schema) == sequences, 'source_sequence_changed')
        finally:
            connection.execute('ROLLBACK')
        # A new snapshot proves the source did not change behind the exported snapshot.
        connection.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
        try:
            drill.require(manifest.database_fingerprints(connection, schema) == before, 'source_database_changed')
            drill.require(drill.sequence_state(connection, schema) == sequences, 'source_sequence_changed')
        finally:
            connection.execute('ROLLBACK')
    shutil.copyfile(expected_api, output / 'expected-api.json')
    drill.require(drill.sha(output / 'expected-api.json') == expected_sha == drill.sha(Path(expected_api)), 'expected_api_changed')
    drill.write_json(output / 'asset-manifest.json', asset_entries)
    drill.write_json(output / 'code-manifest.json', manifest.file_manifest(output / 'code'))
    files = ('database.dump', 'asset-manifest.json', 'code-manifest.json', 'before-fingerprints.json', 'sequences.json', 'expected-api.json')
    evidence = {name: dict(bytes=(output / name).stat().st_size, sha256=drill.sha(output / name)) for name in files}
    value = dict(format_version=1, consistency_id=identity, source_schema=schema, schema_revision=SCHEMA_HEAD,
                 started_at=manifest.read_json(output / 'started.json')['started_at'], snapshot_at=snapshot_at,
                 finished_at=manifest.utc(), duration_seconds=round(time.monotonic() - started, 3),
                 synthetic_only=True, retention='indefinite', write_window=write_window, evidence=evidence,
                 git_head=drill.run(['git', 'rev-parse', 'HEAD'], env=env, cwd=backend.parent).decode().strip(),
                 dirty=bool(drill.run(['git', 'status', '--porcelain', '--untracked-files=normal'], env=env, cwd=backend.parent)),
                 dependencies={name: importlib.metadata.version(name) for name in ('psycopg', 'sqlalchemy', 'fastapi', 'httpx', 'alembic', 'python-docx')},
                 postgres_version=drill.run([pg_bin / 'pg_dump.exe', '--version'], env=env).decode().strip(),
                 asset_set_sha256=manifest.digest(asset_entries), code_set_sha256=manifest.digest(manifest.read_json(output / 'code-manifest.json')))
    drill.write_json(output / 'manifest.pending.json', value)
    drill.write_json(output / 'manifest-receipt.json', dict(sha256=drill.sha(output / 'manifest.pending.json')))
    manifest.validate_backup(output, manifest_name='manifest.pending.json')
    os.replace(output / 'manifest.pending.json', output / 'manifest.json')
    return value
