"""Synthetic import rehearsal. Default prepares evidence; --execute uses a new test schema."""
from contextlib import contextmanager
from datetime import datetime, timezone
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from uuid import uuid4

BACKEND = Path(__file__).resolve().parents[1]
BACKUPS = BACKEND / 'backups'
sys.path.insert(0, str(BACKEND))

from scripts._import_drill_fixture import create_complex_source, file_hashes


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def validate_target(config):
    if (config.environment != 'test' or config.purpose != 'migration'
            or config.url.database != 'paperassist_system_test'
            or not re.fullmatch(r'pa_test_[0-9a-f]{32}', config.schema)
            or config.url.host not in {'localhost', '127.0.0.1', '::1'}):
        raise ValueError('Rehearsal requires an isolated test schema and local test migration account.')


def read_target(config):
    from app.db.database import migration_connection
    from app.maintenance.legacy_import import TABLE_COLUMNS, JOB_TABLES
    validate_target(config)
    with migration_connection(config=config) as db:
        if db.execute('SELECT current_database() AS name').fetchone()['name'] != 'paperassist_system_test':
            raise ValueError('Actual database is not the isolated test database.')
        return {table: tuple(dict(row) for row in db.execute(
            f'SELECT {",".join(columns)}' + (',seq' if table in JOB_TABLES else '')
            + f' FROM {table} ORDER BY {columns[0]}')) for table, columns in TABLE_COLUMNS.items()}


def sequence_state(config):
    from app.db.database import migration_connection
    validate_target(config)
    with migration_connection(config=config) as db:
        return [dict(row) for row in db.execute('''SELECT sequencename, start_value, increment_by, last_value
            FROM pg_sequences WHERE schemaname=%s ORDER BY sequencename''', (config.schema,))]


def interrupt_child(source, directory, barrier, config):
    """Kill only the child created by this call, holding its process handle throughout."""
    from app.db.database import get_database_config, validate_database_pair
    validate_target(config)
    runtime = get_database_config()
    validate_database_pair(config, runtime)
    environment = dict(os.environ)
    environment.update(PAPERASSIST_ENV='test', PAPERASSIST_DB_SCHEMA=config.schema,
                       PAPERASSIST_DATA_DIR=str(directory), PAPERASSIST_PLOT_WORKER_ENABLED='0', OPENAI_API_KEY='')
    # URLs enter only the child's environment, never argv, output or evidence.
    environment['PAPERASSIST_DATABASE_URL'] = environment['PAPERASSIST_TEST_DATABASE_URL'] = runtime.url.render_as_string(hide_password=False)
    environment['PAPERASSIST_MIGRATION_DATABASE_URL'] = environment['PAPERASSIST_TEST_MIGRATION_DATABASE_URL'] = config.url.render_as_string(hide_password=False)
    arguments = [sys.executable, '-B', str(Path(__file__).resolve()), '--interrupt-child',
                 '--source', str(source), '--data-dir', str(directory), '--barrier', str(barrier), '--child-schema', config.schema]
    process = subprocess.Popen(arguments, env=environment, cwd=str(BACKEND), stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    reached = False
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if barrier.is_file():
                reached = True
                break
            if process.poll() is not None:
                raise RuntimeError('Owned import child exited before its synthetic interruption barrier.')
            time.sleep(0.05)
        if not reached:
            raise RuntimeError('Owned import child did not reach its interruption barrier in time.')
        process.terminate()
        process.wait(timeout=10)
        return {'method': 'terminate_owned_child_before_reports_insert', 'barrier_reached': True,
                'child_exit_nonzero': process.returncode != 0}
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)


def child_import(source, directory, barrier, schema):
    from app.db.database import get_migration_database_config
    from app.maintenance.legacy_import import import_sqlite
    from sqlalchemy.engine import Connection
    config = get_migration_database_config()
    validate_target(config)
    if config.schema != schema or any(read_target(config).values()):
        raise ValueError('Interrupted child must use the exact empty test schema supplied by its parent.')
    original = Connection.execute

    def pause_before_reports(connection, statement, *args, **kwargs):
        if str(statement).startswith('INSERT INTO reports '):
            with barrier.open('x', encoding='ascii') as stream:
                stream.write('synthetic reports insertion reached\n')
                stream.flush()
                os.fsync(stream.fileno())
            # The parent's owned-process termination is the only completion path.
            while True:
                time.sleep(0.1)
        return original(connection, statement, *args, **kwargs)

    Connection.execute = pause_before_reports
    try:
        import_sqlite(source, directory, config)
    finally:
        Connection.execute = original


def scan_pending_jobs(directory):
    """Only run the application's recovery discovery queries; never poll a provider."""
    from app.adapters.storage import ProjectStore
    from app.adapters.explanation_store import ExplanationStore
    store = ProjectStore(directory)
    return {'figure_jobs': sorted(row['job_id'] for row in store.pending_figures()),
            'explanation_jobs': sorted(row['job_id'] for row in ExplanationStore(store).pending())}


def rehearse_on_config(source, directory, evidence, config):
    """Caller owns a freshly migrated schema. All data remains synthetic."""
    from app.db.database import migration_connection
    from app.maintenance.legacy_import import import_sqlite, inspect_source, JOB_TABLES
    validate_target(config)
    if any(read_target(config).values()):
        raise ValueError('Rehearsal requires an empty isolated test schema.')
    before = file_hashes(directory)
    snapshot = inspect_source(source, directory)
    initial_sequences = sequence_state(config)
    interruption = interrupt_child(source, directory, evidence / 'reports-insert.barrier', config)
    interruption['all_tables_empty'] = not any(read_target(config).values())
    interruption['sequences_unchanged'] = sequence_state(config) == initial_sequences
    if not interruption['all_tables_empty'] or not interruption['sequences_unchanged']:
        raise ValueError('Interrupted transaction did not leave an empty, unchanged test target.')
    write_json(evidence / 'interrupted.json', interruption)
    imported = import_sqlite(source, directory, config)
    write_json(evidence / 'imported.json', imported)
    repeated = import_sqlite(source, directory, config)
    write_json(evidence / 'already-imported.json', repeated)
    if imported['status'] != 'imported' or repeated['status'] != 'already_imported':
        raise ValueError('Import retry/idempotency result did not match the rehearsal contract.')
    if read_target(config) != snapshot.rows:
        raise ValueError('Full original column values or JSON changed after import.')
    pending = scan_pending_jobs(directory)
    expected_pending = {'figure_jobs': ['fj-11', 'fj-29'], 'explanation_jobs': ['ej-19', 'ej-41']}
    if pending != expected_pending:
        raise ValueError('Recovery discovery did not find all synthetic unfinished jobs.')
    next_sequences = {}
    with migration_connection(config=config) as db:
        for table in JOB_TABLES:
            value = db.execute("SELECT nextval(pg_get_serial_sequence(%s,'seq')) AS value",
                               (f'{config.schema}.{table}',)).fetchone()['value']
            expected = max(row['seq'] for row in snapshot.rows[table]) + 1
            if value != expected:
                raise ValueError('Imported job sequence did not preserve its original gaps and next value.')
            next_sequences[table] = value
    source_unchanged = file_hashes(directory) == before
    if not source_unchanged:
        raise ValueError('Synthetic source or assets changed during the rehearsal.')
    result = {'status': 'verified', 'schema': config.schema, 'interruption': interruption,
              'first_status': imported['status'], 'repeat_status': repeated['status'],
              'source_unchanged': source_unchanged, 'next_sequences': next_sequences, 'pending_jobs': pending,
              'cloud_execution': 'not_run; application recovery discovery queries only',
              'sequence_probe': 'nextval consumes one value in each temporary test sequence; no job rows inserted',
              'original_files_sha256': before}
    write_json(evidence / 'execution.json', result)
    return result


@contextmanager
def isolated_environment(settings):
    previous = {key: os.environ.get(key) for key in settings}
    os.environ.update(settings)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def execute_new_schema(source, directory, evidence):
    from app.core.config import local_config
    from dotenv import dotenv_values
    from app.db.database import DatabaseConfig, get_migration_database_config, migrate_database, validate_database_pair
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool
    values = local_config()
    credentials = {**dotenv_values(BACKEND / '.env.migrations', encoding='utf-8-sig', interpolate=False), **os.environ}
    runtime_url = values.get('PAPERASSIST_TEST_DATABASE_URL')
    migration_url = credentials.get('PAPERASSIST_TEST_MIGRATION_DATABASE_URL')
    if not runtime_url or not migration_url:
        raise ValueError('Explicit test runtime and migration URLs are required.')
    schema = 'pa_test_' + uuid4().hex
    runtime = DatabaseConfig('test', runtime_url, schema)
    migration = DatabaseConfig('test', migration_url, schema, 'migration')
    validate_target(migration)
    validate_database_pair(migration, runtime)
    settings = {'PAPERASSIST_ENV': 'test', 'PAPERASSIST_DB_SCHEMA': schema,
                'PAPERASSIST_TEST_DATABASE_URL': runtime_url, 'PAPERASSIST_TEST_MIGRATION_DATABASE_URL': migration_url,
                'PAPERASSIST_DATA_DIR': str(directory), 'PAPERASSIST_PLOT_WORKER_ENABLED': '0', 'OPENAI_API_KEY': ''}
    created = False
    engine = create_engine(migration.url, poolclass=NullPool, hide_parameters=True, connect_args={'connect_timeout': 5})
    quoted = engine.dialect.identifier_preparer.quote(schema)
    try:
        with isolated_environment(settings):
            with engine.begin() as connection:
                if connection.exec_driver_sql('SELECT current_database()').scalar_one() != 'paperassist_system_test':
                    raise ValueError('Actual database must be the isolated test database.')
                connection.exec_driver_sql(f'CREATE SCHEMA {quoted}')
            created = True
            write_json(evidence / 'created-schema.json', {'database': 'paperassist_system_test', 'schema': schema, 'created': True})
            migrate_database(get_migration_database_config())
            result = rehearse_on_config(source, directory, evidence, migration)
    finally:
        try:
            if created and re.fullmatch(r'pa_test_[0-9a-f]{32}', schema):
                with engine.begin() as connection:
                    if connection.exec_driver_sql('SELECT current_database()').scalar_one() != 'paperassist_system_test':
                        raise ValueError('Refusing cleanup outside the actual test database.')
                    connection.exec_driver_sql(f'DROP SCHEMA {quoted} CASCADE')
                write_json(evidence / 'cleanup.json', {'schema': schema, 'dropped_owned_schema': True})
        finally:
            engine.dispose()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Explicitly execute in a newly created isolated test schema')
    parser.add_argument('--interrupt-child', action='store_true', help=argparse.SUPPRESS)
    for name in ('source', 'data-dir', 'barrier'):
        parser.add_argument('--' + name, type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--child-schema', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.interrupt_child:
            if args.execute or not all((args.source, args.data_dir, args.barrier, args.child_schema)):
                parser.error('Invalid interrupted-child arguments.')
            child_import(args.source, args.data_dir, args.barrier, args.child_schema)
            return 1
        if any((args.source, args.data_dir, args.barrier, args.child_schema)):
            parser.error('Sources are generated internally; existing source paths are not accepted.')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        evidence = BACKUPS / ('import-drill-' + stamp)
        evidence.mkdir(parents=True, exist_ok=False)
        source, directory = create_complex_source(evidence / 'synthetic')
        from app.maintenance.legacy_import import inspect_source, snapshot_source
        before = file_hashes(directory)
        inspected = inspect_source(source, directory)
        write_json(evidence / 'dry-run.json', {'status': 'validated', **inspected.manifest()})
        snapshot_source(source, directory, evidence / 'backup')
        if file_hashes(directory) != before:
            raise ValueError('Source changed while preparing the rehearsal.')
        write_json(evidence / 'prepared.json', {'status': 'prepared', 'synthetic_only': True,
                   'counts': inspected.counts, 'hashes': inspected.hashes, 'assets': inspected.assets,
                   'source_unchanged': True, 'database_connected': False})
        if args.execute:
            execute_new_schema(source, directory, evidence)
            print('Synthetic import rehearsal verified. Evidence: ' + str(evidence))
        else:
            print('Synthetic source and backup prepared; database execution requires --execute. Evidence: ' + str(evidence))
        return 0
    except Exception:
        print('Synthetic import rehearsal failed. Retained evidence must be reviewed; no exception or credentials were printed.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
