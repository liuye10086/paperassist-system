"""Small offline cell probe: real AnnData serialization, sparse intake and QC."""
import hashlib
from pathlib import Path
import numpy as np
from scipy import sparse
import anndata as ad
import pandas as pd
from .single_cell import import_counts,aggregate_cells
from .hdf5_checks import read_h5ad_counts
from .pipeline import run


def exercise(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    matrix=sparse.csr_matrix([[1,0,2],[0,3,4],[2,2,1],[1,1,1]])
    path=root/'cells.h5ad'
    obj=ad.AnnData(matrix.astype(float),obs=pd.DataFrame(index=['a','b','c','d']),var=pd.DataFrame(index=['g1','g2','g3']))
    obj.raw=ad.AnnData(sparse.csr_matrix([[7,0],[0,8],[2,1],[4,0]]),obs=obj.obs.copy(),var=pd.DataFrame(index=['raw1','raw2']))
    obj.write_h5ad(path)
    selection=dict(matrix='raw.X',obs_index='_index',var_index='_index')
    raw,features,cells,_=read_h5ad_counts(path,selection)
    if features['feature_ids']!=['raw1','raw2'] or raw.shape!=(4,2) or raw[0,0]!=7:raise ValueError('single_cell_probe_raw_axes')
    source=dict(id='probe',filename='cells.h5ad',path=str(path),size_bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    config=dict(workflow_version='bio_import_v4',assay='single_cell',file_ids=['probe'],name='offline cells',expected_dataset_revision=0,matrix_representation='h5ad',h5ad={**selection,'matrix':'X'})
    imported=import_counts(dict(files=[source],single_cell_config=config,output_directory=str(root/'intake')))
    leaves={v['key']:v for v in imported['outputs']}
    restored=sparse.csr_matrix(tuple(np.load(leaves[k]['path'],allow_pickle=False) for k in ('matrix_data','matrix_indices','matrix_indptr')),shape=matrix.shape)
    if (restored!=matrix).nnz:raise ValueError('single_cell_probe_counts')
    rows=[dict(barcode=c,sample_id='sample1' if i<2 else 'sample2',donor='donor1' if i<2 else 'donor2',group='A' if i<2 else 'B',cluster='0') for i,c in enumerate(cells)]
    aggregate,units,state=aggregate_cells(matrix,rows,design_confirmed=True)
    if state['donors']!=2 or aggregate.shape!=(2,3) or int(aggregate.sum())!=int(matrix.sum()):raise ValueError('single_cell_probe_aggregate')
    (root/'qc').mkdir()
    result=run(dict(raw={'manifest':imported['manifest'],'members':leaves},config={'min_spots':1},mode='qc',output_directory=str(root/'qc')))
    if result['manifest'].get('observation_level')!='cell' or result['summary']['statistical_unit']!='cell_exploratory' or any('spatial' in v['key'] for v in result['outputs']):raise ValueError('single_cell_probe_dispatch')
    return dict(schema_version=1,checks=dict(h5ad_axes=True,counts_equivalence=True,cell_aggregation=True,nonspatial_dispatch=True),counts={'cells':4,'features':3,'counts_total':int(matrix.sum()),'donors':2},raw_axis_features=['raw1','raw2'])
