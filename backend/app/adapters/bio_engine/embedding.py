import anndata as ad
import numpy as np
import scanpy as sc


def embed(logged, hvg, ids, raw_indices, config):
    if logged.shape[0]<5 or hvg.sum()<3:
        raise ValueError('insufficient_observations_or_hvg')
    if logged.shape[0]*int(hvg.sum())>20_000_000:
        raise ValueError('dense_budget_exceeded')
    dense=logged[:,hvg].toarray().astype(np.float32)
    nonconstant=np.ptp(dense,axis=0)>0
    hvg_indices=np.flatnonzero(hvg)[nonconstant]
    dense=np.ascontiguousarray(dense[:,nonconstant])
    dense=sc.pp.scale(dense,zero_center=True,max_value=10,copy=True).astype(np.float32)
    components=min(int(config.get('pca_components',30)),dense.shape[0]-1,dense.shape[1]-1)
    if components<2: raise ValueError('insufficient_pca_components')
    obj=ad.AnnData(dense)
    seed=int(config.get('seed',0))
    sc.pp.pca(obj,n_comps=components,zero_center=True,svd_solver='arpack',random_state=seed)
    for j in range(components):
        anchor=sorted(range(dense.shape[1]),key=lambda i:(-abs(float(obj.varm['PCs'][i,j])),ids[hvg_indices[i]]))[0]
        if obj.varm['PCs'][anchor,j]<0:
            obj.varm['PCs'][:,j]*=-1; obj.obsm['X_pca'][:,j]*=-1
    sc.pp.neighbors(obj,n_neighbors=min(int(config.get('neighbors',15)),obj.n_obs-1),n_pcs=components,use_rep='X_pca',
                    metric='euclidean',method='umap',transformer='sklearn',random_state=seed)
    sc.tl.umap(obj,min_dist=.5,spread=1.,n_components=2,maxiter=500,random_state=seed)
    sc.tl.leiden(obj,flavor='igraph',directed=False,use_weights=True,n_iterations=2,
                 resolution=config.get('resolution',.5),random_state=seed,key_added='cluster')
    original=obj.obs['cluster'].astype(str).to_numpy()
    labels=sorted(set(original),key=lambda label:int(raw_indices[np.flatnonzero(original==label)].min()))
    clusters=np.asarray([str(labels.index(label)) for label in original])
    return dict(pca=obj.obsm['X_pca'].astype(np.float32),umap=obj.obsm['X_umap'].astype(np.float32),
                clusters=clusters,distances=obj.obsp['distances'],connectivities=obj.obsp['connectivities'],
                loadings=obj.varm['PCs'],hvg_indices=hvg_indices,variance_ratio=obj.uns['pca']['variance_ratio'])
