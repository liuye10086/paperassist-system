"""Real Linux numerical, rendering, HDF5 and sandbox gate."""
import os
os.environ.update({name: '1' for name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMBA_NUM_THREADS')})
os.environ['MPLBACKEND'] = 'Agg'
os.environ['HDF5_PLUGIN_PATH'] = '/nonexistent'
os.environ['NUMBA_THREADING_LAYER'] = 'omp'
os.environ['NUMBA_CACHE_DIR']='/tmp/paperassist-numba'
os.environ['XDG_CACHE_HOME']='/tmp/paperassist-cache'
import hashlib
import json
import tempfile
from pathlib import Path


def exercise(output):
    from tqdm import tqdm
    tqdm.monitor_interval=0
    if tqdm.monitor is not None:
        tqdm.monitor.exit()
        tqdm.monitor=None
    import numpy as np
    import scipy.sparse as sp
    import scanpy as sc
    import anndata as ad
    import h5py
    from matplotlib import pyplot as plt
    from matplotlib.font_manager import FontProperties
    rng = np.random.default_rng(12)
    # Warm sklearn's brute-force 32/64-bit kernels and cached BLAS controller.
    # Otherwise a data-dependent KNN algorithm can first inspect /proc/self/maps
    # after isolation. No procfs read capability is granted to customer work.
    from sklearn.neighbors import NearestNeighbors
    for dtype in ['float32','float64']:
        trusted=rng.normal(size=(8,3)).astype(dtype)
        NearestNeighbors(n_neighbors=3,algorithm='brute').fit(trusted).kneighbors(trusted)
    matrix = sp.csr_matrix(rng.poisson(3, (24, 12)).astype('float32'))
    obj = ad.AnnData(matrix)
    sc.pp.normalize_total(obj, target_sum=10000)
    assert np.allclose(np.asarray(obj.X.sum(1)).ravel(), 10000, rtol=1e-6)
    sc.pp.log1p(obj)
    sc.pp.pca(obj, n_comps=5, svd_solver='arpack', random_state=0)
    sc.pp.neighbors(obj, n_neighbors=5, n_pcs=5, metric='euclidean', method='umap', transformer='sklearn', random_state=0)
    sc.tl.umap(obj, min_dist=.5, spread=1., n_components=2, maxiter=500, random_state=0)
    sc.tl.leiden(obj, flavor='igraph', directed=False, use_weights=True, n_iterations=2, resolution=.5, random_state=0)
    assert np.isfinite(obj.obsm['X_umap']).all()
    obj.write_h5ad(output / 'probe.h5ad')
    restored = ad.read_h5ad(output / 'probe.h5ad')
    assert (restored.X != obj.X).nnz == 0
    font = Path('/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc')
    fig, ax = plt.subplots()
    ax.scatter(obj.obsm['X_umap'][:, 0], obj.obsm['X_umap'][:, 1])
    ax.set_title('空间转录组 QC', fontproperties=FontProperties(fname=font))
    fig.savefig(output / 'probe.png', dpi=100, metadata={'Software': 'PaperAssist'})
    fig.savefig(output / 'probe.pdf', metadata={'CreationDate': None, 'ModDate': None})
    plt.close(fig)
    import importlib.metadata
    return {'scanpy': importlib.metadata.version('scanpy'), 'h5_roundtrip': True,
            'png_bytes': (output / 'probe.png').stat().st_size,
            'pdf_bytes': (output / 'probe.pdf').stat().st_size,
            'font_sha256': hashlib.sha256(font.read_bytes()).hexdigest()}


def probe():
    from app.adapters.bio_parser.sandbox import enter_bio_sandbox
    from types import SimpleNamespace
    import socket
    import resource
    import importlib.metadata
    import matplotlib.font_manager
    from PIL import Image
    Image.init()
    if True:
        directory = tempfile.mkdtemp(prefix='bio-gate-')
        output = Path(directory)
        import sys, io, contextlib, numpy as np
        report = exercise(output)  # Trusted synthetic warmup, before any customer bytes.
        report['python']=sys.version
        import numba
        report['numba_threading_layer']=numba.threading_layer()
        report['warm_threads']=len(os.listdir('/proc/self/task'))
        report['packages']={dist.metadata['Name']:dist.version for dist in importlib.metadata.distributions()}
        import h5py
        report['hdf5_version']=h5py.version.hdf5_version
        from threadpoolctl import threadpool_info
        report['native_libraries']=threadpool_info()
        for library in report['native_libraries']:
            library['sha256']=hashlib.sha256(Path(library['filepath']).read_bytes()).hexdigest()
        report['libgomp_sha256']=hashlib.sha256(Path('/usr/lib/x86_64-linux-gnu/libgomp.so.1.0.0').read_bytes()).hexdigest()
        stream=io.StringIO()
        with contextlib.redirect_stdout(stream):np.show_config()
        report['blas_config']=stream.getvalue()
        lock=Path('/app/requirements-bio.lock.txt') if Path('/app/requirements-bio.lock.txt').is_file() else Path('/tmp/requirements-bio.lock.txt')
        if lock.is_file():report['lock_sha256']=hashlib.sha256(lock.read_bytes()).hexdigest()
        # Fonts and numeric libs are trusted read-only runtime assets. No /etc,
        # application config, database, credential directory or arbitrary /proc read.
        trusted = ['/opt/paperassist-bio', '/usr/share/fonts/truetype/wqy']
        # The existing parser sandbox grants files read; directory assets also
        # require READ_DIR, supplied by the bio-specific wrapper.
        from app.adapters.bio_engine.sandbox import enter
        if report['warm_threads']!=1:
            import threading
            raise RuntimeError({key:report[key] for key in ['numba_threading_layer','warm_threads'] } | {'threads':[(Path('/proc/self/task')/t/'comm').read_text() for t in os.listdir('/proc/self/task')], 'python_threads':str(threading.enumerate())})
        fds = enter([], output, parent_pid=os.getppid())
        isolation = {}
        for key, action in [('network', lambda: socket.socket()), ('file', lambda: open('/etc/passwd')), ('fork', os.fork)]:
            try:
                action()
            except PermissionError:
                isolation[key] = 'denied'
            else:
                raise AssertionError(f'{key} access unexpectedly permitted')
        after = exercise(output)
        report.update(after, status='passed', isolation=isolation,
                      peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                      address_space_limit=resource.getrlimit(resource.RLIMIT_AS),
                      numeric_threads=1)
        for fd in fds:
            os.close(fd)
        return report


if __name__ == '__main__':
    print(json.dumps(probe(), sort_keys=True))
