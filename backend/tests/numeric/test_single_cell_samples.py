import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from scipy import sparse

from app.adapters.bio_engine.single_cell import import_counts


def library(tmp_path, name, genes, values):
    root = tmp_path / name
    root.mkdir()
    contents = {
        'matrix.mtx': '%%MatrixMarket matrix coordinate integer general\n2 2 4\n' +
            ''.join(f'{gene + 1} {cell + 1} {values[cell][gene]}\n' for cell in range(2) for gene in range(2)),
        'features.tsv': ''.join(f'{gene}\t{gene}\tGene Expression\n' for gene in genes),
        'barcodes.tsv': 'AA\nBB\n',
    }
    files = []
    for filename, content in contents.items():
        path = root / filename
        path.write_text(content, encoding='utf-8')
        body = path.read_bytes()
        files.append(dict(id=name + '-' + filename, filename=filename, path=str(path),
                          size_bytes=len(body), sha256=hashlib.sha256(body).hexdigest()))
    return files


def payload(tmp_path, files, samples):
    return dict(files=files, output_directory=str(tmp_path / 'output'), single_cell_config=dict(
        workflow_version='bio_import_v4', assay='single_cell', name='multi', expected_dataset_revision=0,
        matrix_representation='mtx', file_ids=[f['id'] for f in files], samples=samples))


def test_libraries_align_gene_ids_namespace_cells_and_keep_metadata(tmp_path):
    a = library(tmp_path, 'a', ['g1', 'g2'], [[1, 2], [3, 4]])
    b = library(tmp_path, 'b', ['g2', 'g1'], [[5, 6], [7, 8]])
    samples = [dict(sample_id='S1', library_id='L1', donor='D1', group='control', batch='B1', species_taxon_id=9606,reference_id='GRCh38',reference_version='2024-A',library_chemistry='3prime-v3',pair_id='P1',file_ids=[f['id'] for f in a]),
               dict(sample_id='S2', library_id='L2', file_ids=[f['id'] for f in b])]
    result = import_counts(payload(tmp_path, a + b, samples))
    leaves = {m['key']: m for m in result['outputs']}
    matrix = sparse.csr_matrix(tuple(np.load(leaves[k]['path'], allow_pickle=False)
                                    for k in ('matrix_data', 'matrix_indices', 'matrix_indptr')), shape=(4, 2))
    np.testing.assert_array_equal(matrix.toarray(), [[1, 2], [3, 4], [6, 5], [8, 7]])
    assert int(matrix.sum()) == 36
    rows = json.loads(Path(leaves['observation_map_index']['path']).read_text())['rows']
    assert [r['barcode'] for r in rows] == ['L1:AA', 'L1:BB', 'L2:AA', 'L2:BB']
    assert rows[0]['original_barcode'] == 'AA' and rows[0]['library_id'] == 'L1'
    assert rows[0]['sample_id'] == {'status': 'known', 'value': 'S1'}
    assert rows[0]['donor']['value'] == 'D1' and rows[-1]['donor']['status'] == 'pending'
    assert result['manifest']['verification']['study_design'] == 'pending'
    assert len(result['manifest']['samples']) == 2
    assert result['manifest']['samples'][0]['species_taxon_id']==9606
    assert rows[0]['reference_version']=={'status':'known','value':'2024-A'}
    assert rows[-1]['species_taxon_id']=={'status':'pending','value':None}


def test_libraries_do_not_merge_different_gene_sets(tmp_path):
    a = library(tmp_path, 'a', ['g1', 'g2'], [[1, 2], [3, 4]])
    b = library(tmp_path, 'b', ['g2', 'g3'], [[5, 6], [7, 8]])
    samples = [dict(sample_id=name, library_id=name, file_ids=[f['id'] for f in files])
               for name, files in [('a', a), ('b', b)]]
    with pytest.raises(ValueError, match='sample_gene_set_mismatch'):
        import_counts(payload(tmp_path, a + b, samples))


def test_manifest_requires_each_file_exactly_once(tmp_path):
    from pydantic import ValidationError
    from app.domain.bioinformatics.single_cell_contracts import SingleCellImportRequest
    a = library(tmp_path, 'a', ['g1', 'g2'], [[1, 2], [3, 4]])
    sample = dict(sample_id='s', library_id='l', file_ids=[a[0]['id']])
    with pytest.raises(ValidationError, match='sample_files'):
        SingleCellImportRequest.model_validate(payload(tmp_path, a, [sample])['single_cell_config'])


@pytest.mark.parametrize('manual_mapping',[False,True])
def test_multi_sample_full_compute_retains_counts_metadata_and_png(tmp_path,manual_mapping):
    import anndata as ad
    import pandas as pd
    from app.adapters.bio_engine.pipeline import run
    rng = np.random.default_rng(9)
    counts = rng.poisson(3, (48, 24)).astype('int64')
    counts[:24, :8] += 6
    counts[24:, 8:16] += 6
    files = []
    samples = []
    for number in range(2):
        path = tmp_path / f'sample{number}.h5ad'
        ad.AnnData(sparse.csr_matrix(counts[number*24:(number+1)*24]),
                   obs=pd.DataFrame(index=[f'cell{i}' for i in range(24)]),
                   var=pd.DataFrame(index=[f'g{i}' for i in range(24)])).write_h5ad(path)
        content = path.read_bytes()
        files.append(dict(id=str(number), filename=path.name, path=str(path),
                          size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest()))
        samples.append(dict(sample_id=f'S{number}', library_id=f'L{number}', donor=f'D{number}',
                            group='control' if number == 0 else 'treated',species_taxon_id=9606,reference_id='GRCh38',reference_version='v1',library_chemistry='v3',pair_id='P1', file_ids=[str(number)]))
    request = payload(tmp_path, files, samples)
    request['single_cell_config'].update(matrix_representation='h5ad', h5ad=dict(matrix='X', obs_index='_index', var_index='_index'))
    imported = import_counts(request)
    raw = dict(manifest=imported['manifest'], members={m['key']: m for m in imported['outputs']})
    if manual_mapping:
        original = raw['members']['observation_map_index']
        raw['members']['import_observation_map_index'] = original
        rows = json.loads(Path(original['path']).read_bytes())['rows']
        for row in rows:
            row.pop('library_id'); row.pop('original_barcode')
            for field in ('species_taxon_id','reference_id','reference_version','library_chemistry','pair_id'):row.pop(field,None)
            row['donor'] = dict(status='known', value='reviewed-donor')
        body = json.dumps(dict(rows=rows)).encode()
        path = tmp_path / 'reviewed_mapping.json'
        path.write_bytes(body)
        raw['members']['observation_map_index'] = {**original,'path':str(path),'sha256':hashlib.sha256(body).hexdigest(),'size_bytes':len(body)}
    out = tmp_path / 'analysis'
    out.mkdir()
    result = run(dict(raw=raw, output_directory=str(out), mode='compute',
                      config=dict(in_tissue_only=False, min_counts=1, min_genes=1, min_spots=1, hvg_count=16,
                                  pca_components=5, neighbors=5, seed=9, resolution=0.8), identity={}))
    assert result['summary']['raw_observations'] == result['summary']['retained_observations'] == 48
    h5ad_member = next(m for m in result['outputs'] if m['format'] == 'h5ad')
    restored = ad.read_h5ad(h5ad_member['path'])
    np.testing.assert_array_equal(restored.layers['counts'].toarray(), counts)
    assert restored.obs['sample_id'].tolist() == ['S0'] * 24 + ['S1'] * 24
    assert restored.obs['library_id'].tolist() == ['L0'] * 24 + ['L1'] * 24
    assert restored.obs['original_barcode'].tolist() == [f'cell{i}' for i in range(24)] * 2
    assert restored.obs['donor'].tolist() == (['reviewed-donor'] * 48 if manual_mapping else ['D0'] * 24 + ['D1'] * 24)
    assert restored.obs['species_taxon_id'].astype(str).tolist()==['9606']*48
    assert restored.obs['reference_id'].tolist()==['GRCh38']*48
    assert restored.obs['pair_id'].tolist()==['P1']*48
    assert result['manifest']['samples']==imported['manifest']['samples']
    assert result['manifest']['resource_estimate']['hvg_count']==16
    assert not any(m['format'] == 'pdf' for m in result['outputs'])
    assert any(m['key'] == 'umap_png' for m in result['outputs'])
    assert result['summary']['replicate_consistency']['status'] == 'not_computable'
