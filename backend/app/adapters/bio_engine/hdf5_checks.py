"""Bounded 10x v3 /matrix reader. No generic HDF5 import or layer inference."""
import hashlib
import os
os.environ['HDF5_PLUGIN_PRELOAD']='::'
import h5py
import numpy as np
from scipy import sparse


def read_10x(path,limits=None):
    # Disable dynamic native filter/plugin loading even if parent environment differs.
    while h5py.h5pl.size(): h5py.h5pl.remove(0)
    max_features=min(100000,limits.max_features) if limits else 100000
    max_observations=min(20000,limits.max_observations) if limits else 20000
    max_entries=min(10000000,limits.max_entries) if limits else 10000000
    logical_limit=min(512*1024**2,limits.max_expanded_bytes) if limits else 512*1024**2
    with h5py.File(path,'r') as handle:
        budget=[0,0]
        def inspect(group,depth=0):
            if depth>8: raise ValueError('h5_depth_limit')
            for key in group:
                budget[0]+=1
                if budget[0]>64: raise ValueError('h5_object_limit')
                if not isinstance(group.get(key,getlink=True),h5py.HardLink): raise ValueError('h5_link_rejected')
                obj=group[key]
                if isinstance(obj,h5py.Group): inspect(obj,depth+1)
                elif isinstance(obj,h5py.Dataset):
                    if obj.is_virtual or obj.external: raise ValueError('h5_external_storage')
                    if obj.size>10_100_001: raise ValueError('h5_shape_limit')
                    if obj.dtype.kind=='O': raise ValueError('h5_unbounded_vlen_string')
                    budget[1]+=obj.size*obj.dtype.itemsize
                    if budget[1]>logical_limit or obj.dtype.itemsize>4096: raise ValueError('h5_logical_size')
                    properties=obj.id.get_create_plist()
                    for i in range(properties.get_nfilters()):
                        if properties.get_filter(i)[0] not in {1,2,3}: raise ValueError('h5_unknown_filter')
                else: raise ValueError('h5_object_type')
        inspect(handle)
        if 'matrix' not in handle: raise ValueError('h5_not_10x_v3')
        group=handle['matrix']
        required=['data','indices','indptr','shape','barcodes','features/id','features/name','features/feature_type']
        if any(key not in group for key in required): raise ValueError('h5_10x_members_missing')
        def read(key,integer=False):
            dataset=group[key]
            if len(dataset.shape)!=1: raise ValueError('h5_rank')
            if integer and dataset.dtype.kind not in 'iu': raise ValueError('h5_integer_dtype')
            # Bounded slice allocation after full metadata preflight, not dataset[()].
            result=np.empty(dataset.shape,dtype=dataset.dtype)
            for i in range(0,dataset.size,65536): result[i:i+65536]=dataset[i:i+65536]
            return result
        shape=read('shape',True)
        if len(shape)!=2 or not(0<shape[0]<=max_features and 0<shape[1]<=max_observations): raise ValueError('h5_matrix_shape')
        if group['data'].size>max_entries or group['indices'].size>max_entries or group['indptr'].size>max_observations+1:raise ValueError('h5_matrix_size_limit')
        data=read('data',True); indices=read('indices',True); indptr=read('indptr',True)
        if len(data)>10000000 or len(data)!=len(indices) or len(indptr)!=shape[1]+1: raise ValueError('h5_matrix_size')
        if indptr[0]!=0 or indptr[-1]!=len(data) or np.any(indptr[1:]<indptr[:-1]): raise ValueError('h5_pointer')
        if np.any(indices>=shape[0]) or np.any(indices<0) or np.any(data<0): raise ValueError('h5_count_or_index')
        if data.size and (int(data.max())>np.iinfo(np.int64).max or sum(map(int,data))>np.iinfo(np.int64).max): raise ValueError('h5_count_overflow')
        def strings(key):
            value=read(key)
            if value.dtype.kind!='S': raise ValueError('h5_string_dtype')
            return [bytes(s).decode('utf-8','strict') for s in value]
        barcodes=strings('barcodes')
        features={k:strings(v) for k,v in [('feature_ids','features/id'),('feature_symbols','features/name'),('feature_types','features/feature_type')]}
        if len(barcodes)!=shape[1] or any(len(v)!=shape[0] for v in features.values()): raise ValueError('h5_axes_shape')
        if len(set(barcodes))!=len(barcodes) or len(set(features['feature_ids']))!=len(features['feature_ids']): raise ValueError('h5_axes_unique')
        matrix=sparse.csc_matrix((data.astype('int64'),indices.astype('int32'),indptr.astype('int64')),shape=tuple(shape)).T.tocsr()
        original_nnz=matrix.nnz; matrix.sum_duplicates(); matrix.eliminate_zeros(); matrix.sort_indices()
        if np.any(matrix.data<0): raise ValueError('h5_count_overflow')
        return matrix,features,barcodes,{'format':'10x_v3_matrix','checked_objects':budget[0],
                                      'logical_bytes':budget[1],'input_entries':original_nnz,'canonical_entries':matrix.nnz}


def compare(left,left_features,left_barcodes,right,right_features,right_barcodes):
    lf=left_features['feature_ids']; rf=right_features['feature_ids']
    if set(lf)!=set(rf) or set(left_barcodes)!=set(right_barcodes): return {'status':'not_comparable','reason':'axis_set_mismatch'}
    ri={v:i for i,v in enumerate(rf)}; rb={v:i for i,v in enumerate(right_barcodes)}
    fp=[ri[v] for v in lf]; bp=[rb[v] for v in left_barcodes]
    if any(left_features['feature_types'][i]!=right_features['feature_types'][j] for i,j in enumerate(fp)):
        return {'status':'not_comparable','reason':'feature_type_mismatch'}
    canonical=right[bp][:,fp].tocsr(); canonical.sum_duplicates(); canonical.eliminate_zeros(); canonical.sort_indices()
    left=left.copy();left.sum_duplicates();left.eliminate_zeros();left.sort_indices()
    equal=(left!=canonical).nnz==0
    same=lf==rf and left_barcodes==right_barcodes
    return {'status':('identical' if same else 'order_reindexed_equal') if equal else 'mismatch',
            'feature_permutation':fp,'barcode_permutation':bp,'comparator_version':'csr_all_values_v1',
            'counts_total_left':int(left.sum()),'counts_total_right':int(canonical.sum())}
