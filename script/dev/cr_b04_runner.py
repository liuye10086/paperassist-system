"""Explicit CR-B04 acceptance controls. Stop never removes retained objects."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / 'script/.runtime/client-requirements-b04'
STATE = RUNTIME / 'state.json'
GATE = RUNTIME / 'runtime-gate.json'
WORKER_IMAGE = 'paperassist-client-b04-worker:local'
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'script/dev')]
import worker_stack


def new_state(schema, source_schema):
    directory = RUNTIME / 'acceptance' / schema
    return validate_state(dict(schema=schema, source_schema=source_schema, workspace=str(ROOT),
        assets=str(directory / 'assets'), staging=str(directory / 'staging'),
        research_staging=str(directory / 'research-staging'), bio_staging=str(directory / 'bio-staging'),
        runtime_manifest=str(GATE), worker_image=WORKER_IMAGE, bind_host='127.0.0.84', port=18084,
        url='http://127.0.0.84:18084', stack_project='pa-test-' + schema.removeprefix('pa_test_'),
        status='preparing', clone_status='preparing', public_database_modified=False, real_model_calls=0))


def validate_state(state):
    if not isinstance(state, dict) or any(not re.fullmatch(r'pa_test_[a-f0-9]{32}', state.get(k, '')) for k in ('schema', 'source_schema')):
        raise ValueError('Explicit isolated source and target schemas required')
    if state['schema'] == state['source_schema']:
        raise ValueError('Source schema cannot be reused')
    directory = RUNTIME / 'acceptance' / state['schema']
    expected = dict(workspace=str(ROOT), assets=str(directory / 'assets'), staging=str(directory / 'staging'),
        research_staging=str(directory / 'research-staging'), bio_staging=str(directory / 'bio-staging'),
        runtime_manifest=str(GATE), worker_image=WORKER_IMAGE, bind_host='127.0.0.84', port=18084,
        url='http://127.0.0.84:18084', stack_project='pa-test-' + state['schema'][8:])
    if (any(state.get(k) != v for k, v in expected.items()) or type(state.get('port')) is not int
            or state.get('public_database_modified') is not False):
        raise ValueError('Batch schema, endpoint, image or path ownership differs')
    return state


def read_state():
    return validate_state(json.loads(STATE.read_text(encoding='utf-8-sig')))


def configure(state):
    validate_state(state)
    os.environ.update(PAPERASSIST_ENV='test', PAPERASSIST_DB_SCHEMA=state['schema'],
        PAPERASSIST_DATA_DIR=state['assets'], PAPERASSIST_BIO_INSIGHTS_STAGING_DIR=state['staging'],
        PAPERASSIST_BIO_INSIGHTS_RUNTIME_MANIFEST=str(GATE),
        PAPERASSIST_RESEARCH_STAGING_DIR=state['research_staging'], PAPERASSIST_BIO_STAGING_DIR=state['bio_staging'],
        PAPERASSIST_BIO_RUNTIME_MANIFEST=str(ROOT / 'script/.runtime/client-requirements-b02/runtime-gate.json'),
        PAPERASSIST_PLOT_WORKER_ENABLED='0', PAPERASSIST_NCBI_ENABLED='0', PAPERASSIST_NCBI_CONFIG_FILE='',
        PAPERASSIST_NCBI_API_KEY='', PAPERASSIST_NCBI_EMAIL='', PAPERASSIST_WRITING_LIVE_ENABLED='0',
        OPENAI_API_KEY='', OPENAI_API_KEY_FILE='', PAPERASSIST_AUTH_TRUSTED_ORIGINS=state['url'],
        PAPERASSIST_AUTH_IDLE_SECONDS='86400', PAPERASSIST_AUTH_ABSOLUTE_SECONDS='604800',
        PAPERASSIST_EXPLANATION_POLICY_FILE='', PAPERASSIST_PLOT_POLICY_FILE='',
        PAPERASSIST_ANALYSIS_RECOMMENDATION_POLICY_FILE='')


def source_digest():
    source = ROOT / 'backend/app'
    result = hashlib.sha256()
    for path in sorted(source.rglob('*.py'), key=lambda p: p.relative_to(source).as_posix()):
        result.update(path.relative_to(source).as_posix().encode() + b'\0' + path.read_bytes() + b'\0')
    return result.hexdigest()


def port_open(state):
    validate_state(state)
    with socket.socket() as connection:
        connection.settimeout(.2)
        return connection.connect_ex((state['bind_host'], state['port'])) == 0


def compose(stack, args, timeout=300):
    return worker_stack.docker(['compose', '--project-name', stack.project, '--file', str(ROOT / 'compose.workers.yml'),
        '--file', str(RUNTIME / 'compose.override.json'), *args], stack=stack, timeout=timeout)


def build():
    read_state()
    dockerfile = RUNTIME / 'Dockerfile.worker'
    if not dockerfile.is_file():
        raise ValueError('B04 environment Dockerfile is not prepared')
    worker_stack.docker(['build', '--network', 'none', '--pull=false', '--build-context',
        'b04_wheels=' + str(RUNTIME / 'wheels'), '-f', str(dockerfile), '-t', WORKER_IMAGE, str(ROOT)], timeout=1800)
    return {'image': WORKER_IMAGE, 'source_digest': source_digest()}


def probe():
    state = read_state()
    configure(state)
    if not GATE.is_file():
        return {'available': False, 'reason': 'bio_insights_environment_unavailable'}
    from app.domain.bio_insights.settings import runtime_identity
    return runtime_identity()


def workers():
    state = read_state()
    if state['clone_status'] != 'verified':
        raise ValueError('The B04 copy has not been verified')
    configure(state)
    if not probe().get('available'):
        raise ValueError('The isolated B04 science environment has not been verified')
    image_id = worker_stack.docker(['image', 'inspect', '--format', '{{.Id}}', WORKER_IMAGE]).strip()
    check = "from pathlib import Path;import hashlib;r=Path('/app/app');h=hashlib.sha256();[(h.update(p.relative_to(r).as_posix().encode()+b'\\0'+p.read_bytes()+b'\\0')) for p in sorted(r.rglob('*.py'),key=lambda p:p.relative_to(r).as_posix())];print(h.hexdigest())"
    actual = worker_stack.docker(['run', '--rm', '--network', 'none', '--read-only', '--memory', '128m',
                                 '--entrypoint', 'python', image_id, '-c', check]).strip()
    if actual != source_digest():
        raise ValueError('Worker source differs; refresh the owned image before starting')
    available = int(worker_stack.docker(['run', '--rm', '--network', 'none', '--read-only', '--memory', '64m',
        '--entrypoint', 'python', image_id, '-c', "from pathlib import Path;print(next(x.split()[1] for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:')))" ]).strip()) * 1024
    if available < 4 * 1024 ** 3:
        raise ValueError('Docker available memory below approved 4GiB gate')
    from app.core.config import local_config
    stack = worker_stack.prepare(ROOT, local_config(), test_id=state['schema'][8:], assets=Path(state['assets']))
    worker_stack.owned_containers(stack)
    paths = [('staging', '/insights-staging'), ('research_staging', '/research-staging'), ('bio_staging', '/bio-staging')]
    for key, _ in paths:
        Path(state[key]).mkdir(exist_ok=True)
    env = {'PAPERASSIST_BIO_INSIGHTS_STAGING_DIR': '/insights-staging',
        'PAPERASSIST_BIO_INSIGHTS_RUNTIME_MANIFEST': '/run/paperassist/bio-insights-runtime.json',
        'PAPERASSIST_RESEARCH_STAGING_DIR': '/research-staging', 'PAPERASSIST_BIO_STAGING_DIR': '/bio-staging',
        'PAPERASSIST_BIO_RUNTIME_MANIFEST': '/run/bio-runtime.json'}
    mounts = [{'type': 'bind', 'source': state[key], 'target': target} for key, target in paths]
    mounts += [{'type': 'bind', 'source': str(GATE), 'target': env['PAPERASSIST_BIO_INSIGHTS_RUNTIME_MANIFEST'], 'read_only': True},
        {'type': 'bind', 'source': os.environ['PAPERASSIST_BIO_RUNTIME_MANIFEST'], 'target': '/run/bio-runtime.json', 'read_only': True}]
    config = {'services': {name: {'image': image_id, 'environment': env, 'volumes': mounts,
        **({'mem_limit': '4g', 'cpus': 1, 'pids_limit': 64} if name == 'worker' else {})} for name in ['worker', 'dispatcher']}}
    source = json.loads((ROOT / 'script/.runtime/client-requirements-b03/state.json').read_text(encoding='utf-8'))
    pdf_image = source['pdf_image_id']
    worker_stack.docker(['image', 'inspect', '--format', '{{.Id}}', pdf_image])
    config['services']['pdf-renderer'] = {'image': pdf_image}
    worker_stack.private_write(RUNTIME / 'compose.override.json', json.dumps(config, indent=2))
    compose(stack, ['config', '--quiet'])
    compose(stack, ['up', '-d', '--no-build', '--wait', '--wait-timeout', '180'])
    state.update(status='services_running', worker_image_id=image_id, worker_source_digest=actual,
                 pdf_image_id=pdf_image, docker_available_before_start=available)
    worker_stack.private_write(STATE, json.dumps(state, ensure_ascii=False, indent=2))
    return {'containers': worker_stack.owned_containers(stack), 'source_digest': actual}


def stop_workers():
    state = validate_state(read_state())
    stack = worker_stack.load(ROOT, test_id=state['schema'][8:])
    if stack is None:
        return {'containers': [], 'status': 'not_initialized'}
    worker_stack.stop(stack)
    return {'containers': worker_stack.owned_containers(stack), 'retained': True}


def serve():
    state = read_state()
    configure(state)
    import uvicorn
    from fastapi.staticfiles import StaticFiles
    from app.main import app
    app.mount('/', StaticFiles(directory=ROOT / 'frontend/dist', html=True), name='cr-b04-acceptance')
    uvicorn.run(app, host=state['bind_host'], port=state['port'], log_level='warning')


def start_api():
    state = read_state()
    if state['clone_status'] != 'verified' or port_open(state):
        raise ValueError('Batch copy is unverified or port occupied')
    directory = Path(state['assets']).parent
    receipt = directory / 'api-process.json'
    if receipt.exists():
        history = directory / 'api-process-history'
        history.mkdir(exist_ok=True)
        worker_stack.private_write(history / (uuid4().hex + '.json'), receipt.read_text(encoding='utf-8'))
    with (directory / 'api.stdout.log').open('ab') as out, (directory / 'api.stderr.log').open('ab') as err:
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'serve'], cwd=ROOT / 'backend',
            stdout=out, stderr=err, stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    worker_stack.private_write(receipt, json.dumps(dict(pid=child.pid, executable=sys.executable,
        script=str(Path(__file__).resolve()), workspace=str(ROOT), port=state['port'], source_digest=source_digest(),
        frontend_index_sha256=hashlib.sha256((ROOT / 'frontend/dist/index.html').read_bytes()).hexdigest()), indent=2))
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(120):
        try:
            with opener.open(state['url'] + '/api/v1/health', timeout=.5) as response:
                if response.status == 200:
                    return {'api': 'ready', 'url': state['url'], 'pid': child.pid}
        except OSError:
            pass
        if child.poll() is not None:
            raise RuntimeError('B04 API failed; inspect retained batch stderr')
        time.sleep(.25)
    raise RuntimeError('B04 API startup timed out; process receipt retained')


def stop_api():
    state = read_state()
    receipt = Path(state['assets']).parent / 'api-process.json'
    if not receipt.exists():
        return {'api': 'no_recorded_process'}
    saved = json.loads(receipt.read_text(encoding='utf-8'))
    if saved['workspace'] != str(ROOT) or saved['script'] != str(Path(__file__).resolve()) or saved['port'] != state['port']:
        raise ValueError('Foreign API receipt')
    command = """$r=[Console]::In.ReadToEnd()|ConvertFrom-Json
$p=Get-CimInstance Win32_Process -Filter ('ProcessId='+[int]$r.pid)
if ($null -eq $p) { exit 0 }
if (-not [string]::Equals($p.ExecutablePath,$r.executable,[StringComparison]::OrdinalIgnoreCase)) { throw 'API executable differs' }
if ($p.CommandLine.IndexOf($r.script,[StringComparison]::OrdinalIgnoreCase) -lt 0 -or $p.CommandLine -notmatch ' serve(?: |$)') { throw 'API command differs' }
Stop-Process -Id $p.ProcessId -ErrorAction Stop
"""
    result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', command],
                            input=json.dumps(saved).encode(), capture_output=True, timeout=15)
    if result.returncode:
        raise RuntimeError('API ownership check failed; no broad stop attempted')
    for _ in range(20):
        if not port_open(state):
            return {'api': 'stopped', 'pid': saved['pid'], 'receipt_retained': True}
        time.sleep(.1)
    raise RuntimeError('API port remains open; no other process stopped')


def main():
    actions = {'state': read_state, 'build': build, 'probe': probe, 'workers': workers,
               'start-api': start_api, 'stop-api': stop_api, 'stop-workers': stop_workers, 'serve': serve}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=actions)
    args = parser.parse_args()
    result = actions[args.action]()
    if result is not None:
        print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
