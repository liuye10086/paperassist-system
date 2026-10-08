"""Project-scoped Linux services; no secret values enter Docker arguments or output."""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from dotenv import dotenv_values


@dataclass(frozen=True)
class Stack:
    root: Path
    directory: Path
    project: str
    environment: dict[str, str]


def protect_directory(path: Path) -> None:
    """Keep generated credentials private before creating their files."""
    if os.name == 'nt':
        identity = subprocess.run(['whoami', '/user', '/fo', 'csv', '/nh'], capture_output=True,
                                  check=True)
        sid = next(csv.reader(identity.stdout.decode('utf-8', errors='replace').splitlines()))[1]
        subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r', f'*{sid}:(OI)(CI)F'],
                       capture_output=True, check=True)
    else:
        path.chmod(0o700)


def private_write(path: Path, value: str) -> None:
    if path.exists() and path.read_text(encoding='utf-8') == value:
        return
    temporary = path.with_name(path.name + '.writing')
    with temporary.open('w', encoding='utf-8', newline='\n') as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    if os.name != 'nt':
        path.chmod(0o600)


def _identity(root: Path, test_id: str | None = None):
    root = root.resolve()
    identity = hashlib.sha256(os.path.normcase(str(root)).encode()).hexdigest()[:12]
    if test_id is not None and not re.fullmatch('[0-9a-f]{32}', test_id):
        raise ValueError('Test stack requires a UUID hex identifier.')
    name = 'test-' + test_id if test_id else 'development'
    project = 'pa-test-' + test_id if test_id else 'paperassist-' + identity
    return root, root / 'script' / '.runtime' / 'workers' / name, project


def prepare(root: Path, values: dict, *, test_id=None, assets: Path | None = None) -> Stack:
    root, directory, project = _identity(root, test_id)
    mode = 'test' if test_id else 'development'
    schema = 'pa_test_' + test_id if test_id else 'public'
    if values.get('PAPERASSIST_ENV', 'development') != mode or values.get('PAPERASSIST_DB_SCHEMA', 'public') != schema:
        raise ValueError('Stack environment/schema does not match its explicit mode.')
    key = 'PAPERASSIST_TEST_DATABASE_URL' if test_id else 'PAPERASSIST_DATABASE_URL'
    from app.db.database import DatabaseConfig
    config = DatabaseConfig(mode, values.get(key, ''), schema)
    url = config.url
    expected_role = 'paperassist_test_runtime' if test_id else 'paperassist_runtime'
    if url.username != expected_role or not url.password or url.host not in {'localhost', '127.0.0.1', '::1'}:
        raise ValueError('Worker requires the existing local runtime database role, not an owner or remote endpoint.')
    development_assets = (root / 'backend' / Path(values.get('PAPERASSIST_DATA_DIR') or 'data').expanduser()).resolve()
    if test_id:
        if assets is None:
            raise ValueError('Test stack requires an explicit isolated assets directory.')
        data = assets.resolve()
        default_assets = (root / 'backend' / 'data').resolve()
        saved = dotenv_values(root / 'backend' / '.env', encoding='utf-8-sig', interpolate=False)
        configured_assets = (root / 'backend' / Path(saved.get('PAPERASSIST_DATA_DIR') or 'data').expanduser()).resolve()
        if any(data == target or target in data.parents for target in (default_assets, configured_assets)):
            raise ValueError('Test stack must not mount development assets.')
    else:
        data = development_assets
    data.mkdir(parents=True, exist_ok=True)
    directory.mkdir(parents=True, exist_ok=True)
    protect_directory(directory)
    # Credentials are retained across restarts because the broker volume retains its users.
    broker_path = directory / 'broker-url'
    rabbit_path = directory / 'rabbitmq.conf'
    if broker_path.exists() != rabbit_path.exists():
        raise ValueError('Incomplete broker credentials; restore the matching private files before starting.')
    if not broker_path.exists():
        password = secrets.token_urlsafe(36)
        vhost = 'paperassist_test' if test_id else 'paperassist_dev'
        private_write(broker_path, f'amqp://paperassist:{password}@rabbitmq:5672/{vhost}')
        private_write(rabbit_path, f'default_user = paperassist\ndefault_pass = {password}\ndefault_vhost = {vhost}\n')
    private_write(directory / 'database-url', url.set(host='host.docker.internal').render_as_string(hide_password=False))
    # Test workers never receive a development model key, even when inherited
    # environment values point at a real secret file.
    model_key = ''
    if not test_id:
        if values.get('OPENAI_API_KEY_FILE'):
            secret_path = (root / 'backend' / Path(values['OPENAI_API_KEY_FILE']).expanduser()).resolve()
            with secret_path.open('rb') as stream:
                raw_key = stream.read(8193)
            if len(raw_key) > 8192:
                raise ValueError('Invalid private model key configuration.')
            model_key = raw_key.decode('utf-8-sig').strip()
        else:
            model_key = (values.get('OPENAI_API_KEY') or '').strip()
        if len(model_key.encode('utf-8')) > 8192 or any(char.isspace() for char in model_key):
            raise ValueError('Invalid private model key configuration.')
    private_write(directory / 'model-api-key', model_key)
    fingerprint = hashlib.sha256((url.render_as_string(hide_password=False) + '\0' + model_key).encode()).hexdigest()
    environment = {
        'PAPERASSIST_STACK_PROJECT': project,
        'PAPERASSIST_STACK_ROOT': str(root),
        'PAPERASSIST_STACK_PRIVATE': str(directory),
        'PAPERASSIST_STACK_DATA': str(data),
        'PAPERASSIST_ENV': mode,
        'PAPERASSIST_DB_SCHEMA': schema,
        'PAPERASSIST_TASK_QUEUE': 'paperassist.test.' + test_id if test_id else 'paperassist.word',
        'PAPERASSIST_QUEUE_TEST_ALLOWED': '1' if test_id else '0',
        'PAPERASSIST_DATABASE_SECRET_KEY': key + '_FILE',
        'PAPERASSIST_WORKER_CONFIG_REVISION': fingerprint,
    }
    private_write(directory / 'stack.json', json.dumps({'root': str(root), 'project': project,
                                                       'environment': environment}, indent=2))
    return Stack(root, directory, project, environment)


def load(root: Path, *, test_id=None) -> Stack | None:
    root, directory, project = _identity(root, test_id)
    path = directory / 'stack.json'
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding='utf-8'))
    if value.get('root') != str(root) or value.get('project') != project:
        raise ValueError('Worker state belongs to another workspace; no container was changed.')
    env = value['environment']
    if (env.get('PAPERASSIST_STACK_ROOT') != str(root) or env.get('PAPERASSIST_STACK_PROJECT') != project
            or env.get('PAPERASSIST_STACK_PRIVATE') != str(directory)):
        raise ValueError('Worker state identity is invalid; no container was changed.')
    return Stack(root, directory, project, env)


def docker(arguments: list[str], *, stack: Stack | None = None, timeout=120) -> str:
    environment = os.environ.copy()
    if stack:
        environment.update(stack.environment)
    try:
        result = subprocess.run(['docker', *arguments], env=environment, cwd=ROOT, capture_output=True,
                                encoding='utf-8', errors='replace', timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError('Docker command unavailable or timed out; check Docker Desktop and project logs.') from None
    if result.returncode:
        # Commands can include third-party exception text; no raw output enters UI/logs.
        raise RuntimeError('Docker command failed; verify Docker Desktop, image access, local credentials and permissions.')
    return result.stdout


def compose(stack: Stack, arguments: list[str], timeout=120) -> str:
    return docker(['compose', '--project-name', stack.project, '--file', str(ROOT / 'compose.workers.yml'),
                   *arguments], stack=stack, timeout=timeout)


def ensure_docker() -> None:
    try:
        system = docker(['info', '--format', '{{.OSType}}'], timeout=15).strip()
    except RuntimeError:
        docker(['desktop', 'start', '--detach'], timeout=30)
        import time
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                system = docker(['info', '--format', '{{.OSType}}'], timeout=10).strip()
                break
            except RuntimeError:
                time.sleep(2)
        else:
            raise RuntimeError('Docker Desktop did not become ready.') from None
    if system != 'linux':
        raise RuntimeError('PaperAssist Worker requires Docker Linux containers.')


def owned_containers(stack: Stack) -> list[dict]:
    ids = docker(['ps', '-aq', '--filter', 'label=com.docker.compose.project=' + stack.project]).split()
    if not ids:
        return []
    # Read only identity/state. Docker inspect without a format would expose env.
    template = '{{json .Id}}|{{json .Config.Labels}}|{{json .State.Status}}|{{if .State.Health}}{{json .State.Health.Status}}{{else}}"none"{{end}}'
    rows = docker(['inspect', '--format', template, *ids]).splitlines()
    result = []
    for row in rows:
        cid, labels, status, health = [json.loads(value) for value in row.split('|')]
        if labels.get('io.paperassist.workspace') != str(stack.root):
            raise ValueError('A Compose project collision was found; no container was changed.')
        result.append({'id': cid, 'service': labels.get('com.docker.compose.service'), 'status': status, 'health': health})
    return result


def stop(stack: Stack) -> None:
    containers = owned_containers(stack)
    if not containers:
        return
    for name in ('dispatcher', 'worker', 'rabbitmq'):
        for item in containers:
            if item['service'] == name and item['status'] == 'running':
                docker(['stop', '--time', '45', item['id']], timeout=60)


def start(stack: Stack) -> None:
    ensure_docker()
    before = owned_containers(stack)  # Check ownership before Compose can replace anything.
    revision = stack.environment.get('PAPERASSIST_WORKER_CONFIG_REVISION', '')
    applied_path = stack.directory / 'applied-config-revision'
    configuration_applied = applied_path.exists() and applied_path.read_text(encoding='utf-8') == revision
    if (configuration_applied and len(before) == 3 and {item['service'] for item in before} == {'worker', 'dispatcher', 'rabbitmq'}
            and all(item['status'] == 'running' and item['health'] == 'healthy' for item in before)):
        return
    previously_running = {item['id'] for item in before if item['status'] == 'running'}
    compose(stack, ['config', '--quiet'])
    print('Building Linux Worker image...', flush=True)
    compose(stack, ['build', 'worker'], timeout=1200)
    print('Starting project broker and Worker services...', flush=True)
    try:
        compose(stack, ['up', '-d', '--wait', '--wait-timeout', '90'], timeout=180)
        private_write(applied_path, revision)
    except Exception:
        for item in owned_containers(stack):
            if item['status'] == 'running' and item['id'] not in previously_running:
                docker(['stop', '--time', '45', item['id']], timeout=60)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'build', 'start', 'stop', 'status', 'probe'])
    args = parser.parse_args()
    try:
        stack = load(ROOT)
        if args.action in {'prepare', 'start', 'build', 'probe'}:
            from app.core.config import local_config
            stack = prepare(ROOT, local_config())
        if stack is None:
            print('Worker stack: stopped (not initialized).')
            return 0
        if args.action == 'prepare':
            print('Private runtime-only configuration prepared.')
        elif args.action == 'build':
            ensure_docker()
            compose(stack, ['build', 'worker'], timeout=1200)
            print('Linux Worker image built.')
        elif args.action == 'start':
            start(stack)
            print('Worker, dispatcher and broker are ready.')
        elif args.action == 'stop':
            stop(stack)
            print('Project Worker services stopped; broker volume retained.')
        elif args.action == 'probe':
            ensure_docker()
            print(compose(stack, ['run', '--rm', '--no-deps', 'worker', 'python', '/app/runtime_probe.py'], timeout=40).strip())
        else:
            services = owned_containers(stack)
            if not services:
                print('Worker stack: stopped (no project containers).')
            for service in services:
                print(f"{service['service']}: {service['status']}, health={service['health']}")
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError, subprocess.SubprocessError):
        print('Worker stack operation failed. Check Docker Linux engine, private runtime configuration and project service status; credentials are never printed.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
