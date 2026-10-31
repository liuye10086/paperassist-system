"""File-only verified B04 inputs; no service, database or network imports."""
import csv
import hashlib
import json
from pathlib import Path
import numpy as np
from scipy import sparse


def verify_member(member):
    path = Path(member['path'])
    if (not path.is_absolute() or path.is_symlink() or not path.is_file()
            or type(member['size_bytes']) is not int or not 0 < member['size_bytes'] <= 256 * 1024**2
            or path.stat().st_size != member['size_bytes']):
        raise ValueError('input_member_invalid')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024**2), b''): digest.update(block)
    if digest.hexdigest() != member['sha256']: raise ValueError('input_member_hash_mismatch')
    return path


def document(member):
    def reject(value): raise ValueError('nonfinite_json')
    return json.loads(verify_member(member).read_bytes(), parse_constant=reject)


def read_array(member):
    value = np.load(verify_member(member), allow_pickle=False, mmap_mode='r')
    if not isinstance(value, np.ndarray) or value.dtype.kind not in 'biuf' or value.ndim > 2:
        raise ValueError('array_invalid')
    return value


def read_csr(members, prefix):
    shape = document(members[prefix + '_shape'])['shape']
    if (not isinstance(shape, list) or len(shape) != 2 or any(type(v) is not int or v < 0 for v in shape)
            or shape[0] > 20000 or shape[1] > 100000): raise ValueError('matrix_shape_limit')
    data, indices, ptr = [read_array(members[prefix + '_' + suffix]) for suffix in ['data','indices','indptr']]
    if (data.ndim != 1 or len(data) > 10000000 or not np.isfinite(data).all() or np.any(data < 0)
            or indices.ndim != 1 or ptr.ndim != 1 or indices.dtype.kind not in 'iu' or ptr.dtype.kind not in 'iu'
            or len(indices) != len(data) or len(ptr) != shape[0] + 1 or ptr[0] != 0 or ptr[-1] != len(data)
            or np.any(ptr[1:] < ptr[:-1]) or np.any(indices < 0) or np.any(indices >= shape[1])):
        raise ValueError('csr_invalid')
    matrix = sparse.csr_matrix((data, indices, ptr), shape=tuple(shape)); matrix.check_format(full_check=True)
    if not matrix.has_canonical_format: raise ValueError('csr_not_canonical')
    return matrix


def load_processed(source, mode):
    from app.domain.bio_insights.design import Observation
    members = source['members']; metadata = source['metadata']; sid = source['source_id']
    for member in members.values(): verify_member(member)
    counts, features, barcodes = load_raw(source['raw'])
    if not counts.has_canonical_format: raise ValueError('raw_csr_not_canonical')
    axes = document(members['raw_axes'])
    if axes != {'barcodes': barcodes, **features}: raise ValueError('processed_raw_axis_mismatch')
    mask = read_array(members['observation_mask']); fmask = read_array(members['feature_mask'])
    if (mask.dtype.kind != 'b' or fmask.dtype.kind != 'b' or mask.shape != (len(barcodes),)
            or fmask.shape != (len(features['feature_ids']),)): raise ValueError('mask_invalid')
    table = list(iter_table(members['observations'], format='tsv'))
    if [row['barcode'] for _, row in table] != barcodes: raise ValueError('observation_axis_invalid')
    supplied = metadata.get('observations')
    if supplied is None:
        supplied = []
        for _, row in table:
            value = {'processed_version_id': sid, 'barcode': row['barcode']}
            for old, new in [('donor','donor'),('group','condition'),('batch','batch'),('sample_id','sample'),('section','section')]:
                value[new] = row.get(old) if row.get(old + '_status') == 'known' else None
            supplied.append(value)
    if len(supplied) != len(barcodes): raise ValueError('observation_mapping_axis_invalid')
    by_barcode = {}
    for row in supplied:
        if row['processed_version_id'] != sid or row['barcode'] in by_barcode: raise ValueError('observation_mapping_axis_invalid')
        by_barcode[row['barcode']] = row
    if set(by_barcode) != set(barcodes): raise ValueError('observation_mapping_axis_invalid')
    libraries = np.asarray(counts.sum(axis=1)).ravel()
    observations = [Observation.model_validate({**by_barcode[b], 'retained': bool(mask[i]),
                    'canonical_dataset_id': metadata['canonical_dataset_id'], 'library_counts': int(libraries[i])}).model_dump()
                    for i, b in enumerate(barcodes)]
    gene_mask = np.asarray([kind == 'Gene Expression' for kind in features['feature_types']])
    if mode == 'spot_exploratory':
        normalized = read_csr(members, 'normalized'); logged = read_csr(members, 'log1p')
        expected_shape = (int(mask.sum()), int(fmask.sum()))
        if normalized.shape != expected_shape or logged.shape != expected_shape: raise ValueError('processed_layer_shape_invalid')
        subset = counts[mask][:, fmask].astype('float64')
        totals = np.asarray(subset.sum(1)).ravel()
        target = document(members['manifest'])['params']['target_sum']
        if type(target) not in (int,float) or not np.isfinite(target) or not 0 < target <= 1e6:
            raise ValueError('normalization_target_invalid')
        expected = subset.multiply(np.divide(target, totals, out=np.zeros_like(totals), where=totals>0)[:,None]).tocsr()
        if not _sparse_close(normalized,expected): raise ValueError('normalized_raw_mismatch')
        expected_log = normalized.copy(); expected_log.data = np.log1p(expected_log.data)
        if not _sparse_close(logged,expected_log): raise ValueError('log1p_layer_mismatch')
        eligible = fmask & gene_mask
        retained_feature_indices = np.flatnonzero(eligible[fmask])
        numeric = {'counts': counts[mask][:,eligible].tocsr(), 'normalized': normalized[:,retained_feature_indices],
                   'log1p': logged[:,retained_feature_indices]}
    else:
        eligible = gene_mask
        numeric = {'counts': counts[mask][:,eligible].tocsr()}
    ids = [identifier for identifier, yes in zip(features['feature_ids'], eligible) if yes]
    symbols = {identifier: symbol for identifier, symbol in zip(features['feature_ids'],features['feature_symbols'])}
    return {'source':source, 'observations':observations, 'retained_keys':[(sid,b) for b,yes in zip(barcodes,mask) if yes],
            'feature_ids':ids, 'symbols':symbols, 'raw_feature_ids':features['feature_ids'], **numeric}


def _sparse_close(actual,expected):
    delta=(actual-expected).tocoo()
    if not delta.nnz:return True
    reference=np.asarray(expected[delta.row,delta.col]).ravel()
    return bool(np.all(np.abs(delta.data)<=1e-6+np.abs(reference)*1e-5))


def load_raw(raw):
    """Read the unchanged B01 member contract without importing B02 calculations."""
    members=raw['members']; shape=raw['manifest']['input_shape']
    shape=(shape['observations'],shape['features'])
    if any(type(v) is not int for v in shape) or not 0<shape[0]<=20000 or not 0<shape[1]<=100000:
        raise ValueError('matrix_shape_limit')
    for member in members.values(): verify_member(member)
    data,indices,ptr=[read_array(members['matrix_'+suffix]) for suffix in ['data','indices','indptr']]
    if (data.ndim!=1 or data.dtype.kind not in 'iu' or len(data)>10000000 or np.any(data<0)
            or sum(map(int,data))>np.iinfo(np.int64).max): raise ValueError('raw_counts_invalid')
    if (indices.ndim!=1 or ptr.ndim!=1 or indices.dtype.kind not in 'iu' or ptr.dtype.kind not in 'iu'
            or len(indices)!=len(data) or len(ptr)!=shape[0]+1 or ptr[0]!=0 or ptr[-1]!=len(data)
            or np.any(ptr[1:]<ptr[:-1]) or np.any(indices<0) or np.any(indices>=shape[1])): raise ValueError('raw_csr_invalid')
    matrix=sparse.csr_matrix((data.astype('int64',copy=False),indices,ptr),shape=shape)
    matrix.check_format(full_check=True)
    features=document(members['features_index']); barcodes=document(members['barcodes_index'])['barcodes']
    if (set(features)!={'feature_ids','feature_symbols','feature_types'} or any(len(v)!=shape[1] for v in features.values())
            or len(set(features['feature_ids']))!=shape[1] or len(barcodes)!=shape[0] or len(set(barcodes))!=shape[0]
            or any(not isinstance(v,str) or not v for v in features['feature_ids']+barcodes)):
        raise ValueError('raw_axis_invalid')
    return matrix,features,barcodes


def iter_table(member, format=None, sheet=None, max_uncompressed_bytes=536870912,
               encoding='utf-8-sig', delimiter=None, header_row=1):
    from .tables import iter_table as read_table
    return read_table(member, format=format, sheet=sheet, max_uncompressed_bytes=max_uncompressed_bytes,
                      encoding=encoding, delimiter=delimiter, header_row=header_row)
