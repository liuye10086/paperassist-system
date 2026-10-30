import h5py
import numpy as np
import pytest


def fixture(path):
    with h5py.File(path,'w') as f:
        matrix=f.create_group('matrix')
        for key, value in {'data':[1,2,3], 'indices':[0,1,0], 'indptr':[0,2,3], 'shape':[2,2]}.items(): matrix[key]=value
        matrix['barcodes']=np.asarray(['a','b'],dtype='S')
        features=matrix.create_group('features')
        for key,value in {'id':['g1','g2'], 'name':['A','A'], 'feature_type':['Gene Expression']*2}.items(): features[key]=np.asarray(value,dtype='S')


def test_h5_real_counts_and_reordered_equivalence(tmp_path):
    from app.adapters.bio_engine.hdf5_checks import read_10x, compare
    path=tmp_path/'matrix.h5'; fixture(path)
    matrix,features,barcodes,attestation=read_10x(path)
    np.testing.assert_equal(matrix.toarray(),[[1,2],[3,0]])
    assert compare(matrix,features,barcodes,matrix[::-1,::-1],
                   {key:value[::-1] for key,value in features.items()},barcodes[::-1])['status']=='order_reindexed_equal'


def test_h5_rejects_external_link_before_read(tmp_path):
    from app.adapters.bio_engine.hdf5_checks import read_10x
    path=tmp_path/'evil.h5'; fixture(path)
    with h5py.File(path,'a') as f: f['evil']=h5py.ExternalLink('/etc/passwd','/')
    with pytest.raises(ValueError,match='link'): read_10x(path)
