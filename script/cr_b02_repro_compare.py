"""Scientific comparator shipped with each offline reproduction package."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np

FLOAT32 = (1e-5, 1e-6)
FLOAT64 = (1e-8, 1e-12)
FLOAT_FIELDS = {'score','p_value','q_value','effect_log2_normalized','detected_group','detected_rest',
    'mean','dispersion_normalized','pc1','pc2','umap1','umap2','zero_fraction','mt_fraction','mean_counts'}
PCA_FILES = {'pca','pca_loadings'}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(1024**2): digest.update(block)
    return digest.hexdigest()


def compare_array(left, right, *, exact=False, tolerance=FLOAT32):
    left, right = np.asarray(left), np.asarray(right)
    assert left.shape == right.shape, 'array shape differs'
    assert left.dtype == right.dtype, 'array dtype differs'
    if exact or left.dtype.kind not in 'fc':
        np.testing.assert_array_equal(left, right, strict=True)
    else:
        np.testing.assert_array_equal(np.isnan(left), np.isnan(right))
        np.testing.assert_array_equal(np.isposinf(left), np.isposinf(right))
        np.testing.assert_array_equal(np.isneginf(left), np.isneginf(right))
        np.testing.assert_allclose(left, right, rtol=tolerance[0], atol=tolerance[1], equal_nan=True)


def canonical_pca(scores, loadings, feature_ids):
    scores, loadings = np.array(scores, copy=True), np.array(loadings, copy=True)
    assert loadings.shape[0] == len(feature_ids)
    for column in range(loadings.shape[1]):
        values = loadings[:,column]
        maximum = np.max(np.abs(values))
        selected = min(np.flatnonzero(np.abs(values) == maximum), key=lambda i: feature_ids[i])
        if values[selected] < 0:
            scores[:,column] *= -1; loadings[:,column] *= -1
    return scores, loadings


def compare_table(left, right, key):
    with Path(left).open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream, delimiter='\t'); fields = reader.fieldnames; rows_left = list(reader)
    with Path(right).open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream, delimiter='\t'); assert fields == reader.fieldnames, 'table columns differ'; rows_right = list(reader)
    assert len(rows_left) == len(rows_right), 'table row count differs'
    tolerance = FLOAT64 if key in {'markers','markers_top'} else FLOAT32
    # Output ordering, tested feature set, NA masks, cluster IDs and stable axes
    # are contractual. Do not sort away an unexpected marker ranking change.
    for column in fields:
        a, b = [r[column] for r in rows_left], [r[column] for r in rows_right]
        assert [v == '' for v in a] == [v == '' for v in b], 'table NA mask differs: ' + column
        if column in FLOAT_FIELDS:
            compare_array(np.asarray([float(v) if v else np.nan for v in a], dtype='float64'),
                          np.asarray([float(v) if v else np.nan for v in b], dtype='float64'), tolerance=tolerance)
        else: assert a == b, 'table identity/order differs: ' + column


def compare_json(left, right):
    if isinstance(left, dict):
        assert isinstance(right, dict) and left.keys() == right.keys(), 'JSON keys differ'
        for key in left: compare_json(left[key], right[key])
    elif isinstance(left, list):
        assert isinstance(right, list) and len(left) == len(right), 'JSON list differs'
        for a, b in zip(left, right): compare_json(a, b)
    elif isinstance(left, float):
        assert isinstance(right, (int,float)) and not isinstance(right, bool)
        np.testing.assert_allclose(left, right, rtol=FLOAT32[0], atol=FLOAT32[1])
    else: assert type(left) is type(right) and left == right, 'JSON exact value differs'


def compare_sparse(left, right, *, exact=False):
    assert left.shape == right.shape
    left, right = left.tocsr(copy=True), right.tocsr(copy=True)
    left.sort_indices(); right.sort_indices()
    # Canonical sparse structure and dtype must remain exact.
    np.testing.assert_array_equal(left.indptr, right.indptr)
    np.testing.assert_array_equal(left.indices, right.indices)
    compare_array(left.data, right.data, exact=exact)


def compare_h5ad(left, right):
    import anndata as ad
    a, b = ad.read_h5ad(left), ad.read_h5ad(right)
    assert a.obs_names.tolist() == b.obs_names.tolist() and a.var_names.tolist() == b.var_names.tolist()
    assert a.obs.columns.tolist() == b.obs.columns.tolist() and a.var.columns.tolist() == b.var.columns.tolist()
    for field in a.obs: assert a.obs[field].astype(str).tolist() == b.obs[field].astype(str).tolist()
    for field in a.var: assert a.var[field].astype(str).tolist() == b.var[field].astype(str).tolist()
    compare_sparse(a.X, b.X)
    assert set(a.layers) == set(b.layers) and set(a.obsm) == set(b.obsm) and set(a.obsp) == set(b.obsp)
    for key in a.layers: compare_sparse(a.layers[key], b.layers[key], exact=key == 'counts')
    for key in a.obsm: compare_array(a.obsm[key], b.obsm[key])
    for key in a.obsp: compare_sparse(a.obsp[key], b.obsp[key])
    assert dict(a.uns) == dict(b.uns), 'H5AD identity/params differ'


def compare_directories(baseline, candidate):
    baseline, candidate = Path(baseline), Path(candidate)
    index = json.loads((baseline/'baseline.json').read_bytes())
    checks = []
    pca_cache = {}
    def pca(root):
        if root not in pca_cache:
            axes = json.loads((root/'raw_axes.json').read_bytes())['feature_ids']
            raw_indices = np.load(root/'pca_feature_raw_indices.npy', allow_pickle=False)
            pca_cache[root] = canonical_pca(np.load(root/'pca.npy', allow_pickle=False),
                np.load(root/'pca_loadings.npy', allow_pickle=False), [axes[i] for i in raw_indices])
        return pca_cache[root]
    scientific_manifest_fields = ['schema_version','engine_version','params','steps','summary','tables','layers']
    for item in index['members']:
        key, fmt = item['key'], item['format']
        a, b = baseline/item['filename'], candidate/item['filename']
        entry = {'key':key, 'format':fmt, 'status':'passed', 'method':'exact_sha256'}
        try:
            assert a.is_file() and b.is_file(), 'artifact missing'
            entry.update(baseline_sha256=sha256(a), candidate_sha256=sha256(b))
            assert sha256(a) == item['sha256'], 'baseline bytes changed'
            if key in PCA_FILES:
                entry['method'] = 'stable_feature_id_sign_float32_tolerance'
                position = 0 if key == 'pca' else 1
                compare_array(pca(baseline)[position], pca(candidate)[position])
            elif fmt == 'npy':
                entry['method'] = 'exact_integer_or_float32_tolerance'
                compare_array(np.load(a,allow_pickle=False), np.load(b,allow_pickle=False))
            elif fmt == 'tsv':
                entry['method'] = 'exact_order_axes_NA_and_float64_marker_or_float32_tolerance'
                compare_table(a,b,key)
            elif fmt == 'h5ad':
                entry['method'] = 'H5AD_semantic_layers_axes_obsm_obsp_uns'
                compare_h5ad(a,b)
            elif key == 'manifest':
                entry['method'] = 'scientific_manifest_excluding_identity_resources_member_container_hashes'
                ma, mb = json.loads(a.read_bytes()), json.loads(b.read_bytes())
                compare_json({k:ma[k] for k in scientific_manifest_fields}, {k:mb[k] for k in scientific_manifest_fields})
            elif fmt == 'json':
                entry['method'] = 'JSON_exact_axes_and_float32_tolerance'
                compare_json(json.loads(a.read_bytes()), json.loads(b.read_bytes()))
            else:
                assert sha256(a) == sha256(b), 'exact artifact hash differs'
        except (AssertionError, OSError, ValueError, KeyError) as exc:
            entry.update(status='failed', detail=str(exc)[:2000])
        checks.append(entry)
    expected = {item['filename'] for item in index['members']}
    extras = sorted(p.name for p in candidate.iterdir() if p.is_file() and p.name not in expected and p.name not in {'baseline.json','result.json','worker.stdout.bin','worker.stderr.txt','comparison.json'})
    if extras: checks.append({'key':'unexpected_artifacts','status':'failed','files':extras})
    return {'schema_version':1,'status':'passed' if all(c['status']=='passed' for c in checks) else 'failed',
        'float32_tolerance':{'rtol':FLOAT32[0],'atol':FLOAT32[1]},'marker_float64_tolerance':{'rtol':FLOAT64[0],'atol':FLOAT64[1]},
        'checks':checks,'biological_validation':'not_performed','user_acceptance':'pending'}


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('baseline'); parser.add_argument('candidate'); parser.add_argument('--report',required=True)
    args=parser.parse_args(); report=compare_directories(args.baseline,args.candidate)
    Path(args.report).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':report['status'],'checks':len(report['checks'])}))
    raise SystemExit(0 if report['status']=='passed' else 1)


if __name__=='__main__': main()
