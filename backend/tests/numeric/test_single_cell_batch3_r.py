"""Pinned Harmony native comparison and a real isolated workflow, no DB."""
from pathlib import Path
import json
import os
import struct
import subprocess
import sys
from app.adapters.single_cell_r.bootstrap import preload_runtime_libraries
preload_runtime_libraries()
import numpy as np
import pytest
from scipy import sparse

pytestmark=pytest.mark.skipif(not Path('/opt/paperassist-single-cell-r/lib/R').is_dir(),reason='pinned embedded R runtime required')


def test_harmony_matches_native_function_with_explicit_cell_order(tmp_path):
    from app.adapters.single_cell_r.bridge import initialize
    bridge=initialize(tmp_path);ro=bridge.ro
    rng=np.random.default_rng(72);pcs=rng.normal(size=(120,8));pcs[:60,0]+=3
    cells=[f'cell_{119-i:03}' for i in range(120)];batches=['b']*60+['a']*60
    config=dict(theta=2,**{'lambda':1},max_iter=10)
    actual=bridge.harmony(pcs,cells,batches,config,72)
    assert actual['status']=='completed',actual
    reference=ro.r('''function(values,cells,batches) {
      x <- matrix(values,nrow=length(cells),byrow=TRUE,dimnames=list(cells,NULL))
      meta <- data.frame(batch=batches,row.names=cells)
      set.seed(72)
      harmony::RunHarmony(data_mat=x,meta_data=meta,vars_use="batch",theta=2,sigma=.1,
        lambda=1,max_iter=10,early_stop=TRUE,ncores=1,return_object=FALSE,verbose=FALSE)
    }''')(ro.FloatVector(pcs.ravel()),ro.StrVector(cells),ro.StrVector(batches))
    assert list(reference.rownames)==cells
    np.testing.assert_allclose(actual['embedding'],np.asarray(reference),atol=1e-6,rtol=1e-6)
    assert bridge.versions['harmony']=='1.2.3'
    with pytest.raises(ValueError,match='axis'):bridge.harmony(pcs,cells[:-1],batches,config,72)


def test_isolated_worker_runs_harmony_regression_exports_and_preserves_counts(tmp_path):
    from app.adapters.bio_engine.manifest import Writer
    rng=np.random.default_rng(72);counts=rng.poisson(3,(120,60)).astype('int64');counts[:60,:15]+=rng.poisson(3,(60,15))
    counts=sparse.csr_matrix(counts);cells=[f'cell{i}' for i in range(120)];genes=[f'g{i}' for i in range(60)]
    source=tmp_path/'source';source.mkdir();writer=Writer(source)
    writer.matrix('matrix',counts);writer.json('features_index',dict(feature_ids=genes,feature_symbols=genes,feature_types=['Gene Expression']*60))
    writer.json('barcodes_index',dict(barcodes=cells));writer.json('observation_map_index',dict(rows=[dict(barcode=c,library_id='L1' if i<60 else 'L2',batch=dict(status='known',value='b1' if i<60 else 'b2'),group=dict(status='known',value='healthy')) for i,c in enumerate(cells)]))
    output=tmp_path/'output';output.mkdir()
    payload=dict(mode='compute',raw=dict(manifest=dict(assay='single_cell',input_shape=dict(observations=120,features=60)),members={m['key']:m for m in writer.artifacts}),
        config=dict(seed=72,min_spots=1,hvg_count=24,pca_components=8,hvg_batch_key='batch',technical_covariates=['log1p_total_counts'],harmony=dict(enabled=True,batch_key='batch',theta=2,**{'lambda':1},max_iter=10)),output_directory=str(output))
    body=json.dumps(payload).encode();worker=Path(__file__).resolve().parents[2]/'app/adapters/bio_engine/worker.py'
    completed=subprocess.run([sys.executable,'-I','-B',str(worker),str(os.getpid())],input=struct.pack('!I',len(body))+body,env={},capture_output=True,timeout=420)
    (tmp_path/'worker.stderr.txt').write_bytes(completed.stderr)
    assert completed.returncode==0,completed.stderr.decode()
    result=json.loads(completed.stdout.split(b'\n',1)[1]);assert 'error' not in result,completed.stderr.decode()
    result=result['result'];state=result['summary']['single_cell_integration']
    from app.adapters.bio_analysis_process import validate_engine_result,validate_processed_arrays
    assert validate_engine_result(result,output,mode='compute',max_output_bytes=1024**3) is result
    assert validate_processed_arrays(result['outputs'])['observations']==120
    assert state['technical_covariates']['applied'] and state['harmony']['applied'],state
    assert state['downstream_representation']=='X_pca_harmony'
    assert result['manifest']['resources']['rss_limit_bytes']==4*1024**3
    members={m['key']:m for m in result['outputs']}
    import anndata as ad
    obj=ad.read_h5ad(members['processed']['path'])
    assert obj.obs_names.tolist()==cells and (obj.layers['counts']!=counts).nnz==0
    assert set(obj.obsm)>={'X_pca','X_pca_unadjusted','X_pca_harmony'}
    np.testing.assert_array_equal(obj.obsm['X_pca_harmony'],np.load(members['integration_x_pca_harmony']['path']))
    assert 'integration_harmony_png' in members and 'integration_covariates_png' in members
    assert not any(m['format']=='pdf' for m in result['outputs'])
