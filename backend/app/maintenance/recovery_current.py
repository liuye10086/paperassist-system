"""Current-head recovery; shares legacy primitives, never upgrades or runs workers."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import secrets
import shutil
import sys
import time
from uuid import uuid4

from app.maintenance import backup_manifest as manifest
from app.maintenance import recovery_drill as drill


def recovery_environment():
    # Keep only OS process necessities. No inherited provider, proxy, queue or .env configuration.
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {'SYSTEMROOT', 'WINDIR', 'PATH', 'TEMP', 'TMP', 'COMSPEC', 'PATHEXT', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA'}}
    env.update(PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', PAPERASSIST_ENV='test',
               PAPERASSIST_PLOT_WORKER_ENABLED='0', PAPERASSIST_WRITING_LIVE_ENABLED='0', PAPERASSIST_NCBI_ENABLED='0',
               PAPERASSIST_AUTH_TRUSTED_ORIGINS='http://testserver')
    for name in ('OPENAI_API_KEY', 'OPENAI_API_KEY_FILE', 'PAPERASSIST_NCBI_CONFIG_FILE', 'PAPERASSIST_NCBI_EMAIL',
                 'PAPERASSIST_NCBI_API_KEY', 'PAPERASSIST_PLOT_POLICY_FILE', 'PAPERASSIST_EXPLANATION_POLICY_FILE',
                 'PAPERASSIST_ANALYSIS_RECOMMENDATION_POLICY_FILE', 'PAPERASSIST_DATABASE_URL', 'PAPERASSIST_MIGRATION_DATABASE_URL'):
        env[name] = ''
    return env


@contextmanager
def owned_cluster(folder, pg, env):
    import psycopg
    from psycopg import sql
    from sqlalchemy.engine import URL
    cluster = folder / 'cluster'
    port = drill.free_port()
    drill.require(port != 5432 and drill.port_closed(port), 'unsafe_port')
    roles = {key: ('pa_' + key + '_' + secrets.token_hex(6), secrets.token_urlsafe(32)) for key in ('admin', 'owner', 'runtime')}
    password_file = folder / '.init-password'
    attempted = False
    def connect(role, database='paperassist_system_test'):
        return psycopg.connect(host='127.0.0.1', port=port, dbname=database, user=roles[role][0],
                               password=roles[role][1], autocommit=True, connect_timeout=5)
    def identity(connection, database):
        db, actual_port = connection.execute('SELECT current_database(), inet_server_port()').fetchone()
        drill.require(db == database, 'wrong_database')
        drill.validate_identity('paperassist_system_test', actual_port, connection.execute('SHOW data_directory').fetchone()[0],
                                expected_port=port, expected_directory=cluster)
        drill.require(connection.execute('SHOW listen_addresses').fetchone()[0] == '127.0.0.1', 'wrong_listener')
    def url(role):
        return URL.create('postgresql+psycopg', username=roles[role][0], password=roles[role][1], host='127.0.0.1',
                          port=port, database='paperassist_system_test').render_as_string(hide_password=False)
    try:
        drill.private_file(password_file, roles['admin'][1] + '\n')
        drill.run([pg / 'initdb.exe', '-D', cluster, '-U', roles['admin'][0], '--auth-host=scram-sha-256',
                   '--auth-local=scram-sha-256', '--encoding=UTF8', '--pwfile', password_file], env=env)
        password_file.unlink()
        with (cluster / 'postgresql.conf').open('a', encoding='utf-8') as stream:
            stream.write("\nlog_statement='none'\nlog_min_error_statement='panic'\nlog_min_messages='panic'\n")
        attempted = True
        drill.run_pg_ctl([pg / 'pg_ctl.exe', '-D', cluster, '-l', folder / 'postgres.log', '-w', '-t', '30',
                          '-o', f'-h 127.0.0.1 -p {port}', 'start'], env=env)
        with connect('admin', 'postgres') as connection:
            identity(connection, 'postgres')
            for key in ('owner', 'runtime'):
                connection.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}').format(sql.Identifier(roles[key][0]), sql.Literal(roles[key][1])))
            connection.execute(sql.SQL('CREATE DATABASE paperassist_system_test OWNER {}').format(sql.Identifier(roles['owner'][0])))
            connection.execute('REVOKE ALL ON DATABASE paperassist_system_test FROM PUBLIC')
            connection.execute(sql.SQL('GRANT CONNECT ON DATABASE paperassist_system_test TO {}').format(sql.Identifier(roles['runtime'][0])))
        with connect('admin') as connection:
            identity(connection, 'paperassist_system_test')
            drill.require(connection.execute("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'").fetchone()[0] == 0, 'public_not_empty')
            connection.execute('DROP SCHEMA public RESTRICT')
        drill.private_file(folder / '.cluster-access.json', json.dumps(dict(port=port, roles=roles)))
        yield dict(port=port, connect=connect, url=url, owner=roles['owner'], cluster=cluster)
    finally:
        password_file.unlink(missing_ok=True)
        stopped = True
        try:
            if attempted and ((cluster / 'postmaster.pid').exists() or not drill.port_closed(port)):
                drill.run_pg_ctl([pg / 'pg_ctl.exe', '-D', cluster, '-m', 'fast', '-w', '-t', '30', 'stop'], env=env)
        except Exception:
            stopped = False
        closed = drill.port_closed(port)
        pid_absent = not (cluster / 'postmaster.pid').exists()
        drill.write_json(folder / 'cluster-stop.json', dict(stopped=stopped, port_closed=closed, pid_absent=pid_absent, retained=True, port=port))
        drill.require(stopped and closed and pid_absent, 'owned_cluster_stop_failed')


GRANT = '''from sqlalchemy import create_engine
from app.db.database import get_migration_database_config,get_database_config,grant_runtime_access
m,r=get_migration_database_config(),get_database_config()
engine=create_engine(m.url)
with engine.begin() as connection:grant_runtime_access(connection,m,r)
engine.dispose()
'''


def execute(source, output, pg_bin, credentials_file):
    from psycopg import sql
    source, pg = Path(source).resolve(), Path(pg_bin)
    backup = manifest.validate_backup(source)
    for module in (manifest, drill, sys.modules[__name__]):
        drill.require(drill.sha(Path(module.__file__)) == drill.sha(source / 'code' / 'backend' / 'app' / 'maintenance' / Path(module.__file__).name), 'orchestrator_code_differs_from_sealed_source')
    env = recovery_environment()
    manifest.validate_archive(drill.run([pg / 'pg_restore.exe', '--list', source / 'database.dump'], env=env).decode(), backup['source_schema'])
    folder = drill.new_run_directory(Path(output))
    started = time.monotonic()
    target = 'pa_test_' + uuid4().hex
    status = dict(status='failed', source_schema=backup['source_schema'], target_schema=target,
                  consistency_id=backup['consistency_id'], recovery_point=backup['snapshot_at'],
                  worker_starts=0, outbox_replays=0, verification='unknown')
    stage = 'initialize'
    def mark(name):
        nonlocal stage
        stage = name
        drill.write_json(folder / (name + '-started.json'), dict(stage=name, at=manifest.utc(), elapsed_seconds=round(time.monotonic()-started, 3)))
    try:
        with owned_cluster(folder, pg, env) as cluster:
            mark('restore')
            drill.run([pg / 'pg_restore.exe', '-h', '127.0.0.1', '-p', cluster['port'], '-U', cluster['owner'][0],
                       '-d', 'paperassist_system_test', '--no-owner', '--no-acl', '--single-transaction', '--exit-on-error',
                       '--no-password', source / 'database.dump'], env={**env, 'PGPASSWORD': cluster['owner'][1]})
            mark('database_verification')
            before = manifest.read_json(source / 'before-fingerprints.json')
            sequences = manifest.read_json(source / 'sequences.json')
            with cluster['connect']('owner') as connection:
                connection.execute(sql.SQL('ALTER SCHEMA {} RENAME TO {}').format(sql.Identifier(backup['source_schema']), sql.Identifier(target)))
                drill.require(manifest.database_fingerprints(connection, target) == before, 'restored_database_mismatch')
                drill.require(drill.sequence_state(connection, target) == sequences, 'restored_sequence_mismatch')
            drill.write_json(folder / 'before-http-verified.json', dict(tables=before, sequences=sequences, source_schema=backup['source_schema'], target_schema=target))
            shutil.copytree(source / 'assets', folder / 'assets')
            manifest.validate_files(folder / 'assets', manifest.read_json(source / 'asset-manifest.json'))
            sealed = source / 'code' / 'backend'
            app_env = {**env, 'PAPERASSIST_DB_SCHEMA': target, 'PAPERASSIST_TEST_DATABASE_URL': cluster['url']('runtime'),
                       'PAPERASSIST_TEST_MIGRATION_DATABASE_URL': cluster['url']('owner'), 'PAPERASSIST_DATA_DIR': str(folder / 'assets')}
            mark('permission_and_audit')
            drill.run([sys.executable, '-c', GRANT], env=app_env, cwd=sealed)
            drill.run([sys.executable, '-m', 'app.db.database', 'check'], env=app_env, cwd=sealed)
            audit = json.loads(drill.run([sys.executable, '-m', 'app.maintenance.database_audit'], env=app_env, cwd=sealed))
            drill.require(audit['ok'], 'restored_audit_failed')
            drill.write_json(folder / 'database-audit.json', audit)
            with cluster['connect']('owner') as connection:
                operational_before = manifest.operational_rows(connection, target)
            mark('http')
            drill.run([sys.executable, '-m', 'app.maintenance.recovery_http', '--expected', source / 'expected-api.json',
                       '--credentials', Path(credentials_file).resolve(), '--output', folder / 'http.json',
                       '--downloads', folder / 'downloads'], env=app_env, cwd=sealed)
            http = manifest.read_json(folder / 'http.json')
            with cluster['connect']('owner') as connection:
                after = manifest.database_fingerprints(connection, target)
                changed = manifest.business_unchanged(before, after)
                seq_after = drill.sequence_state(connection, target)
                changed_sequences = sorted(name for name in sequences if sequences[name] != seq_after.get(name))
                drill.require(sequences == seq_after, 'business_sequence_changed')
                operational_delta = manifest.verify_operational_delta(operational_before, manifest.operational_rows(connection, target), http, time.time())
            manifest.validate_files(folder / 'assets', manifest.read_json(source / 'asset-manifest.json'))
            manifest.validate_backup(source)
            drill.write_json(folder / 'after-http-verified.json', dict(tables=after, changed_operational_tables=changed,
                             operational_delta=operational_delta, changed_sequences=changed_sequences,
                             assets_unchanged=True, unknown_and_queue_unchanged=True))
            status.update(verification='passed', database_port=cluster['port'], actual_http=http)
        status['status'] = 'complete'
    except BaseException as exc:
        status.update(failure=str(exc) if isinstance(exc, drill.DrillError) else 'recovery_failed', stage=stage,
                      verification='passed' if status['verification'] == 'passed' else
                      'failed' if stage in {'database_verification', 'permission_and_audit', 'http'} else 'unknown')
    status.update(finished_at=manifest.utc(), duration_seconds=round(time.monotonic()-started, 3))
    drill.write_json(folder / 'result.json', status)
    return status
