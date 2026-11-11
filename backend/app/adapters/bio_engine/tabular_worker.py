"""Fixed B05 entrypoint sharing the locked B04 environment and sandbox."""
import os
for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMBA_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS','BLIS_NUM_THREADS','RAYON_NUM_THREADS'):os.environ[key]='1'
os.environ.update(MPLBACKEND='Agg',MPLCONFIGDIR='/tmp/b05-mpl',XDG_CACHE_HOME='/tmp/b05-cache')
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
import struct,signal,tempfile,codecs,traceback,resource
from app.adapters.bio_engine.manifest import canonical
from app.adapters.bio_engine.tabular_assays import import_tabular,run_tabular
from app.adapters.bio_engine.tabular_transport import MAX_FRAME_BYTES, read_request, response_result
from app.adapters.bio_insights_engine.worker import actual_identity,warm_render_environment
from app.adapters.bio_insights_engine.sandbox import enter
from app.domain.bioinformatics.tabular_settings import engine_code_digest
from app.domain.bioinformatics.tabular_contracts import ENGINE_VERSION
from app.domain.bio_insights.settings import BioInsightsLimits


def main():
    sys.stdout.buffer.write(b'READY\n');sys.stdout.buffer.flush();pinned=[]
    try:
        header=sys.stdin.buffer.read(4)
        if len(header)!=4:raise ValueError('transport_header')
        length=struct.unpack('!I',header)[0]
        if not 0<length<=MAX_FRAME_BYTES:raise ValueError('transport_limit')
        body=sys.stdin.buffer.read(length)
        if len(body)!=length or sys.stdin.buffer.read(1):raise ValueError('transport_length')
        payload=read_request(body)
        output=Path(payload['output_directory'])
        if output.is_symlink() or not output.is_dir() or any(output.iterdir()):raise ValueError('output_not_empty')
        limits=BioInsightsLimits()
        def timeout(*_):raise TimeoutError('tabular_timeout')
        signal.signal(signal.SIGALRM,timeout);signal.setitimer(signal.ITIMER_REAL,limits.warmup_seconds)
        codecs.lookup('utf-8-sig')
        with tempfile.TemporaryDirectory(prefix='b05-warm-') as warm:warm_render_environment(Path(warm))
        actual=actual_identity();actual.update(engine_version=ENGINE_VERSION,code_digest=engine_code_digest(),blockers=[])
        if actual!=payload['_runtime_identity']:raise RuntimeError('bio_environment_unavailable')
        if any(payload['identity'].get(k)!=actual[k] for k in ('engine_version','code_digest','environment_digest')):raise RuntimeError('bio_environment_unavailable')
        lock=Path(__file__).resolve().parents[3]/'requirements-bio-insights.lock.txt'
        payload['_trusted_lock']=lock.read_bytes()
        records=payload['files'] if payload['mode']=='import_v3' else list(payload['raw']['members'].values())
        if not 1<=len(records)<=256:raise ValueError('input_member_limit')
        signal.setitimer(signal.ITIMER_REAL,1200)
        pinned=enter(records,output,int(sys.argv[1]))
        result=import_tabular(payload) if payload['mode']=='import_v3' else run_tabular(payload)
        result['resources']={'child_peak_rss_kib':int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)}
        answer=canonical({'result':response_result(result, payload['mode'])})
        if len(answer)>MAX_FRAME_BYTES:raise ValueError('output_transport_limit')
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        code='bio_environment_unavailable' if isinstance(exc,RuntimeError) else 'bio_analysis_timeout' if isinstance(exc,TimeoutError) else 'bio_resource_exceeded' if isinstance(exc,MemoryError) else 'bio_recipe_invalid'
        answer=canonical({'error':{'code':code}})
    finally:
        for fd in pinned:os.close(fd)
    sys.stdout.buffer.write(answer);sys.stdout.buffer.flush()


if __name__=='__main__':main()
