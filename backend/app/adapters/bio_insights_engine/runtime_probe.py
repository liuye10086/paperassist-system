"""Actual synthetic aggregation, model, local GSEA and kernel isolation gate."""
import os
for _name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMBA_NUM_THREADS',
              'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'BLIS_NUM_THREADS', 'RAYON_NUM_THREADS'):
    os.environ[_name] = '1'
os.environ.update(MPLBACKEND='Agg', MPLCONFIGDIR='/tmp/b04-mpl', XDG_CACHE_HOME='/tmp/b04-cache',
                  HDF5_PLUGIN_PATH='/nonexistent', HDF5_PLUGIN_PRELOAD='::')
import hashlib
import importlib.metadata
import json
import resource
import signal
import socket
import subprocess
import sys
import tempfile
from pathlib import Path


def exercise(output):
    """Only trusted reproducible fixtures; also warms code used after isolation."""
    import numpy as np
    import pandas as pd
    from scipy import sparse
    from pydeseq2.dds import DeseqDataSet
    from pydeseq2.ds import DeseqStats
    from pydeseq2.default_inference import DefaultInference
    import gseapy
    from matplotlib import pyplot as plt
    from matplotlib.font_manager import FontProperties
    from tqdm import tqdm
    tqdm.monitor_interval = 0
    rng = np.random.default_rng(745)
    counts = rng.negative_binomial(12, .35, size=(24, 80)).astype('int64') + 1
    counts[12:, :10] *= 4
    aggregation = sparse.csr_matrix((np.ones(24, dtype='int64'),
                                    (np.repeat(np.arange(12), 2), np.arange(24))), shape=(12, 24))
    grouped = (aggregation @ sparse.csr_matrix(counts)).toarray()
    assert grouped.sum() == counts.sum()
    index = [f'donor{i}' for i in range(12)]
    frame = pd.DataFrame(grouped, index=index, columns=[f'g{i}' for i in range(80)])
    metadata = pd.DataFrame({'condition': ['A'] * 6 + ['B'] * 6}, index=index)
    inference = DefaultInference(n_cpus=1)
    dds = DeseqDataSet(counts=frame, metadata=metadata, design='~condition',
                       size_factors_fit_type='poscounts', refit_cooks=False,
                       low_memory=True, n_cpus=1, inference=inference, quiet=True)
    dds.deseq2()
    stats = DeseqStats(dds, contrast=['condition', 'B', 'A'], n_cpus=1,
                      cooks_filter=True, independent_filter=False, inference=inference, quiet=True)
    stats.summary()
    assert np.isfinite(stats.results_df['log2FoldChange']).all()
    assert stats.results_df.loc['g0':'g9', 'log2FoldChange'].median() > 0
    ranking = pd.Series(np.linspace(5, -5, 80), index=frame.columns)
    result = gseapy.prerank(rnk=ranking, gene_sets={'positive': list(frame.columns[:12]),
                            'negative': list(frame.columns[-12:])}, threads=1, permutation_num=100,
                            min_size=5, max_size=70, seed=0, outdir=None, no_plot=True, verbose=False)
    assert result.results['positive']['es'] > 0 and result.results['negative']['es'] < 0
    fig, ax = plt.subplots()
    ax.plot(ranking.to_numpy())
    ax.set_title('差异富集环境验证', fontproperties=FontProperties(fname='/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc'))
    fig.savefig(output / 'probe.png', dpi=100)
    plt.close(fig)
    return {'aggregation': True, 'deseq2_fit': True, 'gsea': True,
            'fit_shape': list(frame.shape), 'gsea_permutations': 100,
            'png_bytes': (output / 'probe.png').stat().st_size,
            'render_formats': ['png']}


def probe():
    from app.domain.bio_insights.settings import BioInsightsLimits, engine_code_digest
    from app.adapters.bio_insights_engine.sandbox import enter
    from PIL import Image
    from threadpoolctl import threadpool_info
    limits = BioInsightsLimits()
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError('bio_insights_deadline')))
    signal.alarm(limits.warmup_seconds)
    Image.init()
    # Match production import order before measuring loaded native libraries.
    import importlib
    for name in ('comparison','result_import','resources','enrichment','candidates','figures'):
        importlib.import_module('app.adapters.bio_insights_engine.'+name)
    output = Path(tempfile.mkdtemp(prefix='bio-insights-probe-'))
    exercise(output)
    packages = {dist.metadata['Name'].lower().replace('_', '-'): dist.version
                for dist in importlib.metadata.distributions()}
    libraries = sorted(threadpool_info(), key=lambda library: library['filepath'])
    for library in libraries:
        library['sha256'] = hashlib.sha256(Path(library['filepath']).read_bytes()).hexdigest()
        assert library['num_threads'] == 1
    report = {'schema_version': 1, 'engine_version': 'bio_insights_v1.0.0',
              'interpreter': sys.executable, 'python': sys.version, 'packages': packages,
              'native_libraries': libraries, 'numeric_threads': 1,
              'warm_threads': len(os.listdir('/proc/self/task')), 'limits': limits.model_dump(),
              'code_digest': engine_code_digest(),
              'lock_sha256': hashlib.sha256(Path('/app/requirements-bio-insights.lock.txt').read_bytes()).hexdigest()}
    report['container_memory_limit_bytes'] = int(Path('/sys/fs/cgroup/memory.max').read_text())
    report['container_cpu_max'] = Path('/sys/fs/cgroup/cpu.max').read_text().strip()
    report['docker_mem_available_bytes'] = next(int(line.split()[1]) * 1024 for line in
        Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
    assert report['container_memory_limit_bytes'] <= 4 * 1024**3
    assert report['docker_mem_available_bytes'] >= 4 * 1024**3
    # Open only these non-secret counter files before isolation. Retained FDs
    # permit final accounting without granting customer code a cgroup directory.
    memory_counter = os.open('/sys/fs/cgroup/memory.peak', os.O_RDONLY | os.O_CLOEXEC)
    task_counter = os.open('/sys/fs/cgroup/pids.peak', os.O_RDONLY | os.O_CLOEXEC)
    assert report['warm_threads'] == 1, report['warm_threads']
    signal.alarm(limits.compute_wall_seconds)
    pinned = enter([], output, parent_pid=os.getppid())
    isolation = {}
    for name, action in [('network', lambda: socket.socket()), ('file', lambda: Path('/etc/passwd').read_bytes()),
                         ('fork', os.fork), ('subprocess', lambda: subprocess.run(['/bin/true'], check=True))]:
        try:
            action()
        except PermissionError:
            isolation[name] = 'denied'
        else:
            raise AssertionError(f'{name} unexpectedly permitted')
    report['checks'] = exercise(output)
    report.update(status='passed', isolation=isolation,
                  peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  address_space_limit=list(resource.getrlimit(resource.RLIMIT_AS)))
    report['container_peak_memory_bytes'] = int(os.read(memory_counter, 128))
    report['container_peak_tasks'] = int(os.read(task_counter, 128))
    os.close(memory_counter); os.close(task_counter)
    assert report['peak_rss_kib'] < limits.memory_bytes // 1024
    for descriptor in pinned:
        os.close(descriptor)
    signal.alarm(0)
    return report


if __name__ == '__main__':
    print(json.dumps(probe(), sort_keys=True, allow_nan=False))
