"""New entrypoints must execute after the existing Linux isolation boundary."""
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

pytestmark=pytest.mark.skipif(sys.platform!='linux',reason='Linux production isolation')


def invoke(payload,tmp_path):
    body=json.dumps(payload).encode();worker=Path(__file__).resolve().parents[2]/'app/adapters/bio_engine/worker.py'
    result=subprocess.run([sys.executable,'-I','-B',str(worker),str(os.getpid())],input=struct.pack('!I',len(body))+body,env={},capture_output=True,timeout=240)
    (tmp_path/'child.stderr').write_bytes(result.stderr)
    assert result.returncode==0,result.stderr.decode()
    response=json.loads(result.stdout.split(b'\n',1)[1])
    assert 'error' not in response,result.stderr.decode()
    return response['result']


def test_single_r_reference_worker_isolation(tmp_path):
    from app.adapters.bio_engine.manifest import Writer
    from app.adapters.single_cell_r.annotation import REFERENCE_ROOT,REFERENCE_ID
    metadata=json.loads((REFERENCE_ROOT/REFERENCE_ID/'reference.json').read_text())
    genes=metadata['gene_ids'][:500];cells=[f'c{i}' for i in range(12)]
    source=tmp_path/'source';source.mkdir();writer=Writer(source)
    writer.json('raw_axes',dict(barcodes=cells,feature_ids=genes,feature_symbols=genes,feature_types=['Gene Expression']*len(genes)))
    writer.array('observation_mask',np.ones(12,dtype=bool));writer.array('feature_mask',np.ones(len(genes),dtype=bool))
    values=np.log1p(np.random.default_rng(4).poisson(3,(12,len(genes)))).astype('float32');writer.matrix('log1p',sparse.csr_matrix(values))
    output=tmp_path/'output';output.mkdir()
    result=invoke(dict(mode='annotation',raw=dict(manifest={'assay':'single_cell'},members={}),processed=dict(manifest={'assay':'single_cell'},members={m['key']:m for m in writer.artifacts}),
        config=dict(reference_id=REFERENCE_ID,species='Homo sapiens',gene_id_type='ensembl_gene_id',label_level='main',seed=0),identity={},output_directory=str(output)),tmp_path)
    assert result['summary']['cells']==12 and result['manifest']['tool_version']=='2.8.0'


def test_subset_worker_inherits_without_reading_code_after_isolation(tmp_path):
    from app.adapters.bio_engine.manifest import Writer
    from app.adapters.bio_engine.pipeline import run
    from tests.numeric.test_single_cell_batch3_algorithms import sample
    counts,_,genes,batches=sample();cells=[f'cell{i}' for i in range(80)]
    source=tmp_path/'source';source.mkdir();w=Writer(source)
    w.matrix('matrix',counts);w.json('features_index',dict(feature_ids=genes,feature_symbols=genes,feature_types=['Gene Expression']*36));w.json('barcodes_index',dict(barcodes=cells))
    w.json('observation_map_index',dict(rows=[dict(barcode=c,library_id=b) for c,b in zip(cells,batches)]))
    raw=dict(manifest=dict(assay='single_cell',input_shape=dict(observations=80,features=36)),members={m['key']:m for m in w.artifacts})
    config=dict(min_spots=1,hvg_count=12,pca_components=6,harmony=dict(enabled=False))
    parent_dir=tmp_path/'parent';parent_dir.mkdir();parent=run(dict(mode='compute',raw=raw,config=config,output_directory=str(parent_dir)))
    output=tmp_path/'output';output.mkdir()
    result=invoke(dict(mode='compute',raw=raw,config=config,output_directory=str(output),processed=dict(manifest=parent['manifest'],members={m['key']:m for m in parent['outputs']}),
        subset=dict(parent_processed_source=dict(processed_dataset_version_id='parent'),cell_ids=cells[:40],cluster_ids=[],resolved_cell_ids=cells[:40])),tmp_path)
    assert result['summary']['subset']['selected_cells']==40 and result['manifest']['subset']['capture_models_rerun'] is False
