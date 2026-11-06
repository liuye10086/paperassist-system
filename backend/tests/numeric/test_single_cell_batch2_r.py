"""Real pinned R packages, direct original-tool comparison and isolated worker.

Run only in paperassist-single-cell-worker:local; no DB or external data.
Launch preload_runtime_libraries() before importing pytest (pytest may import
hashlib/numpy and pin incompatible base-system libraries before collection).
"""
import csv
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
from app.adapters.single_cell_r.bootstrap import preload_runtime_libraries
preload_runtime_libraries()
import numpy as np
import pytest
from scipy import sparse

pytestmark=pytest.mark.skipif(not Path('/opt/paperassist-single-cell-r/lib/R').is_dir(),reason='pinned embedded R runtime required')


def data():
    rng=np.random.default_rng(23)
    matrix=rng.poisson(2,(160,96)).astype('int64')
    matrix[:80,:32]+=rng.poisson(14,(80,32));matrix[80:,32:64]+=rng.poisson(14,(80,32))
    matrix[74:80]+=matrix[90:96]
    return sparse.csr_matrix(matrix),[f'cell_{i:03}' for i in range(160)],[f'gene_{i:03}' for i in range(96)]


def test_real_embedded_models_equal_direct_original_tools_and_preserve_counts(tmp_path):
    from app.adapters.single_cell_r.bridge import initialize
    from app.adapters.single_cell_r.algorithms import run_algorithms
    bridge=initialize(tmp_path)
    assert bridge.versions['xgboost']=='2.1.4.1' and bridge.versions['RcppParallel']=='5.1.9'
    matrix,cells,genes=data();original=matrix.copy();ro=bridge.ro
    # Independent COO construction and direct exported functions. No pa_run,
    # pipeline, or adapter result generation is used by this reference.
    direct=ro.r('''function(x,i,j,genes,cells,seed) {
      mat <- Matrix::sparseMatrix(i=i,j=j,x=x,dims=c(length(genes),length(cells)),dimnames=list(genes,cells))
      set.seed(seed)
      dbl <- scDblFinder::scDblFinder(mat,dbr=0.1,clusters=FALSE,dims=20L,includePCs=19L,nfeatures=min(1352L,nrow(mat)),verbose=FALSE,BPPARAM=BiocParallel::SerialParam(progressbar=FALSE))
      set.seed(seed)
      dec <- decontX::decontX(mat,seed=seed,verbose=FALSE)
      list(score=dbl$scDblFinder.score,prediction=as.character(dbl$scDblFinder.class),contamination=dec$contamination,x=dec$decontXcounts@x,i=dec$decontXcounts@i,p=dec$decontXcounts@p,cells=colnames(dec$decontXcounts),genes=rownames(dec$decontXcounts))
    }''')
    coo=matrix.tocoo();reference=direct(ro.FloatVector(coo.data.astype('float64')),ro.IntVector(coo.col+1),ro.IntVector(coo.row+1),ro.StrVector(genes),ro.StrVector(cells),23)
    doublet=bridge.run(matrix,cells,genes,'scdblfinder',23,.1)
    correction=bridge.run(matrix,cells,genes,'decontx',23)
    assert doublet['status']=='completed',doublet
    assert correction['status']=='completed',correction
    np.testing.assert_allclose(doublet['score'],np.asarray(reference.rx2('score')),rtol=0,atol=1e-12)
    assert doublet['prediction']==list(reference.rx2('prediction'))
    np.testing.assert_allclose(correction['contamination'],np.asarray(reference.rx2('contamination')),rtol=0,atol=1e-12)
    expected=sparse.csr_matrix((np.asarray(reference.rx2('x')),np.asarray(reference.rx2('i')),np.asarray(reference.rx2('p'))),shape=matrix.shape)
    assert (correction['counts']-expected).nnz==0
    assert list(reference.rx2('cells'))==cells and list(reference.rx2('genes'))==genes
    assert correction['counts'].dtype.kind=='f' and np.any(correction['counts'].data%1!=0)
    assert (matrix!=original).nnz==0
    config=dict(seed=23,doublet=dict(enabled=True,expected_rate=.1,exclude_predicted=True),decontx=dict(enabled=True))
    joined=sparse.vstack([matrix,matrix],format='csr');joined_cells=['A:'+v for v in cells]+['B:'+v for v in cells]
    combined=run_algorithms(joined,joined_cells,genes,['A']*160+['B']*160,config)
    assert combined['summary']['decontx']['status']=='completed',combined['library_algorithms']
    for offset in (0,160):
        np.testing.assert_allclose([r['doublet_score'] for r in combined['observations'][offset:offset+160]],doublet['score'],rtol=0,atol=1e-12)
        np.testing.assert_allclose([r['decontx_contamination'] for r in combined['observations'][offset:offset+160]],correction['contamination'],rtol=0,atol=1e-12)
    assert (combined['decontx_counts'][:160]-correction['counts']).nnz==0
    assert combined['keep'].tolist()==[v=='singlet' for v in doublet['prediction']]*2


def test_real_isolated_worker_runs_tools_and_aligns_float_layer_with_final_counts(tmp_path):
    from app.adapters.bio_engine.manifest import Writer
    matrix,cells,genes=data()
    source=tmp_path/'source';source.mkdir();writer=Writer(source)
    writer.matrix('matrix',matrix);writer.json('features_index',dict(feature_ids=genes,feature_symbols=genes,feature_types=['Gene Expression']*len(genes)));writer.json('barcodes_index',dict(barcodes=cells))
    writer.json('observation_map_index',dict(rows=[dict(barcode=cell,library_id='L1',original_barcode=cell) for cell in cells]))
    output=tmp_path/'output';output.mkdir()
    raw=dict(manifest=dict(assay='single_cell',input_shape=dict(observations=len(cells),features=len(genes))),members={m['key']:m for m in writer.artifacts})
    payload=dict(mode='compute',raw=raw,config=dict(seed=23,min_spots=1,hvg_count=32,pca_components=8,neighbors=8,doublet=dict(enabled=True,expected_rate=.1,exclude_predicted=True),decontx=dict(enabled=True)),output_directory=str(output))
    body=json.dumps(payload).encode();worker=Path(__file__).resolve().parents[2]/'app/adapters/bio_engine/worker.py'
    completed=subprocess.run([sys.executable,'-I','-B',str(worker),str(os.getpid())],input=struct.pack('!I',len(body))+body,env={},capture_output=True,timeout=420)
    (tmp_path/'worker.stderr.txt').write_bytes(completed.stderr);(tmp_path/'worker.stdout.json').write_bytes(completed.stdout)
    assert completed.returncode==0,completed.stderr.decode()
    assert completed.stdout.startswith(b'READY\n'),completed.stdout[:200]
    answer=json.loads(completed.stdout.split(b'\n',1)[1]);assert 'error' not in answer,completed.stderr.decode()
    result=answer['result'];states=result['summary']['single_cell_algorithms']
    assert result['manifest']['resources']['rss_limit_bytes']==4*1024**3
    assert result['manifest']['resources']['address_space_limit_bytes']==5*1024**3
    assert result['manifest']['resource_estimate']['configured_limits']['memory_bytes']==4*1024**3
    assert states['doublet']['status']==states['decontx']['status']=='completed',states
    assert states['decontx']['layer_emitted'] is True
    members={m['key']:m for m in result['outputs']}
    rows=list(csv.DictReader(Path(members['observations']['path']).open(),delimiter='\t'))
    kept=np.asarray([r['kept']=='True' for r in rows])
    import anndata as ad
    restored=ad.read_h5ad(members['processed']['path'])
    assert restored.obs_names.tolist()==list(np.asarray(cells)[kept])
    assert restored.var_names.tolist()==genes
    assert (restored.layers['counts']!=matrix[kept]).nnz==0
    assert restored.layers['decontx_counts'].dtype.kind=='f'
    assert np.any(restored.layers['decontx_counts'].data%1!=0)
    assert states['doublet']['excluded_cells']==int((~kept).sum())
    assert all(r['doublet_status']=='completed' for r in rows)
    assert not any(m['format']=='pdf' for m in result['outputs'])


def test_r_scratch_grant_preserves_network_fork_exec_and_unlisted_tmp_denial(tmp_path):
    output=tmp_path/'output';output.mkdir();secret=tmp_path/'unlisted';secret.write_text('not granted')
    script='''
import os,socket,sys,tempfile,resource
from pathlib import Path
from app.adapters.single_cell_r.bridge import initialize
from app.adapters.bio_engine.sandbox import enter
scratch=Path(tempfile.mkdtemp(prefix='paperassist-single-cell-r-',dir='/tmp'))
bridge=initialize(scratch)
assert len(os.listdir('/proc/self/task'))==1
fds=enter([],Path(sys.argv[1]),os.getppid(),r_scratch=scratch)
assert resource.getrlimit(resource.RLIMIT_AS)==(5*1024**3,5*1024**3)
(scratch/'allowed').write_text('ok')
assert (scratch/'allowed').read_text()=='ok'
assert Path('/opt/paperassist-single-cell-r/explicit-spec.txt').read_bytes()
for action in [lambda:Path(sys.argv[2]).read_bytes(),lambda:socket.socket(),os.fork,lambda:os.execve('/bin/true',['/bin/true'],{})]:
 try:action()
 except PermissionError:pass
 else:raise AssertionError('unauthorized access')
print('R_SCRATCH_ISOLATION_PASSED')
'''
    env={**os.environ,**{name:'1' for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS')}}
    result=subprocess.run([sys.executable,'-c',script,str(output),str(secret)],capture_output=True,text=True,env=env,timeout=240)
    (tmp_path/'r-isolation.stderr.txt').write_text(result.stderr)
    assert result.returncode==0,result.stderr
    assert result.stdout.strip()=='R_SCRATCH_ISOLATION_PASSED'
