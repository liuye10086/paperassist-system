import csv
import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pytest

from tests.numeric.test_bio_tabular_assays import payload


def _raw(tmp_path, *, counts=True, matrix=None):
    from app.adapters.bio_engine.tabular_assays import import_tabular

    value = payload(tmp_path, counts=counts)
    if matrix is not None:
        source = value['files'][0]
        contents = matrix.encode('utf-8')
        Path(source['path']).write_bytes(contents)
        source.update(sha256=hashlib.sha256(contents).hexdigest(), size_bytes=len(contents))
    raw_dir = tmp_path / 'raw'
    raw_dir.mkdir()
    value['output_directory'] = str(raw_dir)
    result = import_tabular(value)
    return value, result


def _run(tmp_path, config=None, *, matrix=None):
    from app.adapters.bio_engine.tabular_assays import run_tabular

    original, raw = _raw(tmp_path, matrix=matrix)
    out = tmp_path / 'processed'
    out.mkdir()
    return run_tabular(dict(raw={'manifest': raw['manifest'], 'members': {m['key']: m for m in raw['outputs']
                    }}, config=config or {}, identity=original['identity'], mode='compute', output_directory=str(out)))


def test_b03_qc_has_counts_detection_distribution_filter_reasons_and_outlier_advisory(tmp_path):
    result = _run(tmp_path)
    members = {item['key']: item for item in result['outputs']}
    rows = list(csv.DictReader(io.StringIO(Path(members['sample_qc']['path']).read_text(encoding='utf-8')), delimiter='\t'))
    assert {'total_counts', 'detected_features', 'zero_fraction', 'expression_distribution', 'outlier_advisory'} <= set(rows[0])
    assert result['manifest']['filter_rules']['sample']['manual_exclusion_only'] is True
    assert 'outlier_advisories' in result['manifest']
    assert [row['condition'] for row in rows] == ['A', 'A', 'B']


def test_b03_has_independent_normalized_vst_layers_and_roundtrippable_analysis_object(tmp_path):
    result = _run(tmp_path, {'normalization': 'vst'})
    members = {item['key']: item for item in result['outputs']}
    assert {'raw_values', 'filtered_values', 'normalized_values', 'vst_values', 'analysis_object', 'analysis_object_manifest'} <= set(members)
    assert result['manifest']['value_layers']['normalized']['semantic'] == 'normalized_counts'
    assert result['manifest']['value_layers']['vst']['semantic'] == 'variance_stabilized_expression'
    object_manifest=json.loads(Path(members['analysis_object_manifest']['path']).read_text(encoding='utf-8'))
    assert object_manifest['params']['normalization']=='vst'
    assert object_manifest['identity']==result['manifest']['identity']
    assert len(object_manifest['manifest_identity_sha256'])==64
    from app.adapters.bio_engine.tabular_assays import load_analysis_object
    restored = load_analysis_object(members['analysis_object']['path'], members['analysis_object_manifest']['path'])
    np.testing.assert_array_equal(restored['sample_ids'], ['s1', 's2', 's3'])
    assert restored['layers'].keys() >= {'raw', 'filtered', 'normalized', 'vst'}


def test_b03_emits_correlation_distance_heatmap_data_with_metadata_labels(tmp_path):
    result = _run(tmp_path, {'normalization': 'vst'})
    members = {item['key']: item for item in result['outputs']}
    assert {'sample_correlation', 'sample_distance', 'correlation_heatmap_data', 'distance_heatmap_data'} <= set(members)
    correlation = json.loads(Path(members['sample_correlation']['path']).read_text(encoding='utf-8'))
    assert correlation['sample_ids'] == ['s1', 's2', 's3']
    assert correlation['condition'] == ['A', 'A', 'B']
    assert correlation['batch'] == [''] * 3


def test_bulk_sample_distance_matches_euclidean_without_three_dimensional_broadcast(tmp_path, monkeypatch):
    norm = np.linalg.norm

    def reject_pair_feature_cube(values, *args, **kwargs):
        assert values.ndim < 3, 'sample distances must not allocate a samples-by-samples-by-features array'
        return norm(values, *args, **kwargs)

    monkeypatch.setattr(np.linalg, 'norm', reject_pair_feature_cube)
    result = _run(tmp_path, {'normalization': 'vst'}, matrix='feature_id,s1,s2,s3\na,1,2,7\nb,2,9,8\nc,3,6,2\n')
    members = {item['key']: item for item in result['outputs']}
    observed = json.loads(Path(members['sample_distance']['path']).read_text(encoding='utf-8'))
    vst = np.load(members['vst_values']['path'], allow_pickle=False)
    expected = [[float(np.sqrt(np.sum((a - b) ** 2))) for b in vst] for a in vst]
    assert expected[0][1] > 0
    np.testing.assert_allclose(observed['values'], expected, rtol=1e-12, atol=1e-12)
    assert observed['method'] == 'euclidean_complete_features' and observed['layer'] == 'vst'


def test_b03_vst_is_counts_only_and_manual_exclusion_is_not_automatic(tmp_path):
    from app.adapters.bio_engine.tabular_assays import run_tabular

    original, raw = _raw(tmp_path, counts=False)
    out = tmp_path / 'processed'
    out.mkdir()
    with pytest.raises(ValueError, match='vst_counts_only'):
        run_tabular(dict(raw={'manifest': raw['manifest'], 'members': {m['key']: m for m in raw['outputs']}},
                         config={'normalization': 'vst'}, identity=original['identity'], mode='compute', output_directory=str(out)))


def test_b03_processed_source_exposes_setup_identity_separately_from_recipe():
    from app.adapters.bio_analysis_store import BioAnalysisStore

    raw_source={'kind':'bio_dataset_version','schema_version':1,'project_id':'p1','dataset_id':'d1','dataset_version_id':'v1',
        'version':1,'manifest_sha256':'a'*64,'parser_version':'tabular_assay_import_v1','source_file_ids':['f1']}
    manifest={'schema_version':2,'assay':'bulk_rna_counts','raw_source':raw_source,
        'identity':{'raw_source':raw_source,'recipe_version_id':'recipe1','setup_id':'setup1'},
        'engine_version':'tabular_quantitative_v1.0.0','environment_digest':'b'*64}
    source=BioAnalysisStore.processed_source({'id':'processed1','project_id':'p1','run_id':'run1','recipe_version_id':'recipe1',
        'manifest_sha256':'c'*64,'engine_version':'tabular_quantitative_v1.0.0','environment_digest':'b'*64},manifest)
    assert source['recipe_version_id']=='recipe1' and source['setup_id']=='setup1'
    legacy=dict(manifest,identity=dict(manifest['identity'],setup_id=None))
    legacy_source=BioAnalysisStore.processed_source({'id':'processed1','project_id':'p1','run_id':'run1','recipe_version_id':'recipe1',
        'manifest_sha256':'c'*64,'engine_version':'tabular_quantitative_v1.0.0','environment_digest':'b'*64},legacy)
    assert 'setup_id' not in legacy_source


def test_b03_non_bulk_results_do_not_expose_a_vst_layer(tmp_path):
    from app.adapters.bio_engine.tabular_assays import import_tabular, run_tabular

    original, raw = _raw(tmp_path, counts=False)
    out = tmp_path / 'processed'
    out.mkdir()
    result = run_tabular(dict(raw={'manifest': raw['manifest'], 'members': {m['key']: m for m in raw['outputs']}},
                              config={}, identity=original['identity'], mode='compute', output_directory=str(out)))
    assert 'vst' not in result['manifest']['value_layers']
    assert 'vst' not in result['manifest']['summary']['layers']
    assert 'vst_values' not in {item['key'] for item in result['outputs']}
