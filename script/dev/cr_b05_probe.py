"""Actual B05 image probes; retain logs, old gates and probe containers."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from uuid import uuid4

import cr_b05_runner as control


def save(path, value):
    control.worker_stack.private_write(path, json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def quantitative_checks(report,code_digest,environment_digest,parent):
    expected=dict(quantitative_continuous=True,quantitative_counts=True,quantitative_sample_figure=True)
    runtime=report.get('runtime_identity',{})
    if (report.get('code_digest')!=code_digest or runtime.get('code_digest')!=code_digest
            or runtime.get('environment_digest')!=environment_digest or report.get('checks')!=expected
            or sorted(report.get('sample_figure_types',[]))!=['distribution','heatmap']):
        raise ValueError('Quantitative code, environment or actual scientific checks differ')
    if (parent.get('parent_validation') is not True or parent.get('checks')!=expected
            or sorted(parent.get('sample_figure_types',[]))!=['distribution','heatmap']
            or sorted(parent.get('validated_names',[]))!=['bulk_counts-comparison','continuous-comparison','sample-distribution','sample-heatmap']):
        raise ValueError('Actual base-interpreter validation must cover both comparisons and both sample figures')
    return expected


def image_identity(image):
    code = """from pathlib import Path
import hashlib,json
from app.domain.bioinformatics.analysis_settings import engine_code_digest,engine_lock_digest
r=Path('/app/app');h=hashlib.sha256()
for p in sorted(r.rglob('*.py'),key=lambda p:p.relative_to(r).as_posix()):
 h.update(p.relative_to(r).as_posix().encode()+b'\\0'+p.read_bytes()+b'\\0')
print(json.dumps(dict(source_digest=h.hexdigest(),bio_code_digest=engine_code_digest(),bio_lock_digest=engine_lock_digest())))
"""
    actual = json.loads(control.worker_stack.docker(['run', '--rm', '--network', 'none', '--read-only',
        '--memory', '128m', '--entrypoint', 'python', image, '-c', code]))
    from app.domain.bioinformatics.analysis_settings import engine_code_digest, engine_lock_digest
    if actual != dict(source_digest=control.source_digest(), bio_code_digest=engine_code_digest(), bio_lock_digest=engine_lock_digest()):
        raise ValueError('Probe image source or lock differs from current checkout')
    return actual


def visium_gate(report, image, identity):
    if (report.get('status') != 'passed' or report.get('h5_roundtrip') is not True
            or report.get('isolation') != {'network': 'denied', 'file': 'denied', 'fork': 'denied'}
            or report.get('numeric_threads') != 1 or report.get('warm_threads') != 1
            or not 0 < report.get('peak_rss_kib', 0) < 2 * 1024**2
            or report.get('png_bytes', 0) <= 0 or report.get('pdf_bytes', 0) <= 0
            or report.get('lock_sha256') != identity['bio_lock_digest']):
        raise ValueError('Incomplete actual Visium probe evidence')
    environment = {key: report[key] for key in ('python', 'packages', 'hdf5_version', 'native_libraries',
        'libgomp_sha256', 'blas_config', 'font_sha256', 'lock_sha256', 'numba_threading_layer')}
    digest = hashlib.sha256(json.dumps(environment, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    gate = dict(schema_version=1, gate_status='passed', engine_version='visium_explore_v1.0.0',
        environment_digest=digest, code_digest=identity['bio_code_digest'], lock_sha256=identity['bio_lock_digest'],
        image_digest=image, platform='linux/amd64', checks=dict(numeric=True, isolation=True, hdf5=True, plots=True),
        verified_at=datetime.now(timezone.utc).isoformat())
    return gate, environment


def run(kind):
    control.configure(control.read_state())
    image = control.worker_stack.docker(['image', 'inspect', '--format', '{{.Id}}', control.WORKER_IMAGE]).strip()
    identity = image_identity(image)
    available=int(control.worker_stack.docker(['run','--rm','--network','none','--read-only','--memory','64m',
        '--entrypoint','python',image,'-c',"from pathlib import Path;print(next(x.split()[1] for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:')))"]).strip())*1024
    if available<4*1024**3:raise ValueError('Docker available memory below approved 4GiB gate')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8]
    directory = control.RUNTIME / 'tasks' / ('probe-' + kind + '-' + stamp)
    directory.mkdir(parents=True, exist_ok=False)
    control.worker_stack.protect_directory(directory)
    name = 'pa-b05-probe-' + kind + '-' + stamp.lower()
    interpreter, module, gate_path = (
        ('/opt/paperassist-bio/bin/python', 'app.adapters.bio_engine.runtime_probe', control.BIO_GATE)
        if kind == 'visium' else
        ('/opt/paperassist-bio-insights/bin/python', 'app.adapters.bio_insights_engine.runtime_probe', control.GATE))
    command = ['docker', 'run', '--name', name, '--network', 'none', '--read-only', '--memory', '2g',
        '--cpus', '1', '--pids-limit', '64', '--tmpfs', '/tmp:rw,size=1g', '--entrypoint', interpreter,
        image, '-m', module]
    save(directory / 'request.json', dict(kind=kind, container=name, image=image, identity=identity, command=command))
    with (directory / 'stdout.json').open('wb') as out, (directory / 'stderr.txt').open('wb') as err:
        try:
            result = subprocess.run(command, cwd=control.ROOT, stdout=out, stderr=err, timeout=360)
        except subprocess.TimeoutExpired:
            # Stop only the uniquely named container created by this invocation; retain it and all evidence.
            control.worker_stack.docker(['stop', '--time', '10', name], timeout=30)
            raise RuntimeError('Probe timed out; named container and logs retained at ' + str(directory)) from None
    save(directory / 'completion.json', dict(exit_code=result.returncode, container_retained=True))
    if result.returncode:
        raise RuntimeError('Actual runtime probe failed; evidence retained at ' + str(directory))
    report = json.loads((directory / 'stdout.json').read_bytes())
    if report.get('status') != 'passed':
        raise ValueError('Probe did not pass')
    if kind == 'visium':
        report, environment = visium_gate(report, image, identity)
        save(directory / 'environment.json', environment)
    else:
        child_directory = directory / 'tabular'
        child_directory.mkdir()
        tabular_name = name + '-child'
        tabular_command = ['docker', 'run', '--name', tabular_name, '--network', 'none', '--read-only',
            '--memory', '4g', '--cpus', '1', '--pids-limit', '64', '--tmpfs', '/tmp:rw,size=1g',
            '--mount', 'type=bind,source=' + str(child_directory) + ',target=/probe',
            '--entrypoint', interpreter, image, '-m', 'app.adapters.bio_engine.tabular_probe', '/probe/work']
        save(directory / 'tabular-request.json', dict(container=tabular_name, command=tabular_command))
        with (directory / 'tabular-stdout.json').open('wb') as out, (directory / 'tabular-stderr.txt').open('wb') as err:
            try:
                tabular_result = subprocess.run(tabular_command, cwd=control.ROOT, stdout=out, stderr=err, timeout=360)
            except subprocess.TimeoutExpired:
                control.worker_stack.docker(['stop', '--time', '10', tabular_name], timeout=30)
                raise RuntimeError('Tabular child gate timed out; evidence and container retained') from None
        save(directory / 'tabular-completion.json', dict(exit_code=tabular_result.returncode, container_retained=True))
        if tabular_result.returncode:
            raise RuntimeError('Actual tabular child gate failed; evidence retained at ' + str(directory))
        tabular = json.loads((directory / 'tabular-stdout.json').read_bytes())
        from app.domain.bioinformatics.tabular_settings import engine_code_digest
        environment = {key: report[key] for key in ('python', 'packages', 'native_libraries', 'lock_sha256', 'limits')}
        environment_digest = hashlib.sha256(json.dumps(environment, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if (tabular.get('tabular_code_digest') != engine_code_digest()
                or tabular.get('checks') != {'tabular_import': True, 'tabular_compute': True}
                or tabular.get('runtime_identity', {}).get('environment_digest') != environment_digest):
            raise ValueError('Tabular actual code or scientific environment differs from the model gate')
        report['checks'].update(tabular['checks'])
        report['tabular_code_digest'] = tabular['tabular_code_digest']
        report['tabular_probe_evidence'] = str(directory / 'tabular-stdout.json')
        quantitative_directory=directory/'quantitative';quantitative_directory.mkdir()
        quantitative_name=name+'-quantitative'
        quantitative_command=['docker','run','--name',quantitative_name,'--network','none','--read-only',
            '--memory','4g','--cpus','1','--pids-limit','64','--tmpfs','/tmp:rw,size=1g',
            '--mount','type=bind,source='+str(quantitative_directory)+',target=/probe',
            '--entrypoint',interpreter,image,'-m','app.adapters.bio_insights_engine.quantitative_probe','/probe/work']
        save(directory/'quantitative-request.json',dict(container=quantitative_name,command=quantitative_command))
        with (directory/'quantitative-stdout.json').open('wb') as out,(directory/'quantitative-stderr.txt').open('wb') as err:
            try:quantitative_result=subprocess.run(quantitative_command,cwd=control.ROOT,stdout=out,stderr=err,timeout=360)
            except subprocess.TimeoutExpired:
                control.worker_stack.docker(['stop','--time','10',quantitative_name],timeout=30)
                raise RuntimeError('Quantitative child gate timed out; evidence and container retained') from None
        save(directory/'quantitative-completion.json',dict(exit_code=quantitative_result.returncode,container_retained=True))
        if quantitative_result.returncode:raise RuntimeError('Actual quantitative child gate failed; evidence retained at '+str(directory))
        quantitative=json.loads((directory/'quantitative-stdout.json').read_bytes())
        parent_name=quantitative_name+'-parent'
        parent_command=['docker','run','--name',parent_name,'--network','none','--read-only','--memory','2g','--cpus','1','--pids-limit','64',
            '--tmpfs','/tmp:rw,size=256m','--mount','type=bind,source='+str(quantitative_directory)+',target=/probe,readonly',
            '-e','OMP_NUM_THREADS=1','-e','OPENBLAS_NUM_THREADS=1','-e','MKL_NUM_THREADS=1',
            '--entrypoint','python',image,'-B','-m','app.adapters.bio_insights_engine.quantitative_probe','--validate-parent','/probe/work']
        save(directory/'quantitative-parent-request.json',dict(container=parent_name,command=parent_command))
        with (directory/'quantitative-parent-stdout.json').open('wb') as out,(directory/'quantitative-parent-stderr.txt').open('wb') as err:
            try:parent_result=subprocess.run(parent_command,cwd=control.ROOT,stdout=out,stderr=err,timeout=360)
            except subprocess.TimeoutExpired:
                control.worker_stack.docker(['stop','--time','10',parent_name],timeout=30)
                raise RuntimeError('Actual base-parent validation timed out; exact container retained') from None
        save(directory/'quantitative-parent-completion.json',dict(exit_code=parent_result.returncode,container_retained=True))
        if parent_result.returncode:raise RuntimeError('Actual base-parent validation failed; evidence retained at '+str(directory))
        parent=json.loads((directory/'quantitative-parent-stdout.json').read_bytes())
        report['checks'].update(quantitative_checks(quantitative,report['code_digest'],environment_digest,parent))
        report['quantitative_probe_evidence']=str(directory/'quantitative-stdout.json')
        report['quantitative_parent_evidence']=str(directory/'quantitative-parent-stdout.json')
        report['image_digest'] = image
    # A concurrent source edit cannot turn an older image probe into new-code evidence.
    image_identity(image)
    if gate_path.exists():
        history = control.RUNTIME / 'gate-history'
        history.mkdir(exist_ok=True)
        control.worker_stack.private_write(history / (kind + '-' + stamp + '.json'), gate_path.read_text(encoding='utf-8'))
    save(gate_path, report)
    if kind == 'visium':
        from app.domain.bioinformatics.analysis_settings import runtime_identity
        available = runtime_identity().get('available')
    else:
        available = control.probe().get('available')
    if not available:
        raise ValueError('Actual image proof does not match current host engine; evidence retained')
    return dict(kind=kind, available=True, image=image, evidence=str(directory), container=name)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=['visium', 'tabular'])
    print(json.dumps(run(parser.parse_args().kind), ensure_ascii=False))
