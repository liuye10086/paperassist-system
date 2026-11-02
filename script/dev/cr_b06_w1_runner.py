"""W1-only isolated writing/export controls. No scientific or external tasks."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / 'script/.runtime/client-requirements-b06-w1'
DATA_ROOT = Path('D:/PaperAssist-Runtime') / ('cr-b06-w1-' + hashlib.sha256(str(ROOT).casefold().encode()).hexdigest()[:12])
STATE = RUNTIME / 'state.json'
BIND_HOST, PORT = '127.0.0.89', 18089
WORKER_IMAGE = 'paperassist-client-b06-w1-worker:local'
BASE_IMAGE_ID = 'sha256:a0ce959026ea5a382b29409a190cc743e8464f67540a7af62bec1e88a06c3d84'
BASE_IMAGE = 'paperassist-client-b05-sub4-worker:local'
LOCAL_PDF_FALLBACK = 'sha256:8b341880cc1533d0a301e7c9ec60493aba67f1464e1efc00820db9044b15bfde'
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'script'), str(ROOT / 'script/dev')]
import worker_stack
from cr_b03_runner import configure as configure_common, port_open, source_digest


def save(path, value):
    worker_stack.private_write(Path(path), json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n')


def new_state(schema, source_schema):
    directory = DATA_ROOT / 'acceptance' / schema
    state = dict(schema=schema, source_schema=source_schema, workspace=str(ROOT),
        assets=str(directory / 'assets'), staging=str(directory / 'staging'),
        research_staging=str(directory / 'research-staging'), bio_staging=str(directory / 'bio-staging'),
        bind_host=BIND_HOST, port=PORT, url=f'http://{BIND_HOST}:{PORT}',
        stack_project='pa-test-' + schema[8:], status='preparing', clone_status='preparing',
        public_database_modified=False, real_model_calls=0, scientific_tasks_authorized=False)
    return validate_state(state)


def validate_state(state):
    if any(not re.fullmatch(r'pa_test_[a-f0-9]{32}', state.get(k, '')) for k in ('schema', 'source_schema')):
        raise ValueError('Explicit isolated source and target required')
    if state['schema'] == state['source_schema']:
        raise ValueError('Accepted source cannot be the target')
    directory = DATA_ROOT / 'acceptance' / state['schema']
    expected = dict(workspace=str(ROOT), assets=str(directory / 'assets'), staging=str(directory / 'staging'),
        research_staging=str(directory / 'research-staging'), bio_staging=str(directory / 'bio-staging'),
        bind_host=BIND_HOST, port=PORT, url=f'http://{BIND_HOST}:{PORT}',
        stack_project='pa-test-' + state['schema'][8:], public_database_modified=False,
        scientific_tasks_authorized=False)
    if any(state.get(k) != v for k, v in expected.items()):
        raise ValueError('W1 ownership or execution scope differs')
    return state


def read_state():
    return validate_state(json.loads(STATE.read_text(encoding='utf-8-sig')))


def configure(state):
    validate_state(state)
    configure_common(state)
    os.environ.update(PAPERASSIST_RESEARCH_STAGING_DIR=state['research_staging'],
        PAPERASSIST_BIO_STAGING_DIR=state['bio_staging'], PAPERASSIST_BIO_INSIGHTS_STAGING_DIR=state['staging'],
        PAPERASSIST_BIO_RUNTIME_MANIFEST='', PAPERASSIST_BIO_INSIGHTS_RUNTIME_MANIFEST='',
        PAPERASSIST_SINGLE_CELL_RUNTIME_MANIFEST='')


def build():
    read_state()
    if worker_stack.docker(['image', 'inspect', '--format', '{{.Id}}', BASE_IMAGE]).strip() != BASE_IMAGE_ID:
        raise ValueError('Retained base image tag changed')
    dockerfile = RUNTIME / 'Dockerfile.worker'
    worker_stack.private_write(dockerfile, 'FROM ' + BASE_IMAGE + '\nCOPY backend/app /app/app\n')
    result = worker_stack.docker(['build', '--network', 'none', '--pull=false', '-f', str(dockerfile),
        '-t', WORKER_IMAGE, str(ROOT)], timeout=600)
    worker_stack.private_write(RUNTIME / 'worker-build.txt', result)
    return dict(image=WORKER_IMAGE, base_image=BASE_IMAGE_ID, source_digest=source_digest())


def compose(stack, args, timeout=180):
    return worker_stack.docker(['compose', '--project-name', stack.project, '--file', str(ROOT / 'compose.workers.yml'),
        '--file', str(RUNTIME / 'compose.override.json'), *args], stack=stack, timeout=timeout)


def workers():
    state = read_state()
    if state['clone_status'] != 'verified':
        raise ValueError('Target copy has not been verified')
    configure(state)
    from app.core.config import local_config
    image = worker_stack.docker(['image', 'inspect', '--format', '{{.Id}}', WORKER_IMAGE]).strip()
    script = "from pathlib import Path;import hashlib;r=Path('/app/app');h=hashlib.sha256();[(h.update(p.relative_to(r).as_posix().encode()+b'\\0'+p.read_bytes()+b'\\0')) for p in sorted(r.rglob('*.py'),key=lambda p:p.relative_to(r).as_posix())];print(h.hexdigest());print(next(x.split()[1] for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:')))"
    probe_name = state['stack_project'] + '-source-probe-' + str(time.time_ns())
    probe = worker_stack.docker(['run', '--name', probe_name, '--network', 'none',
        '--read-only', '--memory', '128m', '--entrypoint', 'python', image, '-c', script]).strip().splitlines()
    if probe[0] != source_digest() or int(probe[1]) * 1024 < 4 * 1024 ** 3:
        raise ValueError('Current source or available-memory check failed')
    stack = worker_stack.prepare(ROOT, local_config(), test_id=state['schema'][8:], assets=Path(state['assets']))
    existing = worker_stack.owned_containers(stack)
    if existing and state.get('worker_image_id') != image:
        raise ValueError('Retained service image differs; inspect before replacing a generation')
    source = json.loads((ROOT / 'script/.runtime/client-requirements-b04/state.json').read_text(encoding='utf-8-sig'))
    declared_pdf_image = source['pdf_image_id']
    try:
        worker_stack.docker(['image', 'inspect', '--format', '{{.Id}}', declared_pdf_image])
        pdf_image = declared_pdf_image
        pdf_provenance = dict(kind='retained_exact', image=pdf_image)
    except RuntimeError:
        # The exact B04 digest is no longer present locally. Reuse the retained
        # local renderer image used by the earlier offline PDF checks, but keep
        # the mismatch explicit rather than silently claiming exact identity.
        worker_stack.docker(['image', 'inspect', '--format', '{{.Id}}', LOCAL_PDF_FALLBACK])
        pdf_image = LOCAL_PDF_FALLBACK
        pdf_provenance = dict(kind='local_fallback', declared=declared_pdf_image, image=pdf_image,
            limitation='B04 exact renderer digest unavailable in current Docker image store')
    env = dict(PAPERASSIST_RESEARCH_STAGING_DIR='/research-staging', PAPERASSIST_WRITING_LIVE_ENABLED='0',
        PAPERASSIST_PLOT_WORKER_ENABLED='0', PAPERASSIST_NCBI_ENABLED='0')
    config = dict(services={name: dict(image=image, environment=env,
        volumes=[dict(type='bind', source=state['research_staging'], target='/research-staging')],
        **(dict(mem_limit='4g', cpus=1, pids_limit=64) if name == 'worker' else {})) for name in ('worker', 'dispatcher')})
    config['services']['pdf-renderer'] = dict(image=pdf_image)
    # Fixed small subnets avoid exhausting the retained historical default pools.
    import ipaddress
    networks = [json.loads(worker_stack.docker(['network', 'inspect', n]))[0]
        for n in worker_stack.docker(['network', 'ls', '-q']).splitlines()]
    selected = {'default': ('10.246.99.0/28', False), 'pdf-internal': ('10.246.100.0/28', True)}
    for key, (subnet, _) in selected.items():
        desired = ipaddress.ip_network(subnet)
        for network in networks:
            if network['Name'] == stack.project + '_' + key:
                continue
            for item in network['IPAM'].get('Config') or []:
                value = item.get('Subnet')
                if value and ':' not in value and desired.overlaps(ipaddress.ip_network(value)):
                    raise ValueError('W1 proposed subnet overlaps retained Docker network')
    config['networks'] = {key: dict(driver='bridge', internal=internal,
        ipam=dict(config=[dict(subnet=subnet)])) for key, (subnet, internal) in selected.items()}
    save(RUNTIME / 'networks-before.json', networks)
    save(RUNTIME / 'compose.override.json', config)
    compose(stack, ['config', '--quiet'])
    compose(stack, ['up', '-d', '--no-build', '--wait', '--wait-timeout', '120'])
    state.update(worker_image_id=image, worker_source_digest=probe[0], pdf_image_id=pdf_image,
        docker_available_before_start=int(probe[1]) * 1024, status='services_running')
    save(STATE, state)
    value = dict(containers=worker_stack.owned_containers(stack), source_digest=probe[0], real_model_calls=0,
        scientific_probes_run=False, source_probe_container=probe_name,
        dependencies_reused_from=BASE_IMAGE_ID, pdf_renderer=pdf_provenance)
    save(RUNTIME / 'worker-runtime.json', value)
    return value


def serve():
    state = read_state(); configure(state)
    import uvicorn
    from fastapi.staticfiles import StaticFiles
    from app.main import app
    app.mount('/', StaticFiles(directory=RUNTIME / 'frontend-dist', html=True), name='cr-b06-w1')
    uvicorn.run(app, host=BIND_HOST, port=PORT, log_level='warning')


def start_api():
    state = read_state()
    if port_open(state):
        raise ValueError('W1 port occupied; no process changed')
    if not (RUNTIME / 'frontend-dist/index.html').is_file():
        raise ValueError('Build the exact W1 frontend first')
    with (RUNTIME / 'api.stdout.txt').open('ab') as out, (RUNTIME / 'api.stderr.txt').open('ab') as err:
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'serve'], cwd=ROOT / 'backend',
            stdout=out, stderr=err, stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    save(RUNTIME / 'api-process.json', dict(pid=child.pid, executable=sys.executable, script=str(Path(__file__).resolve()),
        workspace=str(ROOT), port=PORT, source_digest=source_digest()))
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(80):
        try:
            with opener.open(state['url'] + '/api/v1/health', timeout=.5) as response:
                if response.status == 200:
                    return dict(api='ready', url=state['url'], pid=child.pid)
        except OSError:
            pass
        if child.poll() is not None:
            raise RuntimeError('API exited; inspect retained stderr')
        time.sleep(.25)
    raise RuntimeError('API startup observation timed out; process receipt retained')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['state', 'prepare', 'build', 'workers', 'start-api', 'serve'])
    args = parser.parse_args()
    if args.action == 'serve':
        serve(); return
    if args.action == 'prepare':
        from cr_b06_w1_prepare import prepare
        value = prepare()
        result = {k: value[k] for k in ('schema', 'clone_status', 'migration_head')}
    else:
        result = {'state': read_state, 'build': build, 'workers': workers, 'start-api': start_api}[args.action]()
    print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()
