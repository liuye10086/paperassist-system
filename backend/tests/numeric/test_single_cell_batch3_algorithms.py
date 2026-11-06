import numpy as np
import pytest
import anndata as ad
import scanpy as sc
from scipy import sparse


def sample():
    rng=np.random.default_rng(78)
    from app.adapters.bio_engine.preprocess import normalize
    counts=sparse.csr_matrix(rng.poisson(3,(80,36)))
    _,logged=normalize(counts)
    return counts,logged,[f'g{i:03}' for i in range(36)],['b1']*40+['b2']*40


def test_batch_hvg_matches_scanpy_n_top_hits_and_stable_ranking():
    from app.adapters.bio_engine.integration import select_hvg
    _,logged,ids,batches=sample()
    rows=[dict(batch=b) for b in batches]
    mask,means,disp,nb,state=select_hvg(logged,ids,12,rows,'batch')
    obj=ad.AnnData(logged.copy());obj.obs['batch']=batches
    sc.pp.highly_variable_genes(obj,flavor='seurat',n_bins=20,n_top_genes=12,batch_key='batch')
    np.testing.assert_allclose(means,obj.var.means)
    np.testing.assert_allclose(disp,obj.var.dispersions_norm)
    np.testing.assert_array_equal(nb,obj.var.highly_variable_nbatches)
    order=sorted(range(len(ids)),key=lambda i:(-int(nb[i]),-float(disp[i]),ids[i]))[:12]
    assert set(np.flatnonzero(mask))==set(order) and state['strategy']=='batch_aware_seurat'


@pytest.mark.parametrize('batches,reason',[(None,'batch_values_missing'),(['only']*80,'single_batch')])
def test_hvg_fallback_preserves_global(batches,reason):
    from app.adapters.bio_engine.integration import select_hvg
    from app.adapters.bio_engine.preprocess import high_variable
    _,logged,ids,_=sample()
    rows=[dict(batch=v) for v in batches] if batches else [{} for _ in range(80)]
    value=select_hvg(logged,ids,12,rows,'batch')
    np.testing.assert_array_equal(value[0],high_variable(logged,ids,12)[0])
    assert value[-1]['fallback_reason']==reason


def test_covariate_native_regression_and_input_preservation():
    from app.adapters.bio_engine.integration import regress_covariates
    counts,logged,_,_=sample();dense=logged[:,:12].toarray();before=dense.copy()
    rows=[dict(total_counts=int(n)) for n in np.asarray(counts.sum(1)).ravel()]
    adjusted,state=regress_covariates(dense,rows,['log1p_total_counts'],False)
    ref=ad.AnnData(before.copy());ref.obs['log1p_total_counts']=np.log1p([r['total_counts'] for r in rows])
    sc.pp.regress_out(ref,['log1p_total_counts'],n_jobs=1)
    np.testing.assert_allclose(adjusted,ref.X,atol=1e-6)
    np.testing.assert_array_equal(dense,before)
    assert state['applied'] is True


@pytest.mark.parametrize('rows,columns,confirmed,reason',[
    ([{}]*8,['log1p_total_counts'],False,'covariate_missing_or_nonfinite'),
    ([dict(total_counts=2)]*8,['log1p_total_counts'],False,'covariate_constant'),
    ([dict(mt_fraction=i/10) for i in range(8)],['mt_fraction'],False,'mitochondrial_rule_unconfirmed'),
    ([dict(total_counts=i+1,mt_fraction=np.log1p(i+1)/10) for i in range(8)],['log1p_total_counts','mt_fraction'],True,'covariate_design_rank_deficient'),
])
def test_invalid_covariate_set_is_not_partially_applied(rows,columns,confirmed,reason):
    from app.adapters.bio_engine.integration import regress_covariates
    x=np.arange(32,dtype='float32').reshape(8,4)
    adjusted,state=regress_covariates(x,rows,columns,confirmed)
    np.testing.assert_array_equal(adjusted,x)
    assert state['status']=='not_computable' and state['reason']==reason and not state['applied']


def test_harmony_refuses_confounding_but_missing_groups_are_exploratory():
    from app.adapters.bio_engine.integration import assess_design
    rows=[dict(batch='A',group='control')]*20+[dict(batch='B',group='case')]*20
    assert assess_design(rows,'batch')['reason']=='batch_group_completely_confounded'
    assert assess_design([dict(batch=r['batch']) for r in rows],'batch')['reason']=='group_missing_confounding_unassessed'


def test_harmony_embedding_routes_neighbors_to_corrected_coordinates(monkeypatch):
    from app.adapters.bio_engine import integration
    from app.adapters.bio_engine.embedding import embed
    _,logged,ids,batches=sample()
    class Bridge:
        versions={'harmony':'1.2.3','R':'4.4.3'}
        def harmony(self,pcs,cells,batches,config,seed):
            return dict(status='completed',reason=None,logs=['axis test'],embedding=pcs*np.arange(1,pcs.shape[1]+1))
        def release_temporaries(self):pass
    monkeypatch.setattr(integration,'get_bridge',lambda:Bridge())
    captured=[];native=sc.pp.neighbors
    def neighbors(obj,**kwargs):
        captured.append((kwargs['use_rep'],obj.obsm[kwargs['use_rep']].copy()))
        return native(obj,**kwargs)
    monkeypatch.setattr(sc.pp,'neighbors',neighbors)
    rows=[dict(barcode=f'cell{i}',batch=b,total_counts=i+20,group='healthy') for i,b in enumerate(batches)]
    result=embed(logged,np.ones(len(ids),dtype=bool),ids,np.arange(80),dict(pca_components=6,technical_covariates=['log1p_total_counts'],harmony=dict(enabled=True,batch_key='batch')),integration_rows=rows)
    assert captured[0][0]=='X_pca_harmony'
    np.testing.assert_array_equal(captured[0][1],result['pca_harmony'])
    assert result['integration']['downstream_representation']=='X_pca_harmony'
    assert not np.array_equal(result['pca_unadjusted'],result['pca'])


def test_embedded_bridge_has_explicit_harmony_axis_validation():
    from app.adapters.single_cell_r.bridge import EmbeddedR
    assert callable(getattr(EmbeddedR,'harmony',None))


@pytest.mark.parametrize('reason,rows',[
    ('single_batch',[dict(batch='A',group='healthy')]*80),
    ('batch_values_missing',[dict(batch='A')]*79+[{}]),
    ('batch_group_completely_confounded',[dict(batch='A',group='case')]*40+[dict(batch='B',group='control')]*40),
])
def test_harmony_invalid_design_does_not_call_r(monkeypatch,reason,rows):
    from app.adapters.bio_engine import integration
    monkeypatch.setattr(integration,'get_bridge',lambda:pytest.fail('invalid design called R'))
    embedding,state,design,versions=integration.integrate_pca(np.zeros((80,6)),rows,dict(harmony=dict(enabled=True)))
    assert embedding is None and state['reason']==reason and state['status']=='not_computable' and not state['applied']


def test_harmony_failure_preserves_pca_and_does_not_create_corrected_coordinates(monkeypatch):
    from app.adapters.bio_engine import integration
    from app.adapters.bio_engine.embedding import embed
    _,logged,ids,batches=sample()
    rows=[dict(barcode=str(i),batch=b,group='healthy') for i,b in enumerate(batches)]
    class Bridge:
        versions={'harmony':'1.2.3'}
        def harmony(self,*args):return dict(status='failed',reason='harmony_failed',logs=['failure fixture'])
        def release_temporaries(self):pass
    monkeypatch.setattr(integration,'get_bridge',lambda:Bridge())
    config=dict(pca_components=4)
    old=embed(logged,np.ones(len(ids),dtype=bool),ids,np.arange(80),config)
    failed=embed(logged,np.ones(len(ids),dtype=bool),ids,np.arange(80),{**config,'harmony':dict(enabled=True)},integration_rows=rows)
    assert failed['integration']['downstream_representation']=='X_pca' and failed['pca_harmony'] is None
    for key in ('pca','umap','clusters','loadings','variance_ratio'):np.testing.assert_array_equal(failed[key],old[key])
    assert (failed['connectivities']!=old['connectivities']).nnz==0


def test_single_cell_all_disabled_preserves_previous_scientific_behavior():
    from app.adapters.bio_engine.embedding import embed
    _,logged,ids,batches=sample();config=dict(pca_components=4)
    old=embed(logged,np.ones(len(ids),dtype=bool),ids,np.arange(80),config)
    new=embed(logged,np.ones(len(ids),dtype=bool),ids,np.arange(80),config,integration_rows=[dict(batch=b) for b in batches])
    for key in ('pca','umap','clusters','loadings','variance_ratio'):np.testing.assert_array_equal(new[key],old[key])


def test_single_cell_singleton_batch_hvg_explicitly_falls_back():
    from app.adapters.bio_engine.integration import select_hvg
    _,logged,ids,_=sample()
    value=select_hvg(logged,ids,12,[dict(batch='a')]*79+[dict(batch='b')],'batch')
    assert value[-1]['fallback'] is True and value[-1]['fallback_reason']=='batch_too_small'


def test_integration_plot_titles_describe_before_after_in_output_language(tmp_path,monkeypatch):
    from app.adapters.bio_engine.integration import publish_integration
    from app.adapters.bio_engine.manifest import Writer
    from app.adapters.bio_engine import plots
    from matplotlib import pyplot as plt
    titles=[];exports=[]
    def capture(writer,key,fig,data,config):
        titles.extend(ax.get_title() for ax in fig.axes)
        exports.append((data,config,[artist.get_facecolors()[0] for artist in fig.axes[0].collections]))
        plt.close(fig)
    monkeypatch.setattr(plots,'save',capture)
    pcs=np.arange(48,dtype='float32').reshape(12,4)
    state=dict(harmony=dict(batch_key='batch',logs=[]),technical_covariates={'applied':True},design={'counts':[]},versions={})
    publish_integration(Writer(tmp_path),dict(integration=state,pca_unadjusted=pcs,pca=pcs,pca_harmony=pcs),
        [dict(barcode=str(i),batch='A' if i<6 else 'B') for i in range(12)],dict(output_language='zh-CN'))
    assert titles==['协变量处理前','协变量处理后','Harmony 前（PCA）','Harmony 后（校正维度）']
    for data,config,artist_colors in exports:
        assert config['palette']==config['cmap']=='tab20'
        assert config['effective_palette']==data['effective_palette']=='paperassist_golden_angle_hsl_v1'
        assert sorted(data['category_colors'])==['A','B']
        np.testing.assert_array_equal(artist_colors,[data['category_colors'][label] for label in ['A','B']])
