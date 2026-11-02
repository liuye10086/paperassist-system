"""Actual final-image inventory, without repeating accepted numerical fits."""
import os
for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMBA_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS','BLIS_NUM_THREADS','RAYON_NUM_THREADS'):
    os.environ[key]='1'
os.environ.update(MPLBACKEND='Agg',MPLCONFIGDIR='/tmp/sub3-mpl',XDG_CACHE_HOME='/tmp/sub3-cache',NUMBA_CACHE_DIR='/tmp/sub3-numba')
import hashlib
import importlib
import importlib.metadata
import json
from pathlib import Path
import sys
import tempfile


def inventory():
    # Load the production scientific module set; never invoke its exercise/fits.
    for name in ('comparison','result_import','resources','enrichment','candidates','figures','microbiome'):
        importlib.import_module('app.adapters.bio_insights_engine.'+name)
    import skbio.stats.distance
    from app.adapters.bio_insights_engine.worker import warm_render_environment,warm_microbiome_environment,actual_identity
    with tempfile.TemporaryDirectory(prefix='sub3-inventory-') as warm:
        warm_render_environment(Path(warm))
    warm_microbiome_environment()
    from threadpoolctl import threadpool_info
    from app.domain.bio_insights.settings import BioInsightsLimits,engine_code_digest,engine_lock_digest
    libraries=sorted(threadpool_info(),key=lambda value:value['filepath'])
    for library in libraries:
        library['sha256']=hashlib.sha256(Path(library['filepath']).read_bytes()).hexdigest()
        assert library['num_threads']==1
    return dict(runtime_identity=actual_identity(),python=sys.version,packages={d.metadata['Name'].lower().replace('_','-'):d.version for d in importlib.metadata.distributions()},native_libraries=libraries,
        lock_sha256=engine_lock_digest(),limits=BioInsightsLimits().model_dump(),code_digest=engine_code_digest(),numeric_threads=1,
        validation_scope='actual final-image imports and package/native-library inventory only; no accepted model refit')


if __name__=='__main__':print(json.dumps(inventory(),sort_keys=True))
