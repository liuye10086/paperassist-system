"""Batch-aware feature selection and reversible embedding-only adjustments."""
import numpy as np
import anndata as ad
import scanpy as sc
from .preprocess import high_variable
from app.adapters.single_cell_r.bridge import get_bridge


def batch_values(rows,key):
    values=[r.get(key) for r in rows]
    if any(v is None or not str(v).strip() for v in values):return values,'batch_values_missing'
    if len(set(values))<2:return values,'single_batch'
    return values,None


def select_hvg(logged,ids,n_top,rows,key):
    values,reason=batch_values(rows,key) if key else ([],None)
    if key and not reason and min(values.count(v) for v in set(values))<2:reason='batch_too_small'
    state=dict(status='completed',requested=key is not None,applied=False,batch_key=key,
        strategy='global_seurat',fallback=bool(reason),fallback_reason=reason,reason=reason,n_top_genes=n_top,n_bins=20)
    if not key or reason:
        chosen,mean,dispersion=high_variable(logged,ids,n_top)
        return chosen,mean,dispersion,None,state
    obj=ad.AnnData(logged.copy());obj.obs['batch']=values
    sc.pp.highly_variable_genes(obj,flavor='seurat',n_bins=20,n_top_genes=n_top,batch_key='batch',inplace=True)
    mean=obj.var['means'].to_numpy();dispersion=obj.var['dispersions_norm'].to_numpy()
    hits=obj.var['highly_variable_nbatches'].to_numpy()
    variance=np.asarray(logged.power(2).mean(0)).ravel()-np.asarray(logged.mean(0)).ravel()**2
    eligible=np.isfinite(dispersion)&(variance>1e-12)
    order=sorted(np.flatnonzero(eligible),key=lambda i:(-int(hits[i]),-float(dispersion[i]),ids[i]))
    chosen=np.zeros(len(ids),dtype=bool);chosen[order[:n_top]]=True
    state.update(applied=True,strategy='batch_aware_seurat',batches=len(set(values)))
    return chosen,mean,dispersion,hits,state


def regress_covariates(dense,rows,columns,mt_confirmed):
    state=dict(status='not_requested',reason='disabled',requested=list(columns),applied=False,columns=list(columns),
        tool='scanpy.pp.regress_out',n_jobs=1,intercept=True,source='raw_QC_counts',design_rank=None)
    if not columns:return dense.copy(),state
    reason=None;values=[]
    if 'mt_fraction' in columns and not mt_confirmed:reason='mitochondrial_rule_unconfirmed'
    for column in columns:
        raw=[r.get('total_counts' if column=='log1p_total_counts' else column) for r in rows]
        try:
            arr=np.asarray(raw,dtype='float64')
            if column=='log1p_total_counts':arr=np.log1p(arr)
            if not np.isfinite(arr).all():reason=reason or 'covariate_missing_or_nonfinite'
            elif np.ptp(arr)<=1e-12:reason=reason or 'covariate_constant'
            values.append(arr)
        except (TypeError,ValueError):reason=reason or 'covariate_missing_or_nonfinite'
    if not reason:
        design=np.column_stack([np.ones(len(rows)),*values])
        rank=int(np.linalg.matrix_rank(design));state['design_rank']=rank
        if rank<design.shape[1] or len(rows)<=rank:reason='covariate_design_rank_deficient'
    if reason:
        state.update(status='not_computable',reason=reason);return dense.copy(),state
    obj=ad.AnnData(dense.copy())
    for column,arr in zip(columns,values):obj.obs[column]=arr
    try:
        sc.pp.regress_out(obj,keys=columns,n_jobs=1)
        if not np.isfinite(obj.X).all() or np.count_nonzero(np.ptp(obj.X,axis=0)>1e-7)<3:
            state.update(status='not_computable',reason='insufficient_residual_variation');return dense.copy(),state
    except (ValueError,np.linalg.LinAlgError) as exc:
        state.update(status='failed',reason='regression_failed',logs=[str(exc)]);return dense.copy(),state
    state.update(status='completed',reason=None,applied=True)
    return np.asarray(obj.X,dtype='float32'),state


def assess_design(rows,key):
    values,reason=batch_values(rows,key)
    counts={}
    for row,batch in zip(rows,values):
        group=row.get('group');counts[(batch,group)]=counts.get((batch,group),0)+1
    table=[dict(batch=b,group=g,cells=n) for (b,g),n in sorted(counts.items(),key=lambda p:(str(p[0][0]),str(p[0][1])))]
    result=dict(status='completed',reason=reason,batch_key=key,confounded=False,counts=table,
        groups_complete=all(r.get('group') is not None for r in rows))
    if reason:result['status']='not_computable'
    elif not result['groups_complete']:
        result.update(status='not_computable',reason='group_missing_confounding_unassessed')
    else:
        groups={r['group'] for r in rows}
        # If each batch belongs to exactly one biological group, there is no
        # within-batch group contrast to distinguish batch from group effects.
        confounded=len(groups)>1 and all(len({r['group'] for r in rows if r[key]==b})==1 for b in set(values))
        if confounded:result.update(status='not_computable',reason='batch_group_completely_confounded',confounded=True)
    return result


def integrate_pca(pcs,rows,config):
    params=config.get('harmony',{});key=params.get('batch_key','batch')
    design=assess_design(rows,key)
    state=dict(status='not_requested',reason='disabled',requested=bool(params.get('enabled')),applied=False,batch_key=key,logs=[],
        actual_params=dict(theta=params.get('theta',2),**{'lambda':params.get('lambda',1)},sigma=.1,max_iter=params.get('max_iter',10),early_stop=True,ncores=1,return_object=False,seed=int(config.get('seed',0)),nclust=min(round(len(rows)/30),100)))
    versions={}
    if not state['requested']:return None,state,design,versions
    _,reason=batch_values(rows,key)
    if design['confounded']:reason='batch_group_completely_confounded'
    if state['actual_params']['nclust']<2:reason=reason or 'insufficient_cells_for_harmony_default_clusters'
    if reason:
        state.update(status='not_computable',reason=reason);return None,state,design,versions
    bridge=get_bridge();versions=bridge.versions
    try:
        result=bridge.harmony(pcs,[r['barcode'] for r in rows],[r[key] for r in rows],params,int(config.get('seed',0)))
    except (ValueError,RuntimeError) as exc:
        result=dict(status='failed',reason='harmony_failed',logs=[str(exc)])
    finally:bridge.release_temporaries()
    state.update({k:result[k] for k in ('status','reason','logs')})
    state['applied']=result['status']=='completed'
    return result.get('embedding') if state['applied'] else None,state,design,versions


def batch_diagnostics(representations,rows,key,seed):
    from sklearn.metrics import silhouette_score
    from sklearn.neighbors import NearestNeighbors
    labels,reason=batch_values(rows,key)
    if reason:return [dict(representation=name,status='not_computable',reason=reason) for name in representations]
    indices=np.sort(np.random.default_rng(seed).choice(len(rows),min(1000,len(rows)),replace=False))
    labels=np.asarray(labels)[indices];records=[]
    for name,matrix in representations.items():
        x=matrix[indices];k=min(15,len(x)-1)
        neighbors=NearestNeighbors(n_neighbors=k+1,n_jobs=1).fit(x).kneighbors(x,return_distance=False)
        cross=[]
        for i,nn in enumerate(neighbors):cross.extend((labels[nn[nn!=i][:k]]!=labels[i]).tolist())
        possible=1<len(set(labels))<len(labels)
        records.append(dict(representation=name,status='completed',reason=None,sampled_cells=len(x),dimensions=x.shape[1],seed=seed,
            batch_silhouette=float(silhouette_score(x,labels)) if possible else None,knn_cross_batch_fraction=float(np.mean(cross)),neighbors=k,
            interpretation='descriptive_batch_mixing_not_biological_quality'))
    return records


def publish_integration(writer,result,rows,config):
    from . import plots
    from matplotlib import pyplot as plt
    state=result['integration'];representations={'X_pca_unadjusted':result['pca_unadjusted'],'X_pca':result['pca']}
    if result.get('pca_harmony') is not None:representations['X_pca_harmony']=result['pca_harmony']
    key=state['harmony']['batch_key'];labels=[r.get(key) or 'unknown' for r in rows]
    state['diagnostics']=batch_diagnostics(representations,rows,key,int(config.get('seed',0)))
    writer.json('integration_summary',state)
    writer.table('integration_design',state['design']['counts'],['batch','group','cells'])
    writer.table('integration_diagnostics',state['diagnostics'])
    writer.table('integration_tool_versions',[dict(tool=k,version=v) for k,v in state['versions'].items()],['tool','version'])
    writer.add('integration_tool_logs',('\n'.join(state['harmony']['logs'])+'\n').encode(),'txt')
    for name,matrix in representations.items():writer.array('integration_'+name.lower(),matrix)
    writer.table('integration_coordinates',[dict(barcode=r['barcode'],representation=name,**{f'dimension_{j+1}':float(v) for j,v in enumerate(matrix[i])}) for name,matrix in representations.items() for i,r in enumerate(rows)])
    for suffix,before,after in [('covariates','X_pca_unadjusted','X_pca'),('harmony','X_pca','X_pca_harmony')]:
        if after not in representations:continue
        fig,axes=plt.subplots(1,2);colors,effective_palette=plots.categorical_colors(sorted(set(labels)),palette='tab20')
        en=config.get('output_language','en')=='en'
        titles=(['Before covariate regression','After covariate regression'] if en else ['协变量处理前','协变量处理后']) if suffix=='covariates' else (['Before Harmony (PCA)','After Harmony (corrected)'] if en else ['Harmony 前（PCA）','Harmony 后（校正维度）'])
        if suffix=='covariates' and not state['technical_covariates'].get('applied'):titles[1]+=' (not applied)' if en else '（未应用）'
        if suffix=='harmony':fig.suptitle('Harmony dimensions do not represent PCA explained variance' if en else 'Harmony 校正维度不代表 PCA 解释方差',fontsize=9)
        for ax,name,title in zip(axes,[before,after],titles):
            matrix=representations[name]
            for label in sorted(set(labels)):
                selected=np.asarray([v==label for v in labels]);ax.scatter(matrix[selected,0],matrix[selected,1],s=5,label=label,color=colors[label])
            harmony=name=='X_pca_harmony';prefix=('Harmony dimension' if en else 'Harmony 维度') if harmony else 'PC'
            ax.set(xlabel=prefix+' 1',ylabel=prefix+' 2',title=title);ax.legend(fontsize=6)
        plots.save(writer,'integration_'+suffix,fig,dict(barcodes=[r['barcode'] for r in rows],batch_key=key,batches=labels,before=representations[before],after=representations[after],
            category_colors=colors,effective_palette=effective_palette,
            axis_note='Harmony axes are corrected dimensions, not PCA explained variance',state=state['harmony' if suffix=='harmony' else 'technical_covariates']),
            {**config,'kind':'integration_'+suffix,'width_inches':8,'height_inches':4,'palette':'tab20','cmap':'tab20','effective_palette':effective_palette})
