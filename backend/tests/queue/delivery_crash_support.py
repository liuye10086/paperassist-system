"""Test-only isolation guards and observable process/broker crash evidence."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time

import httpx2
from dotenv import dotenv_values

from app.core.config import get_data_dir
from app.core.paths import BACKEND_ROOT, PROJECT_ROOT
from app.db.database import database_connection, get_database_config


def require_isolated_test(*, queue=False):
    config = get_database_config()
    if (os.environ.get('PAPERASSIST_RUN_QUEUE_TESTS') != '1'
            or config.environment != 'test'
            or config.url.database != 'paperassist_system_test'
            or config.url.username != 'paperassist_test_runtime'
            or config.url.host not in ({'host.docker.internal'} if queue else {'localhost', '127.0.0.1', '::1'})
            or not re.fullmatch(r'pa_test_[0-9a-f]{32}', config.schema)):
        raise SystemExit('Crash drill requires the dedicated UUID-scoped test database.')
    configured = os.environ.get('PAPERASSIST_DATA_DIR', '')
    assets = get_data_dir()
    saved = dotenv_values(BACKEND_ROOT / '.env', encoding='utf-8-sig', interpolate=False)
    development_assets = (BACKEND_ROOT / Path(saved.get('PAPERASSIST_DATA_DIR') or 'data')).resolve()
    if (not configured or not Path(configured).is_absolute()
            or any(assets == target or target in assets.parents
                   for target in ((BACKEND_ROOT / 'data').resolve(), development_assets))):
        raise SystemExit('Crash drill must use explicitly isolated temporary assets.')
    if queue and (os.environ.get('PAPERASSIST_QUEUE_TEST_ALLOWED') != '1'
                  or os.environ.get('PAPERASSIST_TASK_QUEUE') != 'paperassist.test.' + config.schema[8:]):
        raise SystemExit('Crash drill requires its exact isolated test queue.')
    with database_connection() as db:
        row = db.execute('SELECT current_database() AS database,current_user AS role,session_user AS session').fetchone()
        if (row['database'], row['role'], row['session']) != (
                'paperassist_system_test', 'paperassist_test_runtime', 'paperassist_test_runtime'):
            raise SystemExit('Crash drill database identity mismatch.')
    return config, assets


def durable_marker(path, data):
    path = Path(path)
    temporary = path.with_name(path.name + '.writing')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(data, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def wait_until(read, accept, *, seconds=30, description):
    deadline = time.monotonic() + seconds
    last = None
    while time.monotonic() < deadline:
        last = read()
        if accept(last):
            return last
        time.sleep(0.2)
    raise AssertionError(f'{description} did not become ready: {last}')


def evidence(checkpoint, **values):
    print('DELIVERY_CRASH_EVIDENCE ' + json.dumps({'checkpoint': checkpoint, **values}, sort_keys=True), flush=True)


@contextmanager
def crashing_api(request_key):
    config, assets = require_isolated_test()
    address = assets / '.test-api-address.json'
    env = {**os.environ,
           'PAPERASSIST_TEST_DATABASE_URL': config.url.render_as_string(hide_password=False),
           'PAPERASSIST_TEST_API_ADDRESS_FILE': str(address),
           'PAPERASSIST_CRASH_REQUEST_KEY': request_key,
           'PAPERASSIST_PLOT_WORKER_ENABLED': '0',
           'OPENAI_API_KEY': '', 'OPENAI_API_KEY_FILE': '',
           'PAPERASSIST_EXPLANATION_POLICY_FILE': '', 'PAPERASSIST_PLOT_POLICY_FILE': ''}
    stderr = (assets / '.test-api-stderr.log').open('wb')
    process = subprocess.Popen([sys.executable, str(Path(__file__).with_name('api_crash_bootstrap.py'))],
                               cwd=BACKEND_ROOT, env=env, stdout=subprocess.DEVNULL, stderr=stderr)
    info = None
    runtime_handle = None
    try:
        def read_address():
            assert process.poll() is None, 'Isolated API exited before readiness.'
            return json.loads(address.read_text(encoding='utf-8')) if address.exists() else None
        info = wait_until(read_address, bool, description='isolated API socket')
        assert info['host'] == '127.0.0.1'
        # Windows virtualenv executables are launchers; their interpreter is a child.
        assert info['pid'] == process.pid or info['parent_pid'] == process.pid
        if os.name == 'nt':
            import _winapi
            # Pin the exact owned interpreter. Exit/cleanup cannot target a reused PID.
            runtime_handle = _winapi.OpenProcess(0x00100001, False, info['pid'])
        endpoint = f"http://127.0.0.1:{info['port']}"
        with httpx2.Client(base_url=endpoint, timeout=10, trust_env=False) as transport:
            def healthy():
                assert process.poll() is None, 'Isolated API exited before health readiness.'
                try:
                    return transport.get('/api/v1/health').status_code == 200
                except httpx2.TransportError:
                    return False
            wait_until(healthy, bool, description='isolated API health')
            yield process, transport
    finally:
        runtime_stopped = None
        if runtime_handle is not None:
            import _winapi
            if _winapi.WaitForSingleObject(runtime_handle, 0) == _winapi.WAIT_TIMEOUT:
                _winapi.TerminateProcess(runtime_handle, 76)
            runtime_stopped = _winapi.WaitForSingleObject(runtime_handle, 10000) == _winapi.WAIT_OBJECT_0
            _winapi.CloseHandle(runtime_handle)
            assert runtime_stopped, 'Owned API interpreter did not stop.'
        if process.poll() is None:
            if os.name == 'nt' and runtime_handle is None:
                # Before readiness, use the existing bounded native owned-tree helper.
                cleanup_env = {**os.environ, 'PAPERASSIST_TEST_API_LAUNCHER_PID': str(process.pid),
                               'PAPERASSIST_TEST_TREE_SOURCE': str(PROJECT_ROOT / 'script' / 'dev' / 'process-tree.cs')}
                cleanup = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                    "Add-Type -Path $env:PAPERASSIST_TEST_TREE_SOURCE; "
                    "$owned = Get-Process -Id ([int]$env:PAPERASSIST_TEST_API_LAUNCHER_PID) -ErrorAction SilentlyContinue; "
                    "if ($null -ne $owned) { [PaperAssistProcessTree]::Stop($owned) }"],
                    env=cleanup_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
                assert cleanup.returncode == 0, 'Owned API launcher tree cleanup failed.'
            elif runtime_handle is None:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        port_closed = None
        if info is not None:
            with socket.socket() as probe:
                probe.settimeout(0.5)
                port_closed = probe.connect_ex((info['host'], info['port'])) != 0
            assert port_closed, 'Owned API socket still accepts connections after cleanup.'
        evidence('api_process_cleanup', launcher_pid=process.pid,
                 runtime_pid=info['pid'] if info else None, exit_code=process.returncode,
                 stopped=process.poll() is not None, runtime_stopped=runtime_stopped, port_closed=port_closed)
        stderr.close()


def queue_stats(stack, worker_stack):
    worker_stack.owned_containers(stack)
    output = worker_stack.compose(stack, ['exec', '-T', 'rabbitmq', 'rabbitmqctl', '-q',
        'list_queues', '-p', 'paperassist_test', 'name', 'messages_ready',
        'messages_unacknowledged', 'consumers', '--no-table-headers'], timeout=30)
    for line in output.splitlines():
        values = line.split()
        if values and values[0] == stack.environment['PAPERASSIST_TASK_QUEUE']:
            assert len(values) == 4, 'Unexpected isolated broker statistics format.'
            return dict(zip(('ready', 'unacked', 'consumers'), map(int, values[1:])))
    return None


def dispatcher_exit_code(stack, worker_stack):
    dispatchers = [item for item in worker_stack.owned_containers(stack) if item['service'] == 'dispatcher']
    assert len(dispatchers) == 1
    item = dispatchers[0]
    if item['status'] != 'exited':
        return None
    return int(worker_stack.docker(['inspect', '--format', '{{.State.ExitCode}}', item['id']], stack=stack).strip())
