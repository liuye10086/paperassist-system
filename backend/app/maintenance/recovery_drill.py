"""Opt-in recovery in a newly initialized, loopback-only PostgreSQL cluster.

No existing database URL is accepted. Child output is captured, never logged:
PostgreSQL errors can contain restored business values or credentials.
"""

from app.core.paths import BACKEND_ROOT

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
from uuid import uuid4
import zipfile


class DrillError(Exception):
    pass


def require(value, code):
    if not value:
        raise DrillError(code)


def new_run_directory(path):
    require(not path.exists(), 'destination_exists')
    path.mkdir(parents=True, exist_ok=False)
    return path.resolve()


def write_json(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def clean_environment(source):
    env = {k: v for k, v in source.items() if not k.upper().startswith(('PG', 'PAPERASSIST_', 'PYTHON'))
           and k.upper() != 'OPENAI_API_KEY'}
    env.update(PYTHONNOUSERSITE='1', OPENAI_API_KEY='', PAPERASSIST_PLOT_WORKER_ENABLED='0')
    return env


def safe_extract(archive, destination):
    destination = destination.resolve()
    with zipfile.ZipFile(archive) as source:
        for item in source.infolist():
            target = (destination / item.filename).resolve()
            require(target.is_relative_to(destination) and ':' not in item.filename
                    and '\\' not in item.filename and not (item.external_attr >> 16 & 0o170000) == 0o120000,
                    'unsafe_archive_member')
        source.extractall(destination)


def validate_identity(database, port, directory, *, expected_port, expected_directory):
    require(database == 'paperassist_system_test', 'wrong_database')
    require(port == expected_port and port != 5432, 'wrong_port')
    require(Path(directory).resolve() == Path(expected_directory).resolve(), 'wrong_cluster')


def archive_sequences(data):
    result = {}
    # Parse only canonical pg_dump sequence statements, never rewrite SQL.
    for line in data.decode('utf-8').splitlines():
        if line.startswith('SELECT pg_catalog.setval('):
            match = re.fullmatch(r"SELECT pg_catalog.setval\('public\.([a-z_][a-z_0-9]*)', (-?\d+), (true|false)\);", line)
            require(match, 'unsupported_sequence_statement')
            name, value, called = match.groups()
            require(name not in result, 'duplicate_sequence')
            result[name] = [int(value), called == 'true']
    return result


def rows_fingerprint(rows):
    values = sorted(json.dumps(dict(row), ensure_ascii=False, sort_keys=True,
                              separators=(',', ':'), allow_nan=False) for row in rows)
    return hashlib.sha256('\n'.join(values).encode('utf-8')).hexdigest()


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def port_closed(port):
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex(('127.0.0.1', port)) != 0


def run(args, *, env, cwd=None, expected=0):
    result = subprocess.run([str(a) for a in args], env=env, cwd=cwd, capture_output=True,
                            timeout=120, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    require(result.returncode == expected, 'child_command_failed')
    return result.stdout


def run_pg_ctl(args, *, env):
    # Windows postgres can inherit pg_ctl's handles. PIPE/communicate then waits
    # for the long-lived server to close them, even after pg_ctl has exited.
    child = subprocess.Popen([str(a) for a in args], env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        code = child.wait(timeout=45)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=10)
        raise DrillError('pg_ctl_timeout') from None
    except BaseException:
        child.kill()
        child.wait(timeout=10)
        raise
    require(code == 0, 'pg_ctl_failed')


def private_file(path, contents):
    # On Windows remove inherited ACLs before writing any secret.
    path.touch(exist_ok=False)
    if os.name == 'nt':
        who = subprocess.run(['whoami'], capture_output=True, check=True).stdout.decode().strip()
        result = subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r', who + ':F'], capture_output=True)
        require(result.returncode == 0, 'private_file_acl_failed')
    else:
        path.chmod(0o600)
    path.write_text(contents, encoding='utf-8')


def verify_assets(root, manifest):
    actual = []
    for entry in manifest:
        path = (root / entry['path']).resolve()
        require(path.is_relative_to(root.resolve()) and path.is_file(), 'unsafe_or_missing_asset')
        require(path.stat().st_size == entry['bytes'] and sha(path) == entry['sha256'], 'asset_mismatch')
        actual.append(entry)
    require({p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
            == {e['path'] for e in manifest}, 'unexpected_assets')
    return actual


def fingerprints(connection, schema, before, *, upgraded=False):
    from psycopg import sql
    from psycopg.rows import dict_row
    output = {}
    with connection.cursor(row_factory=dict_row) as cursor:
        for table, expected in before.items():
            if upgraded and table == 'alembic_version':
                continue
            names = expected['columns']
            cursor.execute(sql.SQL('SELECT {} FROM {}.{}').format(
                sql.SQL(',').join(map(sql.Identifier, names)), sql.Identifier(schema), sql.Identifier(table)))
            rows = cursor.fetchall()
            value = dict(columns=names, rows=len(rows), sha256=rows_fingerprint(rows))
            require(value == expected, 'original_value_mismatch')
            output[table] = value
    return output


def sequence_state(connection, schema):
    from psycopg import sql
    names = connection.execute("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relkind='S'", (schema,)).fetchall()
    return {name: list(connection.execute(sql.SQL('SELECT last_value,is_called FROM {}.{}').format(
        sql.Identifier(schema), sql.Identifier(name))).fetchone()) for (name,) in names}


LEGACY_READ_PROGRAM = r'''
import os, json, hashlib
from pathlib import Path
import app
assert Path(app.__file__).resolve().parent == Path.cwd() / 'app'
from app.storage import ProjectStore
from app.report_store import ReportStore
store = ProjectStore(Path(os.environ['PAPERASSIST_DATA_DIR']))
projects = store.projects()
assets_read = 0
for project in projects:
    assert store.project(project['id'])['id'] == project['id']
    for file in store.files(project['id']):
        record = store.file(project['id'], file['id'])
        store.original(record)
        assets_read += 1
        if record['preview_json'] is not None:
            json.loads(record['preview_json'])
        store.analysis_setup(project['id'], file['id'])
counts = {}
with store.connection() as db:
    for table in ('files','analysis_setups','analysis_runs','figures','figure_jobs','explanations','explanation_jobs','reports'):
        rows = list(db.execute('SELECT * FROM ' + table))
        counts[table] = len(rows)
        for row in rows:
            for key, value in dict(row).items():
                if key.endswith('_json') and value is not None:
                    json.loads(value)
            if table == 'figures':
                store.figure_png(json.loads(row['figure_json']))
                assets_read += 1
            elif table == 'reports':
                ReportStore(store).content(json.loads(row['report_json']))
                assets_read += 1
print(json.dumps({'source_verified': True, 'projects': len(projects), 'resource_counts': counts,
                  'assets_read_and_hash_verified': assets_read,
                  'business_read_transport': 'local_ProjectStore_read_only'}))
'''


CURRENT_READ_PROGRAM = LEGACY_READ_PROGRAM.replace(
    'from app.storage import ProjectStore', 'from app.adapters.storage import ProjectStore'
).replace('from app.report_store import ReportStore', 'from app.adapters.report_store import ReportStore')


def app_validation(python, backend, env, evidence, label):
    legacy = label == 'legacy'
    database_module = 'app.database' if legacy else 'app.db.database'
    program = LEGACY_READ_PROGRAM if legacy else CURRENT_READ_PROGRAM
    run([python, '-m', database_module, 'check'], env=env, cwd=backend)
    result = json.loads(run([python, '-c', program], env=env, cwd=backend))
    health_program = r'''
import json
from pathlib import Path
import app
assert Path(app.__file__).resolve().parent == Path.cwd() / 'app'
from fastapi.testclient import TestClient
from app.main import app as application
with TestClient(application) as client:
    response = client.get('/api/v1/health')
    assert response.status_code == 200
print(json.dumps({'health_http_status': response.status_code}))
'''
    health = json.loads(run([python, '-c', health_program], env=env, cwd=backend))
    require(health['health_http_status'] == 200, 'health_failed')
    result.update(health_http_status=200, health_transport='in_process_ASGI_TestClient',
                  lifespan_completed=True, live_tcp_server_started=False)
    write_json(evidence / (label + '-application.json'), result)


def execute(args, folder, source, backend, env):
    import psycopg
    from psycopg import sql
    from sqlalchemy.engine import URL
    pg = Path(args.pg_bin)
    cluster = folder / 'cluster'
    port = free_port()
    require(port != 5432, 'unsafe_port')
    schema = 'pa_test_' + uuid4().hex
    roles = {name: ('pa_' + name + '_' + secrets.token_hex(6), secrets.token_urlsafe(32))
             for name in ('admin', 'owner', 'runtime')}
    password_file = folder / '.init-password'
    stage = 'initdb'
    attempted_start = False
    failure = None
    completed = False
    def mark(name, **values):
        nonlocal stage
        stage = name
        write_json(folder / (name + '.json'), {'stage': name, **values})
    def connect(role, database='paperassist_system_test'):
        name, password = roles[role]
        return psycopg.connect(host='127.0.0.1', port=port, dbname=database,
                               user=name, password=password, autocommit=True, connect_timeout=5)
    def identity(connection, database='paperassist_system_test'):
        actual_db, actual_port = connection.execute('SELECT current_database(), inet_server_port()').fetchone()
        directory = connection.execute('SHOW data_directory').fetchone()[0]
        require(actual_db == database, 'wrong_database')
        validate_identity('paperassist_system_test', actual_port, directory,
                          expected_port=port, expected_directory=cluster)
        require(connection.execute('SHOW listen_addresses').fetchone()[0] == '127.0.0.1', 'wrong_listener')
    try:
        private_file(password_file, roles['admin'][1] + '\n')
        mark('initdb', port=port, schema=schema)
        run([pg / 'initdb.exe', '-D', cluster, '-U', roles['admin'][0], '--auth-host=scram-sha-256',
             '--auth-local=scram-sha-256', '--encoding=UTF8', '--pwfile', password_file], env=env)
        password_file.unlink()
        # Avoid database statements/credentials leaking into server logs.
        with (cluster / 'postgresql.conf').open('a', encoding='utf-8') as config:
            config.write("\nlog_statement='none'\nlog_min_error_statement='panic'\nlog_min_messages='panic'\n")
        mark('start')
        attempted_start = True
        run_pg_ctl([pg / 'pg_ctl.exe', '-D', cluster, '-l', folder / 'postgres.log', '-w', '-t', '30',
             '-o', f'-h 127.0.0.1 -p {port}', 'start'], env=env)
        with connect('admin', 'postgres') as admin:
            identity(admin, 'postgres')
            mark('identity_verified', port=port, directory=str(cluster), loopback=True)
            for key in ('owner', 'runtime'):
                name, password = roles[key]
                admin.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}').format(sql.Identifier(name), sql.Literal(password)))
            admin.execute(sql.SQL('CREATE DATABASE paperassist_system_test OWNER {}').format(sql.Identifier(roles['owner'][0])))
            admin.execute('REVOKE ALL ON DATABASE paperassist_system_test FROM PUBLIC')
            admin.execute(sql.SQL('GRANT CONNECT ON DATABASE paperassist_system_test TO {}').format(sql.Identifier(roles['runtime'][0])))
        with connect('admin') as admin:
            identity(admin)
            require(admin.execute("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'").fetchone()[0] == 0, 'public_not_empty')
            admin.execute('DROP SCHEMA public RESTRICT')
        mark('restore')
        restore_env = {**env, 'PGPASSWORD': roles['owner'][1]}
        run([pg / 'pg_restore.exe', '-h', '127.0.0.1', '-p', port, '-U', roles['owner'][0],
             '-d', 'paperassist_system_test', '--no-owner', '--no-acl', '--single-transaction',
             '--exit-on-error', '--no-password', source / 'database.dump'], env=restore_env)
        before = json.loads((source / 'before-fingerprints.json').read_text(encoding='utf-8'))
        expected_seq = archive_sequences(run([pg / 'pg_restore.exe', '--data-only', '--no-owner',
                                  '--no-acl', '-f', '-', source / 'database.dump'], env=env))
        with connect('owner') as owner:
            owner.execute(sql.SQL('ALTER SCHEMA public RENAME TO {}').format(sql.Identifier(schema)))
            restored = fingerprints(owner, schema, before)
            sequences = sequence_state(owner, schema)
            require(sequences == expected_seq, 'sequence_mismatch')
            for table in before:
                privilege = sql.SQL('SELECT') if table == 'alembic_version' else sql.SQL('SELECT,INSERT,UPDATE,DELETE')
                owner.execute(sql.SQL('GRANT {} ON {}.{} TO {}').format(privilege, sql.Identifier(schema), sql.Identifier(table), sql.Identifier(roles['runtime'][0])))
            owner.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(sql.Identifier(schema), sql.Identifier(roles['runtime'][0])))
            owner.execute(sql.SQL('GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA {} TO {}').format(sql.Identifier(schema), sql.Identifier(roles['runtime'][0])))
        mark('restored_values_verified', tables=restored, sequences=sequences)
        manifest = json.loads((source / 'asset-manifest.json').read_text(encoding='utf-8'))
        shutil.copytree(source / 'assets', folder / 'assets')
        verify_assets(folder / 'assets', manifest)
        archive = folder / 'legacy.zip'
        run(['git', 'archive', '--format=zip', '--output=' + str(archive), args.legacy_ref, 'backend'], env=env, cwd=backend.parent)
        safe_extract(archive, folder / 'legacy')
        def url(role):
            return URL.create('postgresql+psycopg', username=roles[role][0], password=roles[role][1], host='127.0.0.1', port=port,
                              database='paperassist_system_test').render_as_string(hide_password=False)
        app_env = {**env, 'PAPERASSIST_ENV': 'test', 'PAPERASSIST_TEST_DATABASE_URL': url('runtime'),
                   'PAPERASSIST_TEST_MIGRATION_DATABASE_URL': url('owner'), 'PAPERASSIST_DB_SCHEMA': schema,
                   'PAPERASSIST_DATA_DIR': str(folder / 'assets'), 'PAPERASSIST_DATABASE_URL': '',
                   'PAPERASSIST_MIGRATION_DATABASE_URL': ''}
        python = Path(sys.executable)
        mark('legacy_validation')
        app_validation(python, folder / 'legacy' / 'backend', app_env, folder, 'legacy')
        mark('current_version_rejection')
        rejection = """from app.db.database import database_connection, SchemaVersionError, ensure_schema_current
try:
    with database_connection() as db:
        ensure_schema_current(db)
except SchemaVersionError:
    raise SystemExit(42)
raise SystemExit(0)
"""
        run([python, '-c', rejection], env=app_env, cwd=backend, expected=42)
        mark('upgrade_0005')
        run([python, '-m', 'app.db.database', 'upgrade'], env=app_env, cwd=backend)
        app_validation(python, backend, app_env, folder, 'current')
        audit = json.loads(run([python, '-m', 'app.maintenance.database_audit'], env=app_env, cwd=backend))
        require(audit['ok'], 'audit_failed')
        write_json(folder / 'database-audit.json', audit)
        with connect('owner') as owner:
            preserved = fingerprints(owner, schema, before, upgraded=True)
            require(sequence_state(owner, schema) == expected_seq, 'sequence_changed')
            revision = owner.execute(sql.SQL('SELECT version_num FROM {}.alembic_version').format(sql.Identifier(schema))).fetchone()[0]
            require(revision == '0005_ownership_indexes', 'unexpected_final_revision')
        verify_assets(folder / 'assets', manifest)
        verify_assets(source / 'assets', manifest)
        mark('final_values_verified', tables=preserved, assets=len(manifest), sequences=expected_seq)
        completed = True
    except BaseException as exc:
        failure = (exc.args[0] if isinstance(exc, DrillError) else
                   'interrupted' if isinstance(exc, (KeyboardInterrupt, SystemExit)) else 'unexpected_failure')
    finally:
        cleanup = True
        stop_state = 'not_started'
        try:
            password_file.unlink(missing_ok=True)
        except OSError:
            cleanup = False
        if attempted_start:
            if not (cluster / 'postmaster.pid').exists() and port_closed(port):
                stop_state = 'already_stopped'
            else:
                try:
                    run_pg_ctl([pg / 'pg_ctl.exe', '-D', cluster, '-m', 'fast', '-w', '-t', '30', 'stop'], env=env)
                    stop_state = 'stopped'
                except Exception:
                    cleanup = False
                    stop_state = 'stop_failed'
        closed = port_closed(port)
        cleanup = cleanup and closed
        write_json(folder / 'result.json', {'status': 'complete' if completed and failure is None and cleanup else 'failed',
                  'stage': stage, 'failure': failure, 'cleanup_succeeded': cleanup, 'database_port_closed': closed,
                  'stop_state': stop_state,
                  'retained_private_cluster': str(cluster), 'existing_database_connected': False})
    return 0 if completed and failure is None and cleanup else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-backup', type=Path, required=True)
    parser.add_argument('--legacy-ref', required=True)
    parser.add_argument('--pg-bin', default='C:/Program Files/PostgreSQL/18/bin')
    parser.add_argument('--execute', action='store_true', help='Initialize and restore only a new isolated cluster')
    args = parser.parse_args(argv)
    backend = BACKEND_ROOT
    folder = None
    try:
        source = args.source_backup.resolve(strict=True)
        source_hashes = {str(p.relative_to(source)): sha(p) for p in source.rglob('*') if p.is_file()}
        env = clean_environment(os.environ)
        require(re.fullmatch('[0-9a-f]{40}', args.legacy_ref), 'full_commit_required')
        actual = run(['git', 'rev-parse', args.legacy_ref + '^{commit}'], env=env, cwd=backend.parent).decode().strip()
        require(actual == args.legacy_ref, 'legacy_ref_mismatch')
        expected = json.loads((source / 'backup-verification.json').read_text(encoding='utf-8'))['backup_sha256']
        require(sha(source / 'database.dump') == expected, 'archive_hash_mismatch')
        manifest = json.loads((source / 'asset-manifest.json').read_text(encoding='utf-8'))
        verify_assets(source / 'assets', manifest)
        version = run([Path(args.pg_bin) / 'pg_restore.exe', '--version'], env=env).decode()
        require(re.search(r'\b18\.', version), 'postgres_18_required')
        listing = run([Path(args.pg_bin) / 'pg_restore.exe', '--list', source / 'database.dump'], env=env).decode()
        require(re.search(r'; \d+ \d+ SCHEMA - public ', listing), 'archive_public_schema_missing')
        folder = new_run_directory(backend / 'backups' / ('recovery-drill-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')))
        write_json(folder / 'prepare.json', {'executed': args.execute, 'archive_sha256': expected,
                   'assets': len(manifest), 'legacy_ref': actual, 'existing_database_connected': False})
        code = execute(args, folder, source, backend, env) if args.execute else 0
        current_hashes = {str(p.relative_to(source)): sha(p) for p in source.rglob('*') if p.is_file()}
        unchanged = current_hashes == source_hashes
        write_json(folder / 'source-integrity.json', {'unchanged': unchanged, 'files': len(source_hashes),
                   'archive_sha256': expected, 'assets': len(manifest)})
        require(unchanged, 'source_backup_changed')
        print(json.dumps({'status': ('complete' if args.execute else 'prepared') if code == 0 else 'failed',
                          'evidence': str(folder)}))
        return code
    except Exception as exc:
        print(json.dumps({'status': 'failed', 'stage': 'prepare_or_finalize',
                          'code': exc.args[0] if isinstance(exc, DrillError) else 'unexpected_failure',
                          'evidence': str(folder) if folder else None}))
        return 1
