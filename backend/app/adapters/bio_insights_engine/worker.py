"""Warm trusted libraries, attest exact environment, then isolate input reads."""
import os
for _key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMBA_NUM_THREADS','NUMEXPR_NUM_THREADS',
             'VECLIB_MAXIMUM_THREADS','BLIS_NUM_THREADS','RAYON_NUM_THREADS'):
    os.environ[_key]='1'
os.environ.update(MPLBACKEND='Agg',MPLCONFIGDIR='/tmp/b04-mpl',XDG_CACHE_HOME='/tmp/b04-cache',
                  HDF5_PLUGIN_PATH='/nonexistent',HDF5_PLUGIN_PRELOAD='::')
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from app.adapters.single_cell_r.bootstrap import preload_runtime_libraries
preload_runtime_libraries()
import codecs
import hashlib
import importlib
import importlib.metadata
import json
import signal
import struct
import tempfile
import resource
import traceback
from app.adapters.bio_engine.manifest import canonical
from app.adapters.bio_insights_engine.pipeline import run
from app.adapters.bio_insights_engine.sandbox import enter
from app.adapters.bio_insights_engine.runtime_probe import exercise
from app.domain.bio_insights.settings import BioInsightsLimits,engine_code_digest,engine_lock_digest


def records(payload):
    result=[]
    for source in payload.get('sources',[]):
        for container in (source,source.get('raw',{})):
            result.extend(container.get('members',{}).values())
    if not 1<=len(result)<=514:raise ValueError('input_member_limit')
    return result


def actual_identity():
    # Attest the same locked native inventory for every assay and reproduction entry.
    # Import only: no beta calculation or assay-specific warmup is needed here.
    import skbio.stats.distance
    from threadpoolctl import threadpool_info
    packages={dist.metadata['Name'].lower().replace('_','-'):dist.version for dist in importlib.metadata.distributions()}
    libraries=sorted(threadpool_info(),key=lambda library:library['filepath'])
    for library in libraries:
        library['sha256']=hashlib.sha256(Path(library['filepath']).read_bytes()).hexdigest()
        if library['num_threads']!=1:raise ValueError('numeric_threads_invalid')
    environment=dict(python=sys.version,packages=packages,native_libraries=libraries,lock_sha256=engine_lock_digest(),limits=BioInsightsLimits().model_dump())
    return dict(available=True,engine_version='bio_insights_v1.0.0',code_digest=engine_code_digest(),lock_sha256=engine_lock_digest(),
                environment_digest=hashlib.sha256(json.dumps(environment,sort_keys=True,separators=(',',':')).encode()).hexdigest())


def warm_render_environment(output):
    """Load the locked environment and fonts without invoking any analysis."""
    import numpy
    import pandas
    from scipy import sparse
    from pydeseq2.dds import DeseqDataSet
    from pydeseq2.ds import DeseqStats
    from pydeseq2.default_inference import DefaultInference
    import gseapy
    from matplotlib import pyplot as plt
    from matplotlib.font_manager import FontProperties
    from tqdm import tqdm
    tqdm.monitor_interval=0
    fig,ax=plt.subplots();ax.plot([0,1],[0,1])
    ax.set_title('图形环境验证',fontproperties=FontProperties(fname='/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc'))
    for fmt in ('png','svg','tiff'):fig.savefig(output/('warm.'+fmt),format=fmt)
    plt.close(fig)


def warm_microbiome_environment():
    import skbio
    from skbio.stats.distance import permanova, permdisp
    from app.adapters.bio_insights_engine.microbiome import beta_tests
    beta_tests([[0.,.1,.2,.7,.8,.9],[.1,0.,.1,.6,.7,.8],[.2,.1,0.,.5,.6,.7],[.7,.6,.5,0.,.1,.2],[.8,.7,.6,.1,0.,.1],[.9,.8,.7,.2,.1,0.]],['a','a','a','b','b','b'],permutations=0)


def main():
    sys.stdout.buffer.write(b'READY\n');sys.stdout.buffer.flush();pinned=[];output=None;phase='transport'
    try:
        header=sys.stdin.buffer.read(4)
        if len(header)!=4:raise ValueError('invalid_transport')
        length=struct.unpack('!I',header)[0]
        if not 0<length<=2*1024**2:raise ValueError('input_transport_limit')
        body=sys.stdin.buffer.read(length)
        if len(body)!=length or sys.stdin.buffer.read(1):raise ValueError('invalid_transport')
        def pairs(items):
            result={}
            for key,value in items:
                if key in result:raise ValueError('duplicate_json_key')
                result[key]=value
            return result
        payload=json.loads(body,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite_json')))
        candidate=Path(payload['output_directory'])
        if candidate.is_symlink() or not candidate.is_dir() or any(candidate.iterdir()):raise ValueError('output_not_empty')
        output=candidate;phase='warmup'
        def deadline(*_):raise TimeoutError('bio_insights_deadline')
        limits=BioInsightsLimits();signal.signal(signal.SIGALRM,deadline);signal.setitimer(signal.ITIMER_REAL,limits.warmup_seconds)
        from PIL import Image
        Image.init();codecs.lookup('utf-8-sig')
        # Import all trusted code before Landlock denies the application tree.
        for name in ('comparison','result_import','resources','enrichment','candidates','figures','quantitative','counts_model','quantitative_figures','qpcr','qpcr_figures','microbiome','microbiome_figures','feature_extract','feature_figures','integration','integration_figures','external_evidence','evidence_figures','single_cell_composition','single_cell_topics','topic_figures'):
            importlib.import_module('app.adapters.bio_insights_engine.'+name)
        import Bio.PDB.MMCIF2Dict
        import Bio.PDB.Polypeptide
        if payload['config'].get('schema_version')==4 or payload['config'].get('figure_type','').startswith('microbiome_'):warm_microbiome_environment()
        with tempfile.TemporaryDirectory(prefix='b04-warm-') as warm:
            if payload['kind']=='bio_candidate' and payload['config'].get('schema_version')==2 or payload['kind'] in ('bio_insight_figure','bio_feature_extract','bio_integration') or payload['kind']=='bio_resource_import' and payload['config'].get('kind') in ('sequence','structure','sample_correspondence','object_correspondence') or payload['kind']=='bio_comparison' and payload['config'].get('schema_version') in (3,4,5):warm_render_environment(Path(warm))
            else:exercise(Path(warm))
        from app.adapters.single_cell_r.bridge import initialize_propeller
        r_scratch=Path(tempfile.mkdtemp(prefix='b04-propeller-',dir='/tmp'))
        from contextlib import redirect_stdout
        with redirect_stdout(sys.stderr):
            if payload['kind']=='bio_integration' and payload['config'].get('schema_version')==2:
                from app.adapters.single_cell_r.topics import initialize_topics
                initialize_topics(r_scratch,payload['config']['method'])
            else:initialize_propeller(r_scratch)
        actual=actual_identity()
        phase='environment_identity'
        if actual!=payload['_runtime_identity']:raise RuntimeError('bio_insights_environment_unavailable')
        if any(payload['identity'].get(key)!=actual[key] for key in ('engine_version','code_digest','environment_digest','lock_sha256')):
            raise RuntimeError('bio_insights_environment_unavailable')
        files=records(payload)
        for item in files:
            path=Path(item['path'])
            if not path.is_absolute() or path.is_symlink() or not path.is_file():raise ValueError('invalid_input_path')
        signal.setitimer(signal.ITIMER_REAL,limits.compute_wall_seconds)
        phase='isolation';pinned=enter(files,output,int(sys.argv[1]),r_scratch=r_scratch);phase='analysis'
        result=run(payload)
        result['resources']={'child_peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
        answer=canonical({'result':result})
        if len(answer)>2*1024**2:raise ValueError('output_transport_limit')
    except Exception as exc:
        from app.adapters.excel_sandbox import SandboxUnavailable
        code='bio_insights_input_invalid'
        if isinstance(exc,MemoryError):code='bio_insights_resource_exceeded'
        elif isinstance(exc,TimeoutError):code='bio_insights_timeout'
        elif isinstance(exc,SandboxUnavailable):code='bio_insights_isolation_unavailable'
        elif isinstance(exc,RuntimeError) and str(exc)=='bio_insights_environment_unavailable':code=str(exc)
        elif isinstance(exc,ValueError) and str(exc)=='figure_layout_too_small':code='bio_insights_figure_layout_too_small'
        elif 'design' in str(exc) or 'pseudobulk_model_failed' in str(exc):code='bio_insights_design_blocked'
        if output is not None:
            # Kept only in this attempt's protected staging directory, never a
            # public error response. No locals, environment or credentials.
            diagnostic=dict(code=code,phase=phase,exception_type=type(exc).__name__,message=str(exc)[:2000],
                frames=[dict(file=Path(frame.filename).name,line=frame.lineno,function=frame.name)
                        for frame in traceback.extract_tb(exc.__traceback__)[-20:]],
                child_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            try:(output/'failure-diagnostics.json').write_bytes(canonical(diagnostic))
            except OSError:pass
        answer=canonical({'error':{'code':code}})
    finally:
        for fd in pinned:os.close(fd)
    sys.stdout.buffer.write(answer);sys.stdout.buffer.flush()


if __name__=='__main__':main()
