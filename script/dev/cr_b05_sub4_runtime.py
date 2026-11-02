"""Run the final image inventory and only the two new isolated worker probes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from uuid import uuid4


def inventory():
    for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMBA_NUM_THREADS',
                'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'BLIS_NUM_THREADS', 'RAYON_NUM_THREADS'):
        os.environ[key] = '1'
    os.environ.update(MPLBACKEND='Agg', MPLCONFIGDIR='/tmp/sub4-mpl', XDG_CACHE_HOME='/tmp/sub4-cache')
    import importlib
    import importlib.metadata
    from app.adapters.bio_insights_engine.worker import actual_identity, warm_render_environment
    # Trusted imports match the new workers; no accepted model exercise is run.
    for name in ('feature_extract', 'feature_figures', 'integration', 'integration_figures'):
        importlib.import_module('app.adapters.bio_insights_engine.' + name)
    with tempfile.TemporaryDirectory(prefix='sub4-inventory-') as warm:
        warm_render_environment(Path(warm))
    runtime = actual_identity()
    from threadpoolctl import threadpool_info
    from app.domain.bio_insights.settings import BioInsightsLimits, engine_lock_digest
    libraries = sorted(threadpool_info(), key=lambda item: item['filepath'])
    for library in libraries:
        library['sha256'] = hashlib.sha256(Path(library['filepath']).read_bytes()).hexdigest()
        if library['num_threads'] != 1:
            raise ValueError('Unexpected native thread count')
    return dict(runtime_identity=runtime, python=sys.version,
        packages={dist.metadata['Name'].lower().replace('_', '-'): dist.version for dist in importlib.metadata.distributions()},
        native_libraries=libraries, lock_sha256=engine_lock_digest(), limits=BioInsightsLimits().model_dump(),
        numeric_threads=1, validation_scope='final image imports/inventory; accepted scientific fits not executed')


def run(kind):
    os.environ['PAPERASSIST_CR_B05_SUBPACKAGE'] = '4'
    import cr_b05_runner as control
    from cr_b05_probe import image_identity, save
    state = control.read_state()
    control.configure(state)
    image = control.worker_stack.docker(['image', 'inspect', '--format', '{{.Id}}', control.WORKER_IMAGE]).strip()
    identity = image_identity(image)
    root = control.RUNTIME / 'probes'
    root.mkdir(exist_ok=True)
    completed = root / (kind + '-completed.json')
    if completed.exists():
        previous = json.loads(completed.read_bytes())
        if previous['image'] == image and previous['identity'] == identity:
            return {**previous, 'existing_evidence_reused': True}
        raise ValueError('Completed probe has another image; assess the exact changed scope before rerunning')
    directory = root / (kind + '-' + uuid4().hex)
    directory.mkdir()
    interpreter = '/opt/paperassist-bio-insights/bin/python'
    common = ['docker', 'run', '--network', 'none', '--read-only', '--memory', '4g', '--cpus', '1',
        '--pids-limit', '64', '--tmpfs', '/tmp:rw,size=1g',
        '--mount', 'type=bind,source=' + str(directory) + ',target=/probe']

    def execute(label, entry, arguments, mounts=()):
        name = 'pa-b05-sub4-' + kind + '-' + label + '-' + uuid4().hex[:12]
        command = common + list(mounts) + ['--name', name, '--entrypoint', entry, image, '-B', *arguments]
        save(directory / (label + '-request.json'), dict(command=command, image=image, identity=identity))
        with (directory / (label + '-stdout.json')).open('wb') as out, (directory / (label + '-stderr.txt')).open('wb') as err:
            try:
                result = subprocess.run(command, cwd=control.ROOT, stdout=out, stderr=err, timeout=1200)
            except subprocess.TimeoutExpired:
                control.worker_stack.docker(['stop', '--time', '10', name], timeout=30)
                raise RuntimeError('New probe timed out; exact attempt and container retained') from None
        save(directory / (label + '-completion.json'), dict(exit_code=result.returncode, container_retained=True))
        if result.returncode:
            raise RuntimeError('New ' + kind + ' probe failed; evidence retained at ' + str(directory))
        return directory / (label + '-stdout.json')

    if kind == 'inventory':
        actual = execute('actual', interpreter, ['/tools/cr_b05_sub4_runtime.py', '--inside-inventory'],
            ['--mount', 'type=bind,source=' + str(Path(__file__).parent) + ',target=/tools,readonly'])
        paths = dict(inventory=str(actual))
    else:
        module = 'app.adapters.bio_insights_engine.' + kind + '_probe'
        child = execute('child', interpreter, ['-m', module, '/probe/work'])
        parent = execute('parent', 'python', ['-m', module, '--validate-parent', '/probe/work'])
        paths = dict(child=str(child), parent=str(parent))
    image_identity(image)
    proof = dict(status='passed', image=image, identity=identity, evidence=str(directory), **paths)
    save(completed, proof)
    return proof


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=['inventory', 'feature', 'integration'], nargs='?')
    parser.add_argument('--inside-inventory', action='store_true')
    args = parser.parse_args()
    if not args.inside_inventory and args.kind is None:
        parser.error('Choose a new probe or inventory')
    print(json.dumps(inventory() if args.inside_inventory else run(args.kind), sort_keys=True))
