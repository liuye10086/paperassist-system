"""Offline synthetic import/processing gate through the actual isolated child."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
from app.domain.bioinformatics.tabular_contracts import BioImportRequestV3, ENGINE_VERSION
from app.domain.bioinformatics.tabular_settings import engine_code_digest
from app.adapters.bio_insights_engine.worker import actual_identity, warm_render_environment
from app.adapters.bio_insights_engine.probe_transport import monitored_run


def exercise(root, *, bulk_counts=False):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    warm = root / 'warm'
    warm.mkdir()
    warm_render_environment(warm)
    runtime = actual_identity()
    runtime.update(engine_version=ENGINE_VERSION, code_digest=engine_code_digest(), blockers=[])
    samples = 'sample_id,condition,biological_unit_id\ns1,A,b1\ns2,A,b2\ns3,B,b3\n'
    matrix = 'feature_id,s1,s2,s3\nf1,2,4,8\nf2,4,8,16\nf3,3,NA,12\n'
    scale = dict(kind='intensity', unit='AU', upstream_method='offline synthetic')
    extra = {}
    if bulk_counts:
        samples += 's4,B,b4\n'
        matrix = 'feature_id,s1,s2,s3,s4\nf1,2,4,8,9\nf2,4,8,16,30\nf3,8,5,2,3\nf4,0,0,0,0\n'
        scale = dict(kind='raw_counts', unit='counts', upstream_method='offline synthetic',
                     namespace='synthetic_id', reference_version='probe_v1', input_origin='bulk_rna')
        extra['sample_metadata_mapping'] = dict(sample_id='sample_id', condition='condition',
                                                 biological_unit_id='biological_unit_id')
    files = []
    for key, contents, role in [('matrix', matrix, 'quantitative_matrix'), ('samples', samples, 'sample_metadata')]:
        path = root / (key + '.csv')
        path.write_text(contents, encoding='utf-8')
        files.append(dict(id=key, filename=path.name, path=str(path),
                          sha256=hashlib.sha256(path.read_bytes()).hexdigest(), size_bytes=path.stat().st_size, role=role))
    config = BioImportRequestV3(
        workflow_version='bio_import_v3', file_ids=['matrix', 'samples'],
        assay='bulk_rna_counts' if bulk_counts else 'proteomics', name='gate', expected_dataset_revision=0,
        tables=[dict(file_id=f['id'], role=f['role'], format='csv') for f in files],
        feature_id_column='feature_id', sample_columns=matrix.splitlines()[0].split(',')[1:], scale=scale, **extra,
    ).model_dump()
    identity = {k: runtime[k] for k in ('engine_version', 'environment_digest', 'code_digest')}

    def child(payload, mode, name):
        from app.adapters.bio_tabular_process import validate_tabular_result

        directory = root / name
        directory.mkdir()
        request = {**payload, 'mode': mode, 'output_directory': str(directory), '_runtime_identity': runtime}
        body = json.dumps(request, allow_nan=False).encode()
        command = [sys.executable, '-I', '-B', str(Path(__file__).with_name('tabular_worker.py')), str(os.getpid())]
        process = monitored_run(command, struct.pack('!I', len(body)) + body, timeout=1380)
        (root / (name + '-stderr.txt')).write_bytes(process.stderr)
        if process.returncode or not process.stdout.startswith(b'READY\n'):
            raise RuntimeError('tabular child transport failed')
        result = json.loads(process.stdout[6:])
        if 'result' not in result:
            raise RuntimeError('tabular child failed: ' + json.dumps(result))
        return validate_tabular_result(result['result'], directory, request, mode)

    import numpy as np

    imported = child(dict(files=files, config=config, identity=identity), 'import_v3', 'import')
    raw = dict(manifest=imported['manifest'], members={m['key']: m for m in imported['outputs']})
    params = dict(normalization='vst', output_language='en') if bulk_counts else dict(transform='log2')
    payload = dict(raw=raw, config=params, identity=identity)
    checks = {'tabular_import': True}
    results = [imported]
    if bulk_counts:
        qc = child(payload, 'qc', 'qc')
        if qc['summary']['qc_metrics']['total_counts'] != dict(s1=14, s2=17, s3=26, s4=42):
            raise RuntimeError('tabular QC probe totals differ')
        checks['tabular_qc'] = True
        results.append(qc)
    processed = child(payload, 'compute', 'compute')
    members = {m['key']: m for m in processed['outputs']}
    if bulk_counts:
        values = np.load(members['raw_values']['path'], allow_pickle=False)
        if (values.shape != (4, 4) or values[:, 0].tolist() != [2, 4, 8, 9]
                or not {'raw', 'filtered', 'normalized', 'vst'} <= processed['manifest']['value_layers'].keys()
                or processed['summary']['analysis_object']['round_trip'] != 'verified_by_loader'):
            raise RuntimeError('tabular Bulk layer or object verification failed')
    else:
        values = np.load(members['analysis_values']['path'], allow_pickle=False)
        missing = np.load(members['analysis_missing']['path'], allow_pickle=False)
        pca_mask = np.load(members['pca_feature_mask']['path'], allow_pickle=False)
        if (missing.sum() != 1 or values[0, 0] != 1 or values[2, 0] != 3
                or pca_mask.tolist() != [True, True, False] or processed['summary']['pca_components'] != 2):
            raise RuntimeError('tabular normalized-expression verification failed')
    checks['tabular_compute'] = True
    results.append(processed)
    report = dict(tabular_code_digest=runtime['code_digest'], checks=checks,
                  engine_version=ENGINE_VERSION, runtime_identity=runtime)
    if bulk_counts:
        report['child_peak_rss_kib'] = max(item['resources']['child_peak_rss_kib'] for item in results)
    return report


def scoped_receipt(root):
    import resource
    import socket
    import subprocess
    from app.adapters.bio_insights_engine.sandbox import enter
    from app.domain.bio_insights.settings import BioInsightsLimits, INTERPRETER
    from app.domain.bioinformatics.settings import BioLimits

    if sys.platform != 'linux' or sys.executable != INTERPRETER:
        raise RuntimeError('Run the tabular probe in the locked Linux interpreter')
    evidence = exercise(root, bulk_counts=True)
    limits = BioInsightsLimits()
    output = root / 'isolation'
    output.mkdir()

    def fork():
        pid = os.fork()
        if pid == 0:
            os._exit(0)
        os.waitpid(pid, 0)

    pinned = enter([], output, parent_pid=os.getppid())
    try:
        checks = {}
        for key, operation in (
            ('network', socket.socket), ('file', lambda: Path('/etc/passwd').read_bytes()),
            ('fork', fork), ('subprocess', lambda: subprocess.run(['/bin/true'], check=True)),
        ):
            try:
                operation()
            except PermissionError:
                checks[key] = 'denied'
            else:
                raise RuntimeError(f'Tabular probe isolation allowed {key}')
        peak = max(evidence['child_peak_rss_kib'], resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        if not 0 < peak < limits.memory_bytes // 1024:
            raise RuntimeError('Tabular probe exceeded the RSS gate')
        return dict(schema_version=1, status='passed', profile='tabular', platform=sys.platform,
                    interpreter=sys.executable, numeric_threads=limits.numeric_threads, limits=limits.model_dump(),
                    bulk_limits=BioLimits().model_dump(), isolation=checks, peak_rss_kib=peak,
                    checks=evidence['checks'], runtime_identity=evidence['runtime_identity'])
    finally:
        for descriptor in pinned:
            os.close(descriptor)


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--receipt', action='store_true')
    args = parser.parse_args()
    probe = scoped_receipt if args.receipt else exercise
    print(json.dumps(probe(args.directory.absolute()), sort_keys=True))
