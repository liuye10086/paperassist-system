"""Verify current single-cell code with the retained Linux runtime and public data.

No cloud, service restarts, PDF generation, or production database writes.
The public-data action downloads attributed CC BY 4.0 matrices only.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / 'backend'
CONTAINER_MEMORY = '3g'
EVIDENCE = ROOT / 'script/.runtime/single-cell-batches'
sys.path.insert(0, str(BACKEND))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def run(command, name, timeout=1800):
    started = time.monotonic()
    result = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=timeout)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / (name + '.stdout')).write_bytes(result.stdout)
    (EVIDENCE / (name + '.stderr')).write_bytes(result.stderr)
    write_json(EVIDENCE / (name + '.run.json'), dict(exit_code=result.returncode, wall_seconds=time.monotonic()-started))
    if result.returncode:
        raise RuntimeError(f'{name} failed; see {EVIDENCE / (name + ".stderr")}')
    return result.stdout


def container(image, *, network=False, interpreter='/usr/local/bin/python'):
    command = ['docker', 'run', '--rm', '--memory', CONTAINER_MEMORY, '--cpus', '1',
               '--mount', f'type=bind,source={BACKEND},target=/app,readonly',
               '--mount', f'type=bind,source={EVIDENCE},target=/evidence',
               '--workdir', '/app', '--env', 'PYTHONPATH=/app', '--env', 'MPLBACKEND=Agg',
               '--env', 'PAPERASSIST_BIO_RUNTIME_MANIFEST=/evidence/bio-runtime.json',
               '--env', 'PAPERASSIST_SINGLE_CELL_RUNTIME_MANIFEST=/evidence/single-cell-runtime.json']
    if not network:
        command += ['--network', 'none']
    return command + ['--entrypoint', interpreter]


def probe(image, *, qc_tools=False, integration_tools=False, annotation_tools=False):
    from app.domain.bioinformatics.analysis_settings import engine_code_digest, engine_lock_digest
    from app.adapters.bio_single_cell_validation import validate_single_cell_probe
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    image_id = subprocess.check_output(['docker', 'image', 'inspect', '--format', '{{.Id}}', image], text=True).strip()
    code_digest = engine_code_digest()
    report = json.loads(run(container(image, interpreter='/opt/paperassist-bio/bin/python') +
                            [image, '-m', 'app.adapters.bio_engine.runtime_probe'], 'numeric-probe'))
    if not (report['status'] == 'passed' and report['h5_roundtrip'] is True
            and report['isolation'] == dict(network='denied', file='denied', fork='denied')
            and report['numeric_threads'] == report['warm_threads'] == 1
            and 0 < report['peak_rss_kib'] < 2 * 1024**2 and report['png_bytes'] > 0
            and report['render_formats'] == ['png'] and report['lock_sha256'] == engine_lock_digest()):
        raise ValueError('Actual numerical runtime checks did not pass')
    environment = {key: report[key] for key in ('python', 'packages', 'hdf5_version', 'native_libraries',
        'libgomp_sha256', 'blas_config', 'font_sha256', 'lock_sha256', 'numba_threading_layer')}
    if qc_tools:
        r_probe = json.loads(run(container(image, interpreter='/opt/paperassist-bio/bin/python') +
            [image, '-c', "import os; os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1'); "
             "from app.adapters.single_cell_r.bridge import initialize; import json,tempfile,hashlib; from pathlib import Path; "
             "b=initialize(Path(tempfile.mkdtemp())); print(json.dumps(dict(versions=b.versions,"
             "explicit_spec_sha256=hashlib.sha256(Path('/opt/paperassist-single-cell-r/explicit-spec.txt').read_bytes()).hexdigest())))"], 'r-runtime-probe'))
        environment['single_cell_r'] = r_probe
        r_tests=['tests/numeric/test_single_cell_batch2_r.py']
        if integration_tools:r_tests.append('tests/numeric/test_single_cell_batch3_r.py')
        if annotation_tools:
            r_tests+=['tests/numeric/test_single_cell_batch4_singler.py','tests/numeric/test_single_cell_batch4_subset_outputs.py','tests/numeric/test_single_cell_batch4_annotation_outputs.py','tests/numeric/test_single_cell_batch4_isolation.py']
            reference=json.loads(run(container(image,interpreter='/opt/paperassist-bio/bin/python')+[image,'-c',
                "import json; from app.adapters.single_cell_r.annotation import resolve_reference; r=resolve_reference(dict(reference_id='monaco_immune_1.0.0',species='Homo sapiens',gene_id_type='ensembl_gene_id',label_level='main')); print(json.dumps({k:v for k,v in r['metadata'].items() if k!='gene_ids'}))"], 'annotation-reference-probe'))
            environment['annotation_reference']=reference
        run(container(image, interpreter='/opt/paperassist-bio/bin/python') +
            ['--env', 'OPENBLAS_NUM_THREADS=1', '--env', 'OMP_NUM_THREADS=1', '--env', 'MKL_NUM_THREADS=1',
             image, '-c', "from app.adapters.single_cell_r.bootstrap import preload_runtime_libraries; preload_runtime_libraries(); import pytest; raise SystemExit(pytest.main("+repr(['--confcutdir=/app/tests/numeric',*r_tests,'-q','--tb=short','-p','no:cacheprovider'])+"))"], 'r-model-worker-probe')
    digest = hashlib.sha256(json.dumps(environment, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    cell = json.loads(run(container(image, interpreter='/opt/paperassist-bio/bin/python') + [image, '-c',
        "from app.adapters.single_cell_r.bootstrap import preload_runtime_libraries; preload_runtime_libraries(); import json,tempfile; from app.adapters.bio_engine.single_cell_probe import exercise; "
        "print(json.dumps(exercise(tempfile.mkdtemp(prefix='sc-probe-'))))"], 'single-cell-probe'))
    validate_single_cell_probe(cell)
    run(container(image, interpreter='/opt/paperassist-bio/bin/python') + [image, '-c', "from app.adapters.single_cell_r.bootstrap import preload_runtime_libraries; preload_runtime_libraries(); import pytest; raise SystemExit(pytest.main(['--confcutdir=/app/tests/numeric','tests/numeric/test_single_cell_worker.py','-q','--tb=short','-p','no:cacheprovider']))"], 'single-cell-worker-probe')
    if code_digest != engine_code_digest():
        raise ValueError('Scientific code changed while probing; run probe again after edits finish')
    gate = dict(schema_version=1, gate_status='passed', engine_version='visium_explore_v1.0.0',
        environment_digest=digest, code_digest=code_digest, lock_sha256=engine_lock_digest(),
        image_digest=image_id, platform='linux/amd64', checks=dict(numeric=True, isolation=True, hdf5=True, plots=True),
        verified_at=datetime.now(timezone.utc).isoformat())
    write_json(EVIDENCE / 'runtime-environment.json', environment)
    write_json(EVIDENCE / 'bio-runtime.json', gate)
    write_json(EVIDENCE / 'single-cell-runtime.json', {key: gate[key] for key in
        ('schema_version', 'gate_status', 'engine_version', 'environment_digest', 'code_digest')} | {'checks':cell['checks']})
    actual = json.loads(run(container(image) + [image, '-c',
        'import json; from app.domain.bioinformatics.single_cell_settings import runtime_identity; print(json.dumps(runtime_identity()))'], 'runtime-identity'))
    if actual['available'] is not True:
        raise ValueError('Current runtime_identity did not accept the actual probe receipts')
    print(json.dumps(dict(status='passed', image=image_id, code_digest=code_digest,
        peak_rss_mib=round(report['peak_rss_kib']/1024, 1), evidence=str(EVIDENCE)), ensure_ascii=False))


def public_data():
    directory = EVIDENCE / 'public-data'
    directory.mkdir(parents=True, exist_ok=True)
    records = []
    for count in ('3', '6'):
        sample = 'pbmc' + count + 'k'
        name = sample + '_filtered_gene_bc_matrices.tar.gz'
        # Public mirror documented in 10x's Cell Ranger R Kit PBMC tutorial.
        url = f'https://s3-us-west-2.amazonaws.com/10x.files/samples/cell/{sample}/{name}'
        path = directory / name
        if not path.is_file():
            temporary = path.with_suffix('.partial')
            with urllib.request.urlopen(url, timeout=60) as response, temporary.open('wb') as stream:
                while block := response.read(1024**2):
                    stream.write(block)
            temporary.replace(path)
        records.append(dict(sample=sample, filename=name, download_url=url,
            source=f'https://www.10xgenomics.com/datasets/{count}-k-pbm-cs-from-a-healthy-donor-1-standard-1-1-0',
            license='CC BY 4.0', attribution='10x Genomics, PBMCs from a Healthy Donor, Cell Ranger 1.1.0',
            donor_relationship='pbmc3k and pbmc6k are the SAME donor according to both official dataset pages',
            species_taxon_id=9606, reference_id='hg19', reference_version=None,
            library_chemistry="10x Universal 3 prime (GemCode read structure on source page)",
            size_bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    write_json(directory / 'sources.json', records)
    print(json.dumps(records, ensure_ascii=False))


def verify(image, selection, *, qc_tools=False, integration_tools=False):
    """Use the normal application task handler and scientific child in Linux.

    The only connection is the local TEST database, with a schema owned by pytest.
    Credentials are passed through a temporary env-file and never logged.
    """
    from dotenv import dotenv_values
    from sqlalchemy.engine import make_url
    settings = {**dotenv_values(BACKEND / '.env', interpolate=False),
                **dotenv_values(BACKEND / '.env.migrations', interpolate=False), **os.environ}
    entries = []
    for key in ('PAPERASSIST_TEST_DATABASE_URL', 'PAPERASSIST_TEST_MIGRATION_DATABASE_URL'):
        url = make_url(settings[key])
        if url.database != 'paperassist_system_test' or url.host not in {'localhost', '127.0.0.1', 'host.docker.internal'}:
            raise ValueError('This verifier only uses the explicitly local paperassist_system_test database')
        entries.append(key + '=' + url.set(host='host.docker.internal').render_as_string(hide_password=False))
    handle, env_path = tempfile.mkstemp(prefix='paperassist-sc-test-', suffix='.env')
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            stream.write('\n'.join(entries) + '\n')
        command = container(image, network=True)
        command += ['--env-file', env_path, '--env', 'PAPERASSIST_SC_PUBLIC_DATA=/evidence/public-data',
                    '--env', 'PAPERASSIST_SC_PUBLIC_EVIDENCE=/evidence/'+('batch3-real-matrix' if integration_tools else 'batch2-real-matrix' if qc_tools else 'real-matrix')]
        if integration_tools:
            command += ['--env','PAPERASSIST_SC_INTEGRATION_TOOLS=1']
        elif qc_tools:
            command += ['--env','PAPERASSIST_SC_QC_TOOLS=1']
        test = 'tests/api/test_single_cell_public_worker.py'
        if selection != 'all':
            test += '::test_public_matrix_normal_worker[' + selection + ']'
        command += [image, '-m', 'pytest', test,
                    '-q', '--tb=short', '-p', 'no:cacheprovider']
        output = run(command, ('batch3-' if integration_tools else 'batch2-' if qc_tools else '') + 'real-worker-' + selection, timeout=3600)
        print(output.decode('utf-8', errors='replace'))
    finally:
        # Only the private tempfile created immediately above; never project materials.
        Path(env_path).unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['probe', 'public-data', 'verify'])
    parser.add_argument('--image', default='paperassist-client-b06-w1-worker:local')
    parser.add_argument('--selection', choices=['all', 'single', 'multiple'], default='all')
    parser.add_argument('--qc-tools', action='store_true', help='Exercise real scDblFinder/decontX; keep separate Batch 2 evidence')
    parser.add_argument('--integration-tools', action='store_true', help='Exercise Harmony and covariates, plus existing R regression probes; keep Batch 3 evidence')
    parser.add_argument('--annotation-tools', action='store_true', help='Exercise SingleR, offline reference and subset reuse, plus prior R probes; keep Batch 4 evidence')
    args = parser.parse_args()
    if args.qc_tools or args.integration_tools or args.annotation_tools:
        CONTAINER_MEMORY = '5g'
        prior = EVIDENCE
        EVIDENCE = ROOT / ('script/.runtime/single-cell-batch4' if args.annotation_tools else 'script/.runtime/single-cell-batch3' if args.integration_tools else 'script/.runtime/single-cell-batch2')
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        # Reuse the attributed public matrix files without touching Batch 1 results.
        import shutil
        if (prior / 'public-data').is_dir() and not (EVIDENCE / 'public-data').exists():
            shutil.copytree(prior / 'public-data', EVIDENCE / 'public-data')
    if args.action == 'probe': probe(args.image, qc_tools=args.qc_tools or args.integration_tools or args.annotation_tools, integration_tools=args.integration_tools or args.annotation_tools, annotation_tools=args.annotation_tools)
    elif args.action == 'public-data': public_data()
    else: verify(args.image, args.selection, qc_tools=args.qc_tools or args.integration_tools, integration_tools=args.integration_tools)
