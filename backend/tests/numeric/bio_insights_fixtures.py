"""Synthetic numerical-only inputs, never customer biological evidence."""
import numpy as np
from scipy import sparse
from app.adapters.bio_engine.manifest import Writer


def source(tmp_path, counts, *, source_id='p1', canonical='dataset1', ids=None, donors=None,
           conditions=None, batches=None, kept=None):
    counts = np.asarray(counts)
    ids = ids or [f'g{i}' for i in range(counts.shape[1])]
    path = tmp_path / source_id; path.mkdir()
    raw_writer = Writer(path)
    raw_writer.matrix('matrix', sparse.csr_matrix(counts))
    raw_writer.json('features_index', {'feature_ids': ids, 'feature_symbols': ids,
                                     'feature_types': ['Gene Expression'] * len(ids)})
    barcodes = [f'b{i}' for i in range(len(counts))]
    raw_writer.json('barcodes_index', {'barcodes': barcodes})
    raw = {'manifest': {'input_shape': {'observations': len(counts), 'features': len(ids)}},
           'members': {a['key']: a for a in raw_writer.artifacts if a['key'] != 'matrix_shape'}}
    output = path / 'processed'; output.mkdir(); w = Writer(output)
    mask = np.ones(len(counts), dtype=bool) if kept is None else np.array(kept, dtype=bool)
    w.array('observation_mask', mask); w.array('feature_mask', np.ones(len(ids), dtype=bool))
    w.json('raw_axes', {'barcodes': barcodes, 'feature_ids': ids, 'feature_symbols': ids,
                       'feature_types': ['Gene Expression'] * len(ids)})
    filtered = counts[mask].astype('float64')
    libraries = filtered.sum(axis=1)
    normalized = np.divide(filtered * 10000, libraries[:, None], out=np.zeros_like(filtered), where=libraries[:, None] > 0)
    w.matrix('normalized', sparse.csr_matrix(normalized))
    w.matrix('log1p', sparse.csr_matrix(np.log1p(normalized)))
    observations = []
    for i, barcode in enumerate(barcodes):
        observations.append({'processed_version_id': source_id, 'barcode': barcode,
                             'donor': None if donors is None else donors[i],
                             'condition': None if conditions is None else conditions[i],
                             'batch': None if batches is None else batches[i]})
    w.table('observations', [{'barcode': b, 'kept': bool(mask[i])} for i, b in enumerate(barcodes)])
    w.json('manifest', {'params': {'target_sum': 10000}})
    return {'source_kind': 'bio_processed_dataset_version', 'source_id': source_id, 'role': 'processed',
            'sha256': 'a' * 64, 'raw': raw, 'members': {a['key']: a for a in w.artifacts},
            'metadata': {'canonical_dataset_id': canonical, 'species_taxon_id': 9606,
                         'namespace': 'ensembl', 'reference_version': 'GRCh38.1', 'observations': observations}}


def config(n=8, *, mode='spot_exploratory', source_id='p1', split=None):
    split = split or n // 2
    group = lambda label, indices: {'label': label, 'observation_keys': [
        {'processed_version_id': source_id, 'barcode': f'b{i}'} for i in indices]}
    return {'kind': 'comparison', 'mode': mode, 'contrasts': [
        {'contrast_id': 'c1', 'name': 'B vs A', 'numerator': group('B', range(split, n)),
         'denominator': group('A', range(split))}], 'family_contrast_ids': ['c1'],
        'species_taxon_id': 9606, 'namespace': 'ensembl', 'reference_version': 'GRCh38.1',
        'mapping_confirmed': mode != 'spot_exploratory', 'independence_confirmed': mode != 'spot_exploratory',
        'independence_basis': 'synthetic fixture', 'minimum_total_counts': 10}


def payload(config, sources):
    return {'schema_version': 1, 'kind': 'bio_'+config['kind'], 'config': config,
            'identity': {'plan_version_id': 'plan1', 'run_id': 'run1'}, 'sources': sources}


def rows(writer, key='comparison_results'):
    import csv
    from pathlib import Path
    item = next(a for a in writer.artifacts if a['key'] == key)
    with Path(item['path']).open(encoding='utf-8', newline='') as stream:
        return list(csv.DictReader(stream, delimiter='\t'))
