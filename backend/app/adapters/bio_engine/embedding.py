import anndata as ad
import numpy as np
import scanpy as sc
from importlib.metadata import version


def embed(logged, hvg, ids, raw_indices, config, *, integration_rows=None):
    if logged.shape[0]<5 or hvg.sum()<3:
        raise ValueError('insufficient_observations_or_hvg')
    if logged.shape[0]*int(hvg.sum())>20_000_000:
        raise ValueError('dense_budget_exceeded')
    dense=logged[:,hvg].toarray().astype(np.float32)
    nonconstant=np.ptp(dense,axis=0)>0
    hvg_indices=np.flatnonzero(hvg)[nonconstant]
    dense=np.ascontiguousarray(dense[:,nonconstant])
    components=min(int(config.get('pca_components',30)),dense.shape[0]-1,dense.shape[1]-1)
    if components<2: raise ValueError('insufficient_pca_components')
    seed=int(config.get('seed',0))
    def pca(values):
        scaled=sc.pp.scale(values,zero_center=True,max_value=10,copy=True).astype(np.float32)
        current=ad.AnnData(scaled)
        sc.pp.pca(current,n_comps=components,zero_center=True,svd_solver='arpack',random_state=seed)
        for j in range(components):
            anchor=sorted(range(scaled.shape[1]),key=lambda i:(-abs(float(current.varm['PCs'][i,j])),ids[hvg_indices[i]]))[0]
            if current.varm['PCs'][anchor,j]<0:
                current.varm['PCs'][:,j]*=-1;current.obsm['X_pca'][:,j]*=-1
        return current
    obj=pca(dense);unadjusted=obj.obsm['X_pca'].copy();integration=None;harmony=None;representation='X_pca'
    if integration_rows is not None:
        from .integration import regress_covariates,integrate_pca
        rule=config.get('mt_rule',{})
        adjusted,covariates=regress_covariates(dense,integration_rows,config.get('technical_covariates',[]),rule.get('confirmed') and rule.get('kind')!='unknown')
        if covariates['applied']:obj=pca(adjusted)
        harmony,harmony_state,design,versions=integrate_pca(obj.obsm['X_pca'],integration_rows,config)
        if harmony is not None:
            obj.obsm['X_pca_harmony']=harmony;representation='X_pca_harmony'
        integration=dict(technical_covariates=covariates,harmony=harmony_state,design=design,downstream_representation=representation,versions={'scanpy':version('scanpy'),**versions})
    sc.pp.neighbors(obj,n_neighbors=min(int(config.get('neighbors',15)),obj.n_obs-1),n_pcs=components,use_rep=representation,
                    metric='euclidean',method='umap',transformer='sklearn',random_state=seed)
    sc.tl.umap(obj,min_dist=.5,spread=1.,n_components=2,maxiter=500,random_state=seed)
    sc.tl.leiden(obj,flavor='igraph',directed=False,use_weights=True,n_iterations=2,
                 resolution=config.get('resolution',.5),random_state=seed,key_added='cluster')
    original=obj.obs['cluster'].astype(str).to_numpy()
    labels=sorted(set(original),key=lambda label:int(raw_indices[np.flatnonzero(original==label)].min()))
    clusters=np.asarray([str(labels.index(label)) for label in original])
    return dict(integration=integration,pca_unadjusted=unadjusted,pca_harmony=harmony,pca=obj.obsm['X_pca'].astype(np.float32),umap=obj.obsm['X_umap'].astype(np.float32),
                clusters=clusters,distances=obj.obsp['distances'],connectivities=obj.obsp['connectivities'],
                loadings=obj.varm['PCs'],hvg_indices=hvg_indices,variance_ratio=obj.uns['pca']['variance_ratio'])
