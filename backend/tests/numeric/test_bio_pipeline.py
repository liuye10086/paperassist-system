import numpy as np
from scipy import sparse
import pytest


def test_qc_filters_once_and_preserves_raw_counts():
    from app.adapters.bio_engine.qc import quality_control
    raw = sparse.csr_matrix([[2, 0, 7], [0, 3, 8], [1, 0, 9], [0, 1, 1], [0, 0, 2]])
    before = raw.copy()
    features = {'feature_ids': ['g1', 'g2', 'antibody'], 'feature_symbols': ['A', 'A', 'B'],
                'feature_types': ['Gene Expression', 'Gene Expression', 'Antibody Capture']}
    result = quality_control(raw, features, ['a','b','c','d','e'], [], {'min_gene_spots': 2})
    assert result['obs_mask'].tolist() == [True, True, True, True, False]
    assert result['feature_mask'].tolist() == [True, True, False]
    assert result['raw_counts'].tolist() == [9, 11, 10, 2, 2]
    assert result['mt_reason'] == 'mitochondrial_rule_unconfirmed'
    np.testing.assert_array_equal(result['filtered_counts'].toarray(),[[2,0],[0,3],[1,0],[0,1]])
    assert (before != raw).nnz == 0


def test_qc_extreme_hints_do_not_automatically_exclude_observations():
    from app.adapters.bio_engine.qc import quality_control
    raw=sparse.csr_matrix([[1],[1],[1],[1],[100]],dtype='int64')
    features={'feature_ids':['g'],'feature_symbols':['G'],'feature_types':['Gene Expression']}
    result=quality_control(raw,features,['a','b','c','d','e'],[],{'min_gene_spots':1})
    assert result['extreme_counts'].tolist()==[False,False,False,False,True]
    assert result['obs_mask'].tolist()==[True]*5


def test_normalization_has_independent_reference():
    from app.adapters.bio_engine.preprocess import normalize
    raw = sparse.csr_matrix([[1, 3], [2, 0]], dtype='int64')
    normalized, logged = normalize(raw)
    np.testing.assert_allclose(normalized.toarray(), [[2500, 7500], [10000, 0]])
    np.testing.assert_allclose(logged.toarray(), np.log1p([[2500, 7500], [10000, 0]]), rtol=1e-6)
    assert raw.dtype == np.int64 and logged.dtype == np.float32


def test_configured_target_sum_and_upper_filters_are_applied():
    from app.adapters.bio_engine.preprocess import normalize
    from app.adapters.bio_engine.qc import quality_control
    raw=sparse.csr_matrix([[1,3],[2,0],[1,0]],dtype='int64')
    normalized,_=normalize(raw,target_sum=200)
    np.testing.assert_allclose(normalized.toarray(),[[50,150],[200,0],[200,0]])
    features={'feature_ids':['mt','other'],'feature_symbols':['MT-A','B'],'feature_types':['Gene Expression']*2}
    qc=quality_control(raw,features,['a','b','c'],[],{'min_gene_spots':1,'max_counts':3,'max_mt_fraction':.5,'mitochondrial_feature_ids':['mt']})
    assert qc['obs_mask'].tolist()==[False,False,False]
    assert qc['reasons'][0]==['max_counts']
    assert qc['reasons'][1]==['max_mt_fraction']


def test_wilcoxon_tie_correct_reference_and_effect():
    from app.adapters.bio_engine.markers import markers
    # Ranks 5,5,5 vs 2,2,2; tie-corrected rank variance = 4.05.
    counts = sparse.csr_matrix([[4, 0]] * 3 + [[1, 0]] * 3)
    normalized = counts.astype('float32')
    logged = normalized.copy(); logged.data = np.log1p(logged.data)
    rows, status = markers(counts, normalized, logged, np.array(['0']*3+['1']*3), ['g1','g2'])
    g1 = next(row for row in rows if row['cluster']=='0' and row['feature_id']=='g1')
    from scipy.stats import norm
    z = 4.5 / np.sqrt(4.05)
    assert g1['score'] == pytest.approx(z)
    assert g1['p_value'] == pytest.approx(2 * norm.sf(z))
    assert g1['effect_log2_normalized'] == pytest.approx(np.log2((4+1e-9)/(1+1e-9)))
    assert next(r for r in rows if r['feature_id']=='g2')['p_value'] is None


def test_fullres_transform_preserves_top_left_orientation():
    from app.adapters.bio_engine.plots import transform_coordinates
    result = transform_coordinates(np.array([[0.,0.], [100.,0.], [0.,200.], [50.,100.]]), .5, .25)
    np.testing.assert_equal(result, [[0,0],[12.5,0],[0,25],[6.25,12.5]])


def test_spatial_image_skips_uncalibrated_auxiliary_preview(tmp_path):
    from PIL import Image
    from app.adapters.bio_engine.pipeline import spatial_image
    import hashlib
    auxiliary=tmp_path/'detected_tissue.jpg';Image.new('RGB',(20,10),'red').save(auxiliary)
    hires=tmp_path/'tissue_hires_image.png';Image.new('RGB',(20,10),'white').save(hires)
    before={path:hashlib.sha256(path.read_bytes()).hexdigest() for path in [auxiliary,hires]}
    raw={'manifest':{'spatial':{'images':[
        {'source_member_name':'GSM8157269_detected_tissue_image.jpg.gz','scale_field':None},
        {'source_member_name':'GSM8157269_tissue_hires_image.png.gz','scale_field':'tissue_hires_scalef'}],
        'scalefactors':{'tissue_hires_scalef':.14939867,'spot_diameter_fullres':100.3514761003761}}},
        'members':{key:{'role':'tissue_image','source_member_name':name,'path':str(path),'sha256':before[path]} for key,name,path in [
            ('aux','GSM8157269_detected_tissue_image.jpg.gz',auxiliary),('hires','GSM8157269_tissue_hires_image.png.gz',hires)]}}
    image,scale,radius,sha=spatial_image(raw)
    np.testing.assert_array_equal(image,np.full((10,20,3),255,dtype='uint8'))
    assert scale==.14939867 and radius==pytest.approx(100.3514761003761*.14939867/2)
    assert sha==before[hires]
    assert all(hashlib.sha256(path.read_bytes()).hexdigest()==sha for path,sha in before.items())


def test_hvg_statistics_match_fixed_scanpy_and_pca_matches_independent_scaled_reference():
    import anndata as ad
    import scanpy as sc
    from sklearn.decomposition import PCA
    from app.adapters.bio_engine.preprocess import normalize,high_variable
    from app.adapters.bio_engine.embedding import embed
    raw=sparse.csr_matrix(np.random.default_rng(74).poisson(4,(30,20)).astype('int64'))
    _,logged=normalize(raw);ids=['g'+str(i).zfill(2) for i in range(20)]
    chosen,mean,dispersion=high_variable(logged,ids,n_top=12)
    official=ad.AnnData(logged.copy());sc.pp.highly_variable_genes(official,flavor='seurat',n_top_genes=12,n_bins=20)
    np.testing.assert_allclose(mean,official.var['means'].to_numpy())
    np.testing.assert_allclose(dispersion,official.var['dispersions_norm'].to_numpy(),equal_nan=True)
    expected=logged[:,chosen].toarray().astype('float32')
    expected=sc.pp.scale(expected,zero_center=True,max_value=10,copy=True).astype('float32')
    reference=PCA(n_components=5,svd_solver='arpack',random_state=13)
    # Match the official ARPACK score definition U*S. A separate transform()
    # adds a float32 GEMM and has a different rounding contract near zero.
    scores=reference.fit_transform(expected)
    result=embed(logged,chosen,ids,np.arange(30),{'pca_components':5,'neighbors':5,'seed':13})
    for j in range(5):
        anchor=np.argmax(np.abs(reference.components_[j]))
        if reference.components_[j,anchor]<0:scores[:,j]*=-1
    np.testing.assert_allclose(result['pca'],scores,rtol=1e-5,atol=1e-6)
    np.testing.assert_allclose(result['variance_ratio'],reference.explained_variance_ratio_,rtol=1e-5)
