"""Small single-cell actual worker transport check, using retained numerical runtime."""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys


def execute(payload):
    body=json.dumps(payload).encode()
    worker=Path('/app/app/adapters/bio_engine/worker.py')
    result=subprocess.run([sys.executable,'-I','-B',str(worker),str(os.getpid())],
        input=struct.pack('!I',len(body))+body,capture_output=True,env={},timeout=300)
    if result.returncode or not result.stdout.startswith(b'READY\n'):
        raise RuntimeError(result.stderr.decode())
    answer=json.loads(result.stdout.split(b'\n',1)[1])
    if 'error' in answer:raise RuntimeError(str(answer)+'\n'+result.stderr.decode())
    return answer['result']


def run(root):
    import anndata as ad
    import numpy as np
    import pandas as pd
    from scipy import sparse
    root=Path(root);root.mkdir(exist_ok=False)
    path=root/'input.h5ad'
    values=sparse.csr_matrix([[1,0,2],[0,3,4],[2,2,1],[1,1,1]],dtype='float64')
    ad.AnnData(values,obs=pd.DataFrame(index=['a','b','c','d']),var=pd.DataFrame(index=['g1','g2','g3'])).write_h5ad(path)
    source=dict(id='probe',filename=path.name,path=str(path),size_bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    config=dict(workflow_version='bio_import_v4',assay='single_cell',file_ids=['probe'],name='cell sandbox probe',expected_dataset_revision=0,matrix_representation='h5ad',h5ad=dict(matrix='X',obs_index='_index',var_index='_index'))
    output=root/'import';output.mkdir()
    imported=execute(dict(mode='import_single_cell',files=[source],single_cell_config=config,settings={},output_directory=str(output)))
    members={v['key']:v for v in imported['outputs']}
    restored=sparse.csr_matrix(tuple(np.load(members[k]['path'],allow_pickle=False) for k in ('matrix_data','matrix_indices','matrix_indptr')),shape=values.shape)
    assert (restored!=values).nnz==0
    qc=root/'qc';qc.mkdir()
    analyzed=execute(dict(mode='qc',raw=dict(manifest=imported['manifest'],members=members),config=dict(min_spots=1),output_directory=str(qc)))
    assert analyzed['manifest']['observation_level']=='cell'
    assert analyzed['summary']['statistical_unit']=='cell_exploratory'
    assert not any('spatial' in v['key'] for v in analyzed['outputs'])
    receipt=dict(checks=dict(actual_single_cell_import=True,actual_nonspatial_qc=True),counts=dict(cells=4,features=3,total=int(values.sum())),evidence_scope='actual production worker Linux sandbox; new H5AD import and nonspatial QC',import_result=imported,qc_result=analyzed)
    (root/'receipt.json').write_text(json.dumps(receipt),encoding='utf-8')
    return {k:v for k,v in receipt.items() if not k.endswith('_result')}


if __name__=='__main__':print(json.dumps(run(sys.argv[1])))
