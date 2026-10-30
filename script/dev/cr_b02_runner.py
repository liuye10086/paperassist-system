"""Explicit, batch-owned acceptance controls; never targets a public schema."""
import argparse
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
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / 'script' / '.runtime' / 'client-requirements-b02'
HERE = RUNTIME / 'acceptance'
STATE = RUNTIME / 'state.json'
GATE = RUNTIME / 'runtime-gate.json'
WORKER_IMAGE = 'paperassist-client-b02-worker:local'
SCIENCE_IMAGE = 'paperassist-bio-runtime:cr-b02-final'
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'script' / 'dev'))
import worker_stack


def new_state(schema):
    directory = HERE / schema
    return {'schema': schema, 'workspace': str(ROOT), 'layout_version': 2, 'assets': str(directory / 'assets'),
            'staging': str(directory / 'bio-staging'), 'runtime_manifest': str(GATE),
            'bind_host': '127.0.0.82', 'port': 18082, 'url': 'http://127.0.0.82:18082', 'purpose': 'CR-B02 user acceptance',
            'stack_project': 'pa-test-' + schema.removeprefix('pa_test_'),
            'worker_image': WORKER_IMAGE, 'public_database_modified': False, 'status': 'preparing'}


def validate_state(state):
    if not isinstance(state, dict) or not re.fullmatch(r'pa_test_[a-f0-9]{32}', state.get('schema', '')):
        raise ValueError('This runner requires its own random test schema')
    if state.get('workspace') != str(ROOT) or state.get('worker_image') != WORKER_IMAGE:
        raise ValueError('The batch workspace/image identity differs')
    if state.get('layout_version', 1) not in (1, 2):
        raise ValueError('Unsupported batch directory layout')
    directory = run_directory(state)
    for key, expected in [('assets', directory / 'assets'), ('staging', directory / 'bio-staging'), ('runtime_manifest', GATE)]:
        if state.get(key) != str(expected):
            raise ValueError('A retained or unrelated path cannot be targeted')
    port = state.get('port')
    host = state.get('bind_host', '127.0.0.1')
    if (host not in ('127.0.0.1', '127.0.0.82') or type(port) is not int or not 18082 <= port <= 18099
            or state.get('url') != f'http://{host}:{port}'
            or state.get('stack_project') != 'pa-test-' + state['schema'][8:]
            or state.get('public_database_modified') is not False):
        raise ValueError('Invalid isolated acceptance endpoint/stack')
    return state


def run_directory(state):
    return HERE / state['schema'] if state.get('layout_version', 1) == 2 else HERE


def migration_digest():
    return hashlib.sha256((ROOT / 'backend' / 'alembic' / 'versions' / '0059_bio_spatial_analysis.py').read_bytes()).hexdigest()


def save_state(state):
    validate_state(state)
    worker_stack.private_write(STATE, json.dumps(state, ensure_ascii=False, indent=2) + '\n')


def read_state(path=STATE):
    if Path(path).resolve() != STATE.resolve():
        raise ValueError('Only this batch state file may be used')
    return validate_state(json.loads(STATE.read_text(encoding='utf-8')))


def configure(state):
    validate_state(state)
    os.environ.update(PAPERASSIST_ENV='test', PAPERASSIST_DB_SCHEMA=state['schema'],
        PAPERASSIST_DATA_DIR=state['assets'], PAPERASSIST_BIO_STAGING_DIR=state['staging'],
        PAPERASSIST_BIO_RUNTIME_MANIFEST=state['runtime_manifest'], PAPERASSIST_PLOT_WORKER_ENABLED='0',
        PAPERASSIST_NCBI_ENABLED='0', PAPERASSIST_NCBI_CONFIG_FILE='', PAPERASSIST_NCBI_API_KEY='',
        PAPERASSIST_NCBI_EMAIL='', PAPERASSIST_WRITING_LIVE_ENABLED='0', OPENAI_API_KEY='', OPENAI_API_KEY_FILE='',
        PAPERASSIST_AUTH_TRUSTED_ORIGINS=state['url'], PAPERASSIST_AUTH_IDLE_SECONDS='86400',
        PAPERASSIST_AUTH_ABSOLUTE_SECONDS='604800', PAPERASSIST_EXPLANATION_POLICY_FILE='',
        PAPERASSIST_PLOT_POLICY_FILE='', PAPERASSIST_ANALYSIS_RECOMMENDATION_POLICY_FILE='')


def port_open(port, host='127.0.0.82'):
    with socket.socket() as connection:
        connection.settimeout(.2)
        return connection.connect_ex((host, port)) == 0


def prepare():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    HERE.mkdir(parents=True, exist_ok=True)
    worker_stack.protect_directory(HERE)
    state = read_state() if STATE.exists() else new_state('pa_test_' + uuid4().hex)
    if state.get('status') == 'ready':
        if state.get('migration_digest') != migration_digest():
            raise RuntimeError('Prepared migration differs; use prepare-new and retain this schema')
        return state
    directory = run_directory(state)
    directory.mkdir(parents=True, exist_ok=True)
    worker_stack.protect_directory(directory)
    for port in range(18082, 18100):
        if not port_open(port, state.get('bind_host', '127.0.0.1')):
            state.update(port=port, url=f"http://{state.get('bind_host', '127.0.0.1')}:{port}")
            break
    else:
        raise RuntimeError('No free local acceptance port; no other service was stopped')
    save_state(state)
    configure(state)
    from app.db.database import get_migration_database_config, get_engine, migrate_database, database_connection
    config = get_migration_database_config()
    engine = get_engine(config)
    with engine.begin() as db:
        if db.exec_driver_sql('SELECT current_database()').scalar_one() != 'paperassist_system_test':
            raise ValueError('The public/development database cannot be migrated')
        exists = db.exec_driver_sql('SELECT 1 FROM pg_namespace WHERE nspname=%s', (state['schema'],)).scalar()
        if not exists:
            db.exec_driver_sql('CREATE SCHEMA ' + engine.dialect.identifier_preparer.quote(state['schema']))
    migrate_database(config)
    from app.domain.storage_governance.deletion import register_new_test_schema
    register_new_test_schema(state['schema'])
    credentials_path = directory / 'credentials.json'
    credentials = json.loads(credentials_path.read_text(encoding='utf-8')) if credentials_path.exists() else {}
    from app.auth.service import create_user
    for name, role in [('review', 'user'), ('other', 'user'), ('admin', 'admin')]:
        if name not in credentials:
            credentials[name] = {'email': f'cr-b02-{name}@paperassist.local', 'password': 'CrB02-' + secrets.token_urlsafe(24)}
            worker_stack.private_write(credentials_path, json.dumps(credentials, ensure_ascii=False, indent=2))
        with database_connection() as db:
            existing = db.execute('SELECT id FROM users WHERE email=%s', (credentials[name]['email'],)).fetchone()
        user = existing or create_user(credentials[name]['email'], credentials[name]['password'], role=role)
        credentials[name]['id'] = user['id']
        worker_stack.private_write(credentials_path, json.dumps(credentials, ensure_ascii=False, indent=2))
    from app.adapters.storage import ProjectStore
    store = ProjectStore(Path(state['assets']), owner_id=credentials['review']['id'])
    legacy = []
    for kind, title in [('sci', 'CR-B02 SCI兼容样例'), ('thesis', 'CR-B02 毕业论文兼容样例')]:
        with database_connection() as db:
            old = db.execute('SELECT id FROM projects WHERE owner_id=%s AND name=%s', (credentials['review']['id'], title)).fetchone()
        legacy.append((old or store.create_project(title, '合成工程验收', kind))['id'])
    state.update(legacy_projects=legacy, status='ready', migration_digest=migration_digest())
    save_state(state)
    return state


def prepare_new():
    retained = []
    if STATE.exists():
        old = read_state()
        if port_open(old['port'], old.get('bind_host', '127.0.0.1')):
            raise RuntimeError('A running acceptance server must be explicitly stopped before changing its state')
        stack = worker_stack.load(ROOT, test_id=old['schema'][8:])
        if stack and any(c['status'] == 'running' for c in worker_stack.owned_containers(stack)):
            raise RuntimeError('This retained stack is running; refusing to replace its state')
        archive = RUNTIME / 'retained-preparations' / old['schema']
        archive.mkdir(parents=True, exist_ok=True)
        worker_stack.protect_directory(archive)
        for source in [STATE, run_directory(old) / 'credentials.json']:
            if source.exists():
                destination = archive / source.name
                if destination.exists() and destination.read_bytes() != source.read_bytes():
                    raise RuntimeError('A different preparation snapshot already exists; refusing overwrite')
                shutil.copy2(source, destination)
        retained = [*old.get('retained_preparations', []), str(archive / 'state.json')]
    state = new_state('pa_test_' + uuid4().hex)
    state['retained_preparations'] = retained
    save_state(state)
    return prepare()


def serve():
    state = read_state()
    configure(state)
    import uvicorn
    from fastapi.staticfiles import StaticFiles
    from app.main import app
    app.mount('/', StaticFiles(directory=ROOT / 'frontend' / 'dist', html=True), name='cr-b02-acceptance')
    uvicorn.run(app, host=state.get('bind_host', '127.0.0.1'), port=state['port'], log_level='warning')


def start_api():
    state = read_state()
    if port_open(state['port'], state.get('bind_host', '127.0.0.1')):
        raise RuntimeError('Acceptance port is occupied; refusing to start a second server')
    configure(state)
    directory = run_directory(state)
    receipt = directory / 'api-process.json'
    if receipt.exists():
        history = directory / 'api-process-history'
        history.mkdir(exist_ok=True)
        worker_stack.private_write(history / (uuid4().hex + '.json'), receipt.read_text(encoding='utf-8'))
    with (directory / 'api.stdout.log').open('ab') as out, (directory / 'api.stderr.log').open('ab') as err:
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'serve'], cwd=ROOT / 'backend',
            stdout=out, stderr=err, stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    worker_stack.private_write(receipt, json.dumps({'pid': child.pid, 'executable': sys.executable,
        'script': str(Path(__file__).resolve()), 'workspace': str(ROOT), 'port': state['port'],
        'source_digest':source_digest(),
        'frontend_index_sha256':hashlib.sha256((ROOT/'frontend/dist/index.html').read_bytes()).hexdigest()}, indent=2))
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(80):
        try:
            with opener.open(state['url'] + '/api/v1/health', timeout=.5) as response:
                if response.status == 200:
                    return {'api': 'ready', 'url': state['url'], 'pid': child.pid}
        except OSError:
            pass
        if child.poll() is not None:
            raise RuntimeError('Acceptance API failed; inspect this batch private stderr log')
        time.sleep(.25)
    raise RuntimeError('Acceptance API startup timed out; process receipt retained')


def compose(stack, override, arguments, timeout=180):
    return worker_stack.docker(['compose', '--project-name', stack.project, '--file', str(ROOT / 'compose.workers.yml'),
        '--file', str(override), *arguments], stack=stack, timeout=timeout)


def source_digest():
    source = ROOT / 'backend' / 'app'
    result = hashlib.sha256()
    for path in sorted(source.rglob('*.py'), key=lambda p: p.relative_to(source).as_posix()):
        result.update(path.relative_to(source).as_posix().encode() + b'\0' + path.read_bytes() + b'\0')
    return result.hexdigest()


def workers():
    state = read_state()
    configure(state)
    from app.core.config import local_config
    from app.domain.bioinformatics.analysis_settings import runtime_identity
    if not runtime_identity()['available']:
        raise RuntimeError('A current numeric/isolation/HDF5/plot attestation is required')
    inspect = worker_stack.docker(['image', 'inspect', '--format', '{{.Id}}', WORKER_IMAGE]).strip()
    check_code = "from pathlib import Path;import hashlib;r=Path('/app/app');h=hashlib.sha256();[(h.update(p.relative_to(r).as_posix().encode()+b'\\0'+p.read_bytes()+b'\\0')) for p in sorted(r.rglob('*.py'),key=lambda p:p.relative_to(r).as_posix())];print(h.hexdigest())"
    actual = worker_stack.docker(['run', '--rm', '--network', 'none', '--read-only', '--memory', '128m',
        '--entrypoint', 'python', inspect, '-c', check_code]).strip()
    if actual != source_digest():
        raise RuntimeError('Worker image source differs; rebuild the dedicated image')
    memory = worker_stack.docker(['run', '--rm', '--network', 'none', '--read-only', '--memory', '64m', '--entrypoint', 'python',
        inspect, '-c', "from pathlib import Path;print(next(x.split()[1] for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:')))"])
    if int(memory.strip()) * 1024 < 4 * 1024**3:
        raise RuntimeError('Docker available memory is below the user-approved 4GiB gate')
    Path(state['staging']).mkdir(parents=True, exist_ok=True)
    stack = worker_stack.prepare(ROOT, local_config(), test_id=state['schema'][8:], assets=Path(state['assets']))
    worker_stack.owned_containers(stack)  # Reject a foreign compose workspace label.
    override = RUNTIME / 'compose.override.json'
    mounts = [{'type': 'bind', 'source': str(GATE), 'target': '/run/bio-runtime.json', 'read_only': True},
              {'type': 'bind', 'source': state['staging'], 'target': '/bio-staging'}]
    config = {'services': {name: {'image': inspect,
        'environment': {'PAPERASSIST_BIO_RUNTIME_MANIFEST': '/run/bio-runtime.json', 'PAPERASSIST_BIO_STAGING_DIR': '/bio-staging'},
        'volumes': mounts, **({'mem_limit': '4g', 'cpus': 1} if name == 'worker' else {})} for name in ['worker', 'dispatcher']}}
    worker_stack.private_write(override, json.dumps(config, indent=2))
    compose(stack, override, ['config', '--quiet'])
    compose(stack, override, ['build', 'pdf-renderer'], timeout=1200)
    compose(stack, override, ['up', '-d', '--no-build', '--wait', '--wait-timeout', '120'], timeout=180)
    state.update(worker_image_id=inspect, worker_source_digest=actual, docker_mem_available_before_start=int(memory.strip()) * 1024,
                 worker_override=str(override))
    save_state(state)
    return {'stack': stack.project, 'containers': worker_stack.owned_containers(stack), 'image_id': inspect}


def verify(action):
    state = read_state()
    configure(state)
    if action in {'verify-runtime', 'verify-numeric'}:
        command = ['/opt/paperassist-bio/bin/python', '-m', 'app.adapters.bio_engine.runtime_probe'] if action == 'verify-runtime' else [
            '/opt/paperassist-bio/bin/python', '-m', 'pytest', '/app/tests/numeric', '-p', 'no:cacheprovider', '--noconftest', '-q']
        result = subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--read-only', '--memory', '2g', '--cpus', '1',
            '--tmpfs', '/tmp:rw,nosuid,nodev,size=1536m', SCIENCE_IMAGE, *command], cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
        evidence = RUNTIME / 'verifications' / (action + '-' + uuid4().hex)
        evidence.mkdir(parents=True)
        worker_stack.private_write(evidence / 'stdout.txt', result.stdout)
        worker_stack.private_write(evidence / 'stderr.txt', result.stderr)
        if result.returncode:
            raise RuntimeError('Scoped verification failed; private evidence retained')
        return {'verification': action, 'exit_code': result.returncode, 'evidence': str(evidence / 'stdout.txt')}
    script = ROOT / 'script' / 'verify_cr_b02_queue.py'
    result = subprocess.run([sys.executable, str(script), '--state', str(STATE)], cwd=ROOT)
    if result.returncode:
        raise RuntimeError('Real queue verification did not pass; retain its evidence')
    return {'verification': action, 'exit_code': 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'prepare-new', 'serve', 'start-api', 'workers', 'state', 'verify-runtime', 'verify-numeric', 'verify-queue'])
    parser.add_argument('--state', default=str(STATE))
    args = parser.parse_args()
    if Path(args.state).resolve() != STATE.resolve():
        raise ValueError('Only the current CR-B02 state is accepted')
    if args.action == 'serve':
        serve()
        return
    result = (prepare() if args.action == 'prepare' else prepare_new() if args.action == 'prepare-new' else start_api() if args.action == 'start-api' else
              workers() if args.action == 'workers' else read_state() if args.action == 'state' else verify(args.action))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
