"""The trusted parent validates bytes instead of trusting a child success flag."""
import hashlib
import importlib
import json
from pathlib import Path

import numpy as np
import pytest

from app.core.exceptions import StorageError


def validator():
    return importlib.import_module('app.adapters.bio_analysis_process').validate_artifacts


def entry(path, *, key='values', fmt='npy'):
    content = path.read_bytes()
    return dict(key=key, path=str(path.resolve()), role=key, format=fmt,
                size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest())


def test_parent_accepts_exact_finite_registered_numpy_leaf(tmp_path):
    path = tmp_path / 'values.npy'
    np.save(path, np.array([1., 2.], dtype='float32'), allow_pickle=False)
    outputs = [entry(path)]
    assert validator()(outputs, tmp_path) == outputs


@pytest.mark.parametrize('failure', ['changed_bytes', 'wrong_size', 'outside', 'extra_leaf', 'nonfinite', 'object_array'])
def test_parent_rejects_corrupt_or_unregistered_child_output(tmp_path, failure):
    output = tmp_path / 'output'
    output.mkdir()
    path = output / 'values.npy'
    np.save(path, np.array([1., 2.], dtype='float32'), allow_pickle=False)
    record = entry(path)
    if failure == 'changed_bytes':
        path.write_bytes(b'x' * record['size_bytes'])
    elif failure == 'wrong_size':
        record['size_bytes'] += 1
    elif failure == 'outside':
        other = tmp_path / 'values.npy'
        other.write_bytes(path.read_bytes())
        path.unlink()
        record = entry(other)
    elif failure == 'extra_leaf':
        (output / 'unregistered.txt').write_text('extra', encoding='utf-8')
    elif failure == 'nonfinite':
        np.save(path, np.array([np.nan]), allow_pickle=False)
        record = entry(path)
    else:
        np.save(path, np.array([{'not': 'numeric'}], dtype=object), allow_pickle=True)
        record = entry(path)
    with pytest.raises(StorageError) as raised:
        validator()([record], output)
    assert raised.value.code == 'bio_output_invalid'


def test_parent_rejects_duplicate_output_identity(tmp_path):
    path = tmp_path / 'values.npy'
    np.save(path, np.array([1], dtype='int64'), allow_pickle=False)
    record = entry(path)
    with pytest.raises(StorageError) as raised:
        validator()([record, record], tmp_path)
    assert raised.value.code == 'bio_output_invalid'


def test_large_axis_metadata_is_a_leaf_not_the_two_megabyte_transport(tmp_path):
    path = tmp_path / 'raw_axes.json'
    path.write_text(json.dumps({'feature_ids': ['ENSG' + str(i).zfill(12) for i in range(100000)],
                               'feature_types': ['Gene Expression'] * 100000}), encoding='utf-8')
    assert path.stat().st_size > 2 * 1024**2
    outputs = [entry(path, key='raw_axes', fmt='json')]
    assert validator()(outputs, tmp_path) == outputs


def test_parent_rejects_ambiguous_json_members(tmp_path):
    path = tmp_path / 'manifest.json'
    path.write_text('{"shape":[10,4],"shape":[1,1]}', encoding='utf-8')
    with pytest.raises(StorageError) as raised:
        validator()([entry(path, key='manifest', fmt='json')], tmp_path)
    assert raised.value.code == 'bio_output_invalid'


def processed_arrays(root, mutation=None):
    outputs = []
    values = {'observation_mask': np.ones(6, dtype=bool), 'feature_mask': np.ones(3, dtype=bool),
              'pca': np.zeros((6, 2), dtype='float32'), 'umap': np.zeros((6, 2), dtype='float32'),
              'hvg_mask': np.ones(3, dtype=bool)}
    for layer in ['counts', 'normalized', 'log1p']:
        values[layer + '_data'] = (np.arange(1, 7, dtype='int64') if layer == 'counts' else
                                  np.full(6, 10000 if layer == 'normalized' else np.log1p(10000), dtype='float32'))
        values[layer + '_indices'] = np.array([0, 1, 2, 0, 1, 2], dtype='int32')
        values[layer + '_indptr'] = np.arange(7, dtype='int64')
    if mutation == 'csr':
        values['counts_indptr'][-1] = 30
    elif mutation == 'axes':
        values['feature_mask'] = np.ones(4, dtype=bool)
    elif mutation == 'embedding':
        values['umap'] = np.zeros((5, 2), dtype='float32')
    elif mutation == 'log':
        values['log1p_data'][2] = 0
    for key, array in values.items():
        path = root / (key + '.npy')
        np.save(path, array, allow_pickle=False)
        outputs.append(entry(path, key=key))
    axes = root / 'raw_axes.json'
    axes.write_text(json.dumps({'barcodes': [f'b{i}' for i in range(6)], 'feature_ids': ['g1', 'g2', 'g3'],
                                'feature_symbols': ['SAME', 'SAME', 'THIRD'],
                                'feature_types': ['Gene Expression'] * 3}), encoding='utf-8')
    outputs.append(entry(axes, key='raw_axes', fmt='json'))
    return outputs


def test_parent_reconciles_processed_axes_and_sparse_layer_semantics(tmp_path):
    outputs = processed_arrays(tmp_path)
    validate = importlib.import_module('app.adapters.bio_analysis_process').validate_processed_arrays
    assert validate(outputs) == {'observations': 6, 'features': 3, 'nnz': 6}


@pytest.mark.parametrize('mutation', ['csr', 'axes', 'embedding', 'log'])
def test_parent_rejects_inconsistent_scientific_arrays_even_with_correct_hashes(tmp_path, mutation):
    outputs = processed_arrays(tmp_path, mutation)
    validate = importlib.import_module('app.adapters.bio_analysis_process').validate_processed_arrays
    with pytest.raises(StorageError) as raised:
        validate(outputs)
    assert raised.value.code == 'bio_output_invalid'
