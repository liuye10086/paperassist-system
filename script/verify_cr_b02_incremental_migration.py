"""Retained V01: old 0058 app seeds a new schema, then current app upgrades it.

Run with the current backend interpreter and --legacy-root ABSOLUTE_PATH.
No public schemas, existing acceptance schemas, services, models, or cleanup.
The old and new app imports live in separate child processes. Only the B01
synthetic registered parser is injected; this proves migration preservation,
not Linux parser isolation, scientific validity, or user acceptance.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'script' / '.runtime' / 'client-requirements-b02' / 'verifications'
OLD_HEAD = '0058_research_intake'
NEW_HEAD = '0059_bio_spatial_analysis'
NEW_TASK_COLUMNS = {'result_bio_processed_dataset_version_id', 'result_bio_figure_version_id'}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def new_state(legacy_root):
    schema = 'pa_test_' + uuid4().hex
    directory = REPORTS / ('v01-' + schema)
    return dict(schema=schema, workspace=str(ROOT), legacy_root=str(Path(legacy_root).resolve()),
        directory=str(directory), assets=str(directory / 'assets'), status='created',
        expected_before=OLD_HEAD, expected_after=NEW_HEAD, retention='preserve_schema_assets_reports')


def validate_state(state):
    if (not isinstance(state, dict) or not re.fullmatch(r'pa_test_[a-f0-9]{32}', state.get('schema', ''))
            or state.get('workspace') != str(ROOT) or state.get('expected_before') != OLD_HEAD
            or state.get('expected_after') != NEW_HEAD):
        raise ValueError('Unexpected verification identity')
    directory = REPORTS / ('v01-' + state['schema'])
    if state.get('directory') != str(directory) or state.get('assets') != str(directory / 'assets'):
        raise ValueError('Verification paths must belong to this new schema')
    old = Path(state['legacy_root'])
    if not old.is_absolute() or old.resolve() == ROOT or not (old / 'backend' / 'app').is_dir():
        raise ValueError('An independent absolute legacy backend is required')
    for path in (directory, Path(state['assets'])):
        if not path.is_absolute() or any(p.is_symlink() or getattr(p, 'is_junction', lambda: False)() for p in [path, *path.parents]):
            raise ValueError('Linked or relative verification path')
    return state


def compare_preservation(before, after):
    failures = []
    for table, expected in before['tables'].items():
        actual = after['tables'].get(table)
        if actual is None:
            failures.append('table:' + table)
            continue
        if actual['columns'] != expected['columns']:
            failures.append('columns:' + table)
        if (actual['count'], actual['sha256']) != (expected['count'], expected['sha256']):
            failures.append('rows:' + table)
    for name, expected in before['indexes'].items():
        if after['indexes'].get(name) != expected:
            failures.append('index:' + name)
    for name, expected in before['assets'].items():
        if after['assets'].get(name) != expected:
            failures.append('asset:' + name)
    if set(after['assets']) != set(before['assets']):
        failures.append('asset_inventory')
    return failures


def private_write(path, value):
    sys.path.insert(0, str(ROOT / 'script' / 'dev'))
    from worker_stack import private_write as write
    write(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def configure(state, backend):
    validate_state(state)
    os.environ.update(PAPERASSIST_ENV='test', PAPERASSIST_DB_SCHEMA=state['schema'],
        PAPERASSIST_DATA_DIR=state['assets'], PAPERASSIST_PLOT_WORKER_ENABLED='0',
        PAPERASSIST_NCBI_ENABLED='0', PAPERASSIST_NCBI_CONFIG_FILE='', PAPERASSIST_NCBI_API_KEY='',
        PAPERASSIST_NCBI_EMAIL='', PAPERASSIST_WRITING_LIVE_ENABLED='0', OPENAI_API_KEY='',
        OPENAI_API_KEY_FILE='', PAPERASSIST_AUTH_TRUSTED_ORIGINS='http://testserver',
        PAPERASSIST_EXPLANATION_POLICY_FILE='', PAPERASSIST_PLOT_POLICY_FILE='',
        PAPERASSIST_ANALYSIS_RECOMMENDATION_POLICY_FILE='', PYTHONDONTWRITEBYTECODE='1')
    sys.path.insert(0, str(backend))
    from app.core.paths import BACKEND_ROOT
    from app.db.database import get_database_config, get_migration_database_config
    if BACKEND_ROOT.resolve() != backend.resolve():
        raise ValueError('Loaded backend differs from the phase identity')
    for config in (get_database_config(), get_migration_database_config()):
        if config.schema != state['schema'] or config.url.database != 'paperassist_system_test':
            raise ValueError('Only the explicit new test schema is allowed')


def assets_snapshot(directory):
    result = {}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            raise ValueError('Linked asset')
        if path.is_file():
            result[path.relative_to(directory).as_posix()] = dict(size=path.stat().st_size,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    return result


def database_snapshot(state, original=None):
    from app.db.database import database_connection
    with database_connection() as db:
        table_names = [r['table_name'] for r in db.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=%s AND table_type='BASE TABLE' AND table_name<>'alembic_version' ORDER BY table_name", (state['schema'],))]
        result = dict(tables={}, indexes={}, head=db.execute('SELECT version_num FROM alembic_version').fetchone()['version_num'])
        quote = db.raw_connection.dialect.identifier_preparer.quote
        for name in table_names:
            columns = [r['column_name'] for r in db.execute('SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position', (state['schema'], name))]
            chosen = original['tables'][name]['columns'] if original and name in original['tables'] else columns
            if not set(chosen) <= set(columns):
                raise ValueError('A preexisting column disappeared')
            if original and name in original['tables']:
                added = set(columns) - set(chosen)
                if added != (NEW_TASK_COLUMNS if name == 'tasks' else set()):
                    raise ValueError('Unexpected legacy table column delta')
                if added:
                    nonnull = db.execute('SELECT count(*) AS n FROM tasks WHERE ' + ' OR '.join(quote(c) + ' IS NOT NULL' for c in sorted(added))).fetchone()['n']
                    if nonnull:
                        raise ValueError('Legacy tasks acquired new result pointers')
            sql = 'SELECT to_jsonb(t) AS value FROM (SELECT ' + ','.join(quote(c) for c in chosen) + ' FROM ' + quote(name) + ') t'
            values = sorted(canonical(r['value']) for r in db.execute(sql))
            result['tables'][name] = dict(columns=chosen, count=len(values), sha256=digest(values))
        for row in db.execute('SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname=%s ORDER BY indexname', (state['schema'],)):
            if row['tablename'] != 'alembic_version':
                result['indexes'][row['indexname']] = dict(table=row['tablename'], definition=row['indexdef'])
    result['assets'] = assets_snapshot(Path(state['assets']))
    return result


def require_response(response, status=201):
    if response.status_code != status:
        raise RuntimeError('Unexpected HTTP response: ' + str(response.status_code))
    return response.json()


def seed_legacy(state):
    from app.db.database import SCHEMA_HEAD, get_migration_database_config, get_engine, migrate_database, database_connection
    if SCHEMA_HEAD != OLD_HEAD:
        raise ValueError('Legacy source must still declare exactly 0058')
    config = get_migration_database_config()
    engine = get_engine(config)
    with engine.begin() as db:
        if db.exec_driver_sql('SELECT current_database()').scalar_one() != 'paperassist_system_test':
            raise ValueError('Unexpected database')
        if db.exec_driver_sql('SELECT 1 FROM pg_namespace WHERE nspname=%s', (state['schema'],)).scalar():
            raise ValueError('Refusing to reuse any existing schema')
        db.exec_driver_sql('CREATE SCHEMA ' + engine.dialect.identifier_preparer.quote(state['schema']))
    migrate_database(config)
    from fastapi.testclient import TestClient
    from app.main import app
    from tests.helpers.auth import login_test_client
    from tests.api.test_projects import create_project, upload
    from tests.api.test_research_intake import research
    from tests.integration.test_bio_import_publication import create_import, run, read, confirm
    seed = {'model_calls': 0, 'bio_parser': 'B01 existing pure registered parser on synthetic Visium fixture'}
    with TestClient(app) as client:
        login_test_client(client)
        sci = create_project(client, 'V01 existing SCI', 'sci')
        thesis = create_project(client, 'V01 existing thesis', 'thesis')
        project = research(client, 'v01-research')
        seed['projects'] = [dict(id=p['id'], project_type=p['project_type']) for p in (sci, thesis, project)]
        xlsx = require_response(upload(client, sci['id']))['file']
        if xlsx['parse_status'] != 'parsed':
            raise RuntimeError('The old XLSX path did not produce a parsed original')
        seed['xlsx_file_id'] = xlsx['id']
        base = '/api/v1/projects/' + project['id']
        requirement = require_response(client.post(base + '/requirements', headers={'Idempotency-Key': 'v01-requirement'}, json={
            'expected_revision': 1, 'operation': 'save', 'content': {'schema_version': 1, 'services': ['analysis']}, 'material_refs': []}))
        design = require_response(client.post(base + '/research-designs', headers={'Idempotency-Key': 'v01-design'}, json={
            'expected_revision': requirement['revision'], 'operation': 'save', 'material_refs': [],
            'content': {'schema_version': 1, 'experiments': [{'id': 'e', 'data_type': 'spatial'}],
                'groups': [{'id': 'g', 'experiment_id': 'e', 'name': 'engineering fixture'}],
                'samples': [{'id': 's', 'experiment_id': 'e', 'group_id': 'g'}]}}))
        seed.update(requirement_version_id=requirement['version']['id'], design_version_id=design['version']['id'])
        base, created, file_id, content = create_import(client)
        if run(created['task'])['status'] != 'waiting_confirmation':
            raise RuntimeError('Old B01 did not release into confirmation')
        view = read(client, base, created)
        queued = require_response(confirm(client, base, created, view), 202)
        if run(queued)['status'] != 'succeeded':
            raise RuntimeError('Old B01 publication failed')
        published = read(client, base, created)['result_source']
        if client.get(base + '/files/' + file_id + '/download').content != content:
            raise RuntimeError('Old B01 original differs')
        seed.update(bio_source=published, bio_task_id=created['task']['id'])
    # No client or background lifespan remains when taking the migration baseline.
    with database_connection() as db:
        if db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']:
            raise RuntimeError('Unexpected model call')
    before = database_snapshot(state)
    if before['head'] != OLD_HEAD or before['tables']['bio_dataset_versions']['count'] != 1:
        raise RuntimeError('Old dataset was not seeded at 0058')
    private_write(Path(state['directory']) / 'seed.json', seed)
    private_write(Path(state['directory']) / 'before.json', before)


def upgrade_and_verify(state):
    from app.db.database import SCHEMA_HEAD, migrate_database, database_connection, verify_runtime_permissions
    from app.db.bio_analysis_schema import TABLE_NAMES
    from app.maintenance.database_audit import audit_database
    if SCHEMA_HEAD != NEW_HEAD:
        raise ValueError('Current source must declare exactly 0059')
    directory = Path(state['directory'])
    before = json.loads((directory / 'before.json').read_text(encoding='utf-8'))
    if before['head'] != OLD_HEAD:
        raise ValueError('Missing old-process baseline')
    with database_connection() as db:
        if db.execute('SELECT version_num FROM alembic_version').fetchone()['version_num'] != OLD_HEAD:
            raise ValueError('Expected a seeded 0058 schema, not a fresh current schema')
    migrate_database()
    after = database_snapshot(state, before)
    failures = compare_preservation(before, after)
    added = set(after['tables']) - set(before['tables'])
    if added != set(TABLE_NAMES) or any(after['tables'][t]['count'] for t in added):
        failures.append('new_table_inventory')
    with database_connection() as db:
        verify_runtime_permissions(db.raw_connection, db.config)
        permissions = []
        immutable = {'bio_observation_map_versions','bio_analysis_recipe_versions','bio_processed_dataset_versions',
                     'bio_analysis_artifacts','bio_annotation_versions','bio_annotation_evidence','bio_figure_members'}
        for name in TABLE_NAMES:
            privileges = {p: db.execute('SELECT has_table_privilege(current_user,%s,%s) AS allowed',
                (state['schema'] + '.' + name, p)).fetchone()['allowed'] for p in ('SELECT','INSERT','UPDATE','DELETE','TRUNCATE')}
            expected = dict(SELECT=True, INSERT=True, UPDATE=name not in immutable, DELETE=name not in immutable, TRUNCATE=False)
            if privileges != expected:
                failures.append('permissions:' + name)
            permissions.append(dict(table=name, actual=privileges, expected=expected))
        audit = audit_database(db)
        if not audit['ok']:
            failures.append('database_audit')
    private_write(directory / 'after.json', after)
    private_write(directory / 'audit.json', audit)
    private_write(directory / 'permissions.json', permissions)
    report = dict(schema=state['schema'], before_head=before['head'], after_head=after['head'],
        status='passed' if not failures else 'failed', failures=failures,
        old_tables=len(before['tables']), old_rows=sum(t['count'] for t in before['tables'].values()),
        old_indexes=len(before['indexes']), original_assets=len(before['assets']),
        new_tables=sorted(added), privileges_checked=True, database_audit_ok=audit['ok'],
        baseline_sha256=digest(before), after_sha256=digest(after),
        allowed_old_column_change={'tasks': sorted(NEW_TASK_COLUMNS)},
        model_calls=0, service_started=False, retained=True,
        limitations=['Synthetic B01 input and injected existing pure parser; no Linux isolation claim',
            'No numerical pipeline, browser, biological validation, or user acceptance performed'])
    private_write(directory / 'report.json', report)
    if failures:
        raise RuntimeError('Migration preservation verification failed')


def execute(legacy_root):
    state = validate_state(new_state(legacy_root))
    directory = Path(state['directory'])
    directory.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(ROOT / 'script' / 'dev'))
    from worker_stack import protect_directory
    protect_directory(directory)
    Path(state['assets']).mkdir()
    state_path = directory / 'state.json'
    private_write(state_path, state)
    # Fixed test URLs are inherited privately by both phases, never argv/report.
    from dotenv import dotenv_values
    env = dict(os.environ)
    for filename, key in [('.env', 'PAPERASSIST_TEST_DATABASE_URL'), ('.env.migrations', 'PAPERASSIST_TEST_MIGRATION_DATABASE_URL')]:
        value = env.get(key) or dotenv_values(ROOT / 'backend' / filename, interpolate=False, encoding='utf-8-sig').get(key)
        if not value:
            raise ValueError('Dedicated test connection not configured')
        env[key] = value
    env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1')
    interpreter = ROOT / 'backend' / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    for phase in ('seed', 'upgrade'):
        state['status'] = 'running_' + phase
        private_write(state_path, state)
        with (directory / (phase + '.log')).open('wb') as log:
            result = subprocess.run([str(interpreter), '-B', str(Path(__file__).resolve()), '--phase', phase,
                '--state', str(state_path)], cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT, timeout=300)
        if result.returncode:
            state['status'] = 'failed_' + phase
            private_write(state_path, state)
            print(canonical({'status': state['status'], 'schema': state['schema'], 'directory': str(directory)}))
            return 1
    state['status'] = 'passed'
    private_write(state_path, state)
    print(canonical({'status': 'passed', 'schema': state['schema'], 'report': str(directory / 'report.json')}))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--legacy-root', type=Path)
    parser.add_argument('--phase', choices=('seed', 'upgrade'))
    parser.add_argument('--state', type=Path)
    args = parser.parse_args()
    try:
        if args.phase:
            state = validate_state(json.loads(args.state.read_text(encoding='utf-8')))
            if args.state.resolve() != Path(state['directory']) / 'state.json':
                raise ValueError('Unexpected state location')
            backend = (Path(state['legacy_root']) if args.phase == 'seed' else ROOT) / 'backend'
            configure(state, backend)
            (seed_legacy if args.phase == 'seed' else upgrade_and_verify)(state)
            print(canonical({'phase': args.phase, 'status': 'passed'}))
            return 0
        if args.legacy_root is None or not args.legacy_root.is_absolute():
            raise ValueError('Supply an absolute --legacy-root')
        return execute(args.legacy_root)
    except Exception as exc:
        # Do not serialize exception bodies, SQL parameters, URLs or credentials.
        print(canonical({'status': 'failed', 'error_type': type(exc).__name__, 'phase': args.phase or 'orchestrate'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
