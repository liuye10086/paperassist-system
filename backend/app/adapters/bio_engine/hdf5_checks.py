"""Bounded 10x v3 /matrix reader. No generic HDF5 import or layer inference."""
import hashlib
import os
os.environ['HDF5_PLUGIN_PRELOAD']='::'
import h5py
import numpy as np
from scipy import sparse


def inspect_hdf5(handle,limits=None):
    """Check metadata before reads; vlen byte limits are checked after each scalar read."""
    while h5py.h5pl.size():h5py.h5pl.remove(0)
    budget=[0,0];seen=set()
    maximum=min(512*1024**2,limits.max_expanded_bytes) if limits else 512*1024**2
    def visit(group,depth=0):
        if depth>8:raise ValueError('h5_depth_limit')
        address=h5py.h5o.get_info(group.id).addr
        if address in seen:raise ValueError('h5_cycle_or_alias')
        seen.add(address)
        for key in group:
            budget[0]+=1
            if budget[0]>256:raise ValueError('h5_object_limit')
            if not isinstance(group.get(key,getlink=True),h5py.HardLink):raise ValueError('h5_link_rejected')
            obj=group[key]
            if isinstance(obj,h5py.Group):visit(obj,depth+1)
            elif isinstance(obj,h5py.Dataset):
                if obj.is_virtual or obj.external:raise ValueError('h5_external_storage')
                if obj.size>10_100_001 or obj.dtype.itemsize>4096:raise ValueError('h5_shape_limit')
                prop=obj.id.get_create_plist()
                if any(prop.get_filter(i)[0] not in {1,2,3} for i in range(prop.get_nfilters())):raise ValueError('h5_unknown_filter')
                string=h5py.check_string_dtype(obj.dtype)
                vlen_string=obj.dtype.kind=='O' and string is not None and string.encoding in ('utf-8','ascii')
                if obj.dtype.kind not in 'biufS' and not vlen_string:raise ValueError('h5_unbounded_or_unsupported_dtype')
                if vlen_string:
                    # Only text axes are decoded, never arbitrary object/reference.
                    if obj.ndim!=1 or obj.size>100000:raise ValueError('h5_string_axis_limit')
                    # h5py allocates one vlen value before its length can be checked.
                    # This is a post-read logical limit, not a native allocation cap;
                    # the existing isolated process memory limit remains necessary.
                    for index in range(obj.size):
                        value=obj[index]
                        if not isinstance(value,(bytes,str)):raise ValueError('h5_string_length_limit')
                        size=len(value.encode('utf-8') if isinstance(value,str) else value)
                        if size>4096:raise ValueError('h5_string_length_limit')
                        budget[1]+=size
                        if budget[1]>maximum:raise ValueError('h5_logical_size')
                budget[1]+=obj.size*obj.dtype.itemsize
                if budget[1]>maximum:raise ValueError('h5_logical_size')
            else:raise ValueError('h5_object_type')
    visit(handle)
    return budget


def integer_counts(value):
    if value.dtype.kind not in 'iuf' or not np.isfinite(value).all() or np.any(value<0) or np.any(value!=np.floor(value)) or (value.size and (value.max()>=2**63 or sum(map(int,value))>np.iinfo(np.int64).max)):
        raise ValueError('h5_counts_nonnegative_integer_required')
    return value.astype('int64')


def read_h5ad_counts(path,selection,limits=None):
    """Controlled sparse CSR/CSC only. raw.X uses raw/var, never main var."""
    from app.domain.bioinformatics.single_cell_contracts import H5adSelection
    selected=H5adSelection.model_validate(selection)
    while h5py.h5pl.size():h5py.h5pl.remove(0)
    with h5py.File(path,'r') as handle:
        budget=inspect_hdf5(handle,limits)
        matrix_path='raw/X' if selected.matrix=='raw.X' else selected.matrix
        var_path='raw/var' if selected.matrix=='raw.X' else 'var'
        if matrix_path not in handle or var_path not in handle or 'obs' not in handle:raise ValueError('h5ad_selected_matrix_or_axes_missing')
        group=handle[matrix_path]
        if not isinstance(group,h5py.Group):raise ValueError('h5ad_sparse_counts_required')
        encoding=group.attrs.get('encoding-type')
        if isinstance(encoding,bytes):encoding=encoding.decode()
        if encoding not in ('csr_matrix','csc_matrix') or set(group)!={'data','indices','indptr'}:raise ValueError('h5ad_sparse_encoding')
        shape=tuple(group.attrs.get('shape',()))
        max_obs=min(20000,limits.max_observations) if limits else 20000
        max_var=min(100000,limits.max_features) if limits else 100000
        max_nnz=min(10000000,limits.max_entries) if limits else 10000000
        if len(shape)!=2 or any(type(v) not in (int,np.int64,np.int32) for v in shape) or not (0<shape[0]<=max_obs and 0<shape[1]<=max_var):raise ValueError('h5ad_shape')
        def read(dataset):
            if not isinstance(dataset,h5py.Dataset) or dataset.ndim!=1:raise ValueError('h5_rank')
            result=np.empty(dataset.shape,dtype=dataset.dtype)
            for i in range(0,dataset.size,65536):result[i:i+65536]=dataset[i:i+65536]
            return result
        if group['data'].size>max_nnz:raise ValueError('h5ad_entries_limit')
        original=read(group['data']);data=integer_counts(original);indices=read(group['indices']);ptr=read(group['indptr'])
        major=shape[0] if encoding=='csr_matrix' else shape[1];minor=shape[1] if encoding=='csr_matrix' else shape[0]
        if indices.dtype.kind not in 'iu' or ptr.dtype.kind not in 'iu' or len(ptr)!=major+1 or len(indices)!=len(data) or ptr[0]!=0 or ptr[-1]!=len(data) or np.any(ptr[1:]<ptr[:-1]) or np.any(indices<0) or np.any(indices>=minor):raise ValueError('h5ad_sparse_indices')
        def strings(axis,column,size):
            if column not in axis:raise ValueError('h5ad_selected_axis_missing')
            values=read(axis[column])
            string=h5py.check_string_dtype(values.dtype)
            if (values.dtype.kind!='S' and not (values.dtype.kind=='O' and string is not None and string.encoding in ('utf-8','ascii'))) or len(values)!=size:raise ValueError('h5ad_axis_encoding')
            result=[v if isinstance(v,str) else bytes(v).decode('utf-8','strict') for v in values]
            if any(not v or len(v)>200 or any(ord(c)<32 for c in v) for v in result):raise ValueError('h5ad_axis_value')
            return result
        cells=strings(handle['obs'],selected.obs_index,shape[0]);ids=strings(handle[var_path],selected.var_index,shape[1])
        symbols=strings(handle[var_path],selected.symbol_column,shape[1]) if selected.symbol_column else ids.copy()
        if len(set(cells))!=len(cells) or len(set(ids))!=len(ids):raise ValueError('h5ad_axes_unique')
        constructor=sparse.csr_matrix if encoding=='csr_matrix' else sparse.csc_matrix
        matrix=constructor((data,indices.astype('int32'),ptr.astype('int64')),shape=shape).tocsr()
        matrix.sum_duplicates();matrix.eliminate_zeros();matrix.sort_indices()
        return matrix,dict(feature_ids=ids,feature_symbols=symbols,feature_types=['Gene Expression']*len(ids)),cells,dict(format='h5ad_sparse_counts_v1',selected_matrix=selected.matrix,var_axis=var_path,obs_axis='obs',float_integer_counts_converted=original.dtype.kind=='f',checked_objects=budget[0],logical_bytes=budget[1])


def read_10x(path,limits=None):
    # Disable dynamic native filter/plugin loading even if parent environment differs.
    while h5py.h5pl.size(): h5py.h5pl.remove(0)
    max_features=min(100000,limits.max_features) if limits else 100000
    max_observations=min(20000,limits.max_observations) if limits else 20000
    max_entries=min(10000000,limits.max_entries) if limits else 10000000
    logical_limit=min(512*1024**2,limits.max_expanded_bytes) if limits else 512*1024**2
    with h5py.File(path,'r') as handle:
        budget=inspect_hdf5(handle,limits)
        if 'matrix' not in handle: raise ValueError('h5_not_10x_v3')
        group=handle['matrix']
        required=['data','indices','indptr','shape','barcodes','features/id','features/name','features/feature_type']
        if any(key not in group for key in required): raise ValueError('h5_10x_members_missing')
        def read(key,integer=False):
            dataset=group[key]
            if len(dataset.shape)!=1: raise ValueError('h5_rank')
            if integer and dataset.dtype.kind not in 'iu': raise ValueError('h5_integer_dtype')
            # Fixed-width arrays are bounded by preflight; vlen text was checked scalar by scalar.
            result=np.empty(dataset.shape,dtype=dataset.dtype)
            for i in range(0,dataset.size,65536): result[i:i+65536]=dataset[i:i+65536]
            return result
        shape=read('shape',True)
        if len(shape)!=2 or not(0<shape[0]<=max_features and 0<shape[1]<=max_observations): raise ValueError('h5_matrix_shape')
        if group['data'].size>max_entries or group['indices'].size>max_entries or group['indptr'].size>max_observations+1:raise ValueError('h5_matrix_size_limit')
        original_data=read('data'); data=integer_counts(original_data); indices=read('indices',True); indptr=read('indptr',True)
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
