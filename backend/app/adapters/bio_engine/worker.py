"""Secret-free trusted warmup, Linux isolation, then customer bytes."""
import os
for _key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMBA_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS','BLIS_NUM_THREADS'):
    os.environ[_key]='1'
os.environ.update(MPLBACKEND='Agg',MPLCONFIGDIR='/tmp/paperassist-mpl',XDG_CACHE_HOME='/tmp/paperassist-cache',HDF5_PLUGIN_PATH='/nonexistent',HDF5_PLUGIN_PRELOAD='::',NUMBA_CACHE_DIR='/tmp/paperassist-numba',NUMBA_THREADING_LAYER='omp')
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
import codecs
import json
import struct
import tempfile
import signal
from app.adapters.bio_engine.manifest import canonical
from app.adapters.bio_engine.pipeline import run
from app.adapters.bio_engine.figure import render
from app.adapters.bio_engine.sandbox import enter
from app.adapters.bio_engine.runtime_probe import exercise
from app.adapters.bio_engine.hdf5_checks import read_10x,compare
from app.adapters.bio_engine.errors import error_code
from app.adapters.bio_engine.importer import import_v2
from PIL import Image


def main():
    sys.stdout.buffer.write(b'READY\n');sys.stdout.buffer.flush()
    pinned=[]
    try:
        length=struct.unpack('!I',sys.stdin.buffer.read(4))[0]
        if not 0<length<=2*1024**2:raise ValueError('input_transport_limit')
        body=sys.stdin.buffer.read(length)
        if len(body)!=length or sys.stdin.buffer.read(1):raise ValueError('invalid_transport')
        payload=json.loads(body,parse_constant=lambda v:(_ for _ in ()).throw(ValueError('nonfinite_json')))
        for lock_path in [Path('/app/requirements-bio.lock.txt'),Path('/tmp/requirements-bio.lock.txt')]:
            if lock_path.is_file():payload['_trusted_lock']=lock_path.read_bytes();break
        if payload.get('mode') not in {'qc','compute','figure','h5_check','import_v2'}:raise ValueError('unsupported_engine_mode')
        member_count=0
        for group,limit in [('raw',256),('processed',256),('annotation',2)]:
            container=payload.get(group,{})
            if type(container) is not dict or type(container.get('members',{})) is not dict:raise ValueError('invalid_input_members')
            count=len(container.get('members',{}))
            if count>limit:raise ValueError('input_member_limit')
            member_count+=count
        if payload['mode']=='import_v2':
            if type(payload.get('files')) is not list or len(payload['files'])>256:raise ValueError('input_member_limit')
            member_count+=len(payload['files'])
        if member_count>514:raise ValueError('input_member_limit')
        output=Path(payload['output_directory'])
        if output.is_symlink() or not output.is_dir() or any(output.iterdir()):raise ValueError('output_not_empty')
        # Trusted small synthetic inputs and bundled fonts; no user file opened.
        def deadline(signum,frame):raise TimeoutError('bio_runtime_deadline')
        signal.signal(signal.SIGALRM,deadline);signal.setitimer(signal.ITIMER_REAL,180)
        Image.init();codecs.lookup('utf-8-sig')
        with tempfile.TemporaryDirectory(prefix='bio-warm-') as warm:
            exercise(Path(warm))
            # Warm HVG/normalization signatures and rendering imports as well.
            import numpy as np
            from scipy import sparse
            from app.adapters.bio_engine.preprocess import normalize,high_variable
            sample=sparse.csr_matrix(np.random.default_rng(0).poisson(4,(12,8)).astype('int64'))
            _,logged=normalize(sample);high_variable(logged,[str(i) for i in range(8)])
            import scanpy as sc
            sc.pp.scale(logged.toarray(),zero_center=True,max_value=10,copy=True)
        signal.setitimer(signal.ITIMER_REAL,0)
        files=[]
        if payload['mode']=='import_v2':
            from app.domain.bioinformatics.settings import BioLimits
            BioLimits.model_validate(payload.get('settings',{}))
            files.extend({'path':item['path']} for item in payload['files'])
        for key in ['raw','processed','annotation']:
            for member in payload.get(key,{}).get('members',{}).values():
                path=Path(member['path'])
                if path.is_symlink() or not path.is_file():raise ValueError('invalid_input_path')
                files.append({'path':str(path)})
        signal.setitimer(signal.ITIMER_REAL,1200)
        pinned=enter(files,output,parent_pid=int(sys.argv[1]))
        if payload['mode']=='import_v2':result=import_v2(payload)
        elif payload['mode']=='figure':result=render(payload)
        elif payload['mode']=='h5_check':
            from app.adapters.bio_engine.manifest import Writer
            import hashlib
            writer=Writer(output)
            member=payload['raw']['members'][payload.get('h5_member_key','alternate_matrix')]
            h5_path=Path(member['path'])
            if h5_path.stat().st_size!=member['size_bytes'] or hashlib.sha256(h5_path.read_bytes()).hexdigest()!=member['sha256']:raise ValueError('h5_source_hash_mismatch')
            matrix,features,barcodes,attestation=read_10x(member['path'])
            matrix.indptr=matrix.indptr.astype('int64');matrix.indices=matrix.indices.astype('int32')
            writer.matrix('matrix',matrix);writer.json('features_index',features);writer.json('barcodes_index',{'barcodes':barcodes})
            comparison={'status':'not_comparable','reason':'alternate_not_requested'}
            if payload.get('compare_alternate'):
                from app.adapters.bio_engine.pipeline import load_raw
                reference,reference_features,reference_barcodes,_=load_raw(payload['raw'])
                comparison=compare(reference,reference_features,reference_barcodes,matrix,features,barcodes)
            steps=[{'key':'h5_read','status':'completed','reason':None,'params':{'format':'10x_v3_matrix'}},
                   {'key':'equivalence','status':'completed' if comparison['status']!='not_comparable' else 'not_computable','reason':comparison.get('reason'),'params':{'comparator':'csr_all_values_v1'}}]
            manifest={'schema_version':1,'engine_version':'visium_explore_v1.0.0','attestation':attestation,'comparison':comparison,'steps':steps,'input_shape':{'observations':matrix.shape[0],'features':matrix.shape[1]},'members':[{k:v for k,v in item.items() if k!='path'} for item in writer.artifacts]}
            writer.json('manifest',manifest)
            result={'status':'completed','engine_version':'visium_explore_v1.0.0','outputs':writer.artifacts,'manifest':manifest,'summary':manifest,'steps':steps,'checks':attestation,'effective_params':{}}
        else:result=run(payload)
        answer=canonical({'result':result})
        if len(answer)>2*1024**2:raise ValueError('output_transport_limit')
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        answer=canonical({'error':{'code':error_code(exc)}})
    finally:
        for fd in pinned:os.close(fd)
    sys.stdout.buffer.write(answer);sys.stdout.buffer.flush()


if __name__=='__main__':main()
