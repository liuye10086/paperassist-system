"""Versioned bulk counts core. The existing spatial poscounts model is unchanged."""
import warnings
import numpy as np
import pandas as pd
from .comparison import _identity


def frozen_parameters(config):
    return dict(size_factors_fit_type=config.size_factor_method,fit_type='parametric',refit_cooks=False,cooks_filter=True,independent_filter=True,alpha=.05,
        lfc_null=0.,alt_hypothesis=None,prior_LFC_var=None,lfc_shrinkage=False,min_mu=.5,min_disp=1e-8,max_disp=10.,min_replicates=7,beta_tol=1e-8,low_memory=False,n_cpus=1,minimum_total_counts=config.minimum_total_counts)


def fit_counts(values,features,contrast,groups,group_keys,by_key,config):
    from pydeseq2.dds import DeseqDataSet
    from pydeseq2.ds import DeseqStats
    from pydeseq2.default_inference import DefaultInference
    ordered=[(key,index,label) for side in (1,0) for key,index in zip(group_keys[side],groups[side]) for label in [contrast.groups[side].label]]
    matrix=np.asarray(values[[i for _,i,_ in ordered]])
    if matrix.dtype!=np.dtype('int64') or np.any(matrix<0) or sum(map(int,matrix.ravel()))>np.iinfo(np.int64).max:raise ValueError('raw_counts_invalid')
    if matrix.size>1000000 or len(matrix)>512:raise ValueError('bulk_model_budget')
    tested=matrix.sum(0)>=config.minimum_total_counts
    if not tested.any() or np.any(matrix[:,tested].sum(1)==0):raise ValueError('no_testable_features_or_zero_library')
    if config.size_factor_method=='ratio' and not (matrix[:,tested]>0).all(0).any():raise ValueError('ratio_no_positive_features')
    ids=['s'+_identity(key)[:24] for key,_,_ in ordered]
    if len(ids)!=len(set(ids)):raise ValueError('duplicate_model_sample')
    metadata_rows=[dict(contrast_id=contrast.contrast_id,unit_id=uid,processed_version_id=key[0],sample_id=key[1],condition=label,
        donor=by_key[key].get(config.pairing_field) or '',batch=by_key[key].get('batch') or '',biological_unit_id=by_key[key].get('biological_unit_id') or by_key[key].get('donor') or '')
        for uid,(key,_,label) in zip(ids,ordered)]
    metadata=pd.DataFrame(metadata_rows,index=ids)
    metadata['condition']=pd.Categorical(metadata['condition'],categories=[contrast.groups[1].label,contrast.groups[0].label])
    formula='~ donor + condition' if config.design=='paired' else '~ batch + condition' if config.batch_adjustment else '~ condition'
    frame=pd.DataFrame(matrix[:,tested],index=ids,columns=np.asarray(features)[tested])
    inference=DefaultInference(n_cpus=1)
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter('always')
        dds=DeseqDataSet(counts=frame,metadata=metadata,design=formula,fit_type='parametric',size_factors_fit_type=config.size_factor_method,
            refit_cooks=False,low_memory=False,n_cpus=1,inference=inference,quiet=True,min_mu=.5,min_disp=1e-8,max_disp=10.,min_replicates=7,beta_tol=1e-8)
        design=np.asarray(dds.obsm['design_matrix'],dtype=float);rank=int(np.linalg.matrix_rank(design))
        if rank!=design.shape[1] or len(matrix)-rank<=0:raise ValueError('actual_design_rank_invalid')
        dds.deseq2()
        stats=DeseqStats(dds,contrast=['condition',contrast.groups[0].label,contrast.groups[1].label],alpha=.05,cooks_filter=True,
            independent_filter=True,lfc_null=0.,alt_hypothesis=None,prior_LFC_var=None,n_cpus=1,inference=inference,quiet=True)
        stats.summary()
    factors=np.asarray(dds.obs['size_factors'],dtype=float)
    if factors.shape!=(len(matrix),) or not np.isfinite(factors).all() or np.any(factors<=0):raise ValueError('size_factors_invalid')
    normalized=matrix.astype(float)/factors[:,None]
    if not np.isfinite(normalized).all():raise ValueError('normalized_counts_nonfinite')
    output=[];convergence=[]
    for j,feature in enumerate(features):
        row=dict(effect_name='effect_log2fc',effect_value=None,effect_unit='log2 count fold change',effect_reason='not_computable',
            base_mean=None,lfc_se=None,statistic=None,wald_statistic=None,p_value=None,original_method_adjustment=None,
            tested=bool(tested[j]),test_status='not_computable' if tested[j] else 'excluded',reason=None if tested[j] else 'minimum_total_counts',p_value_underflow=False)
        diagnostic=dict(contrast_id=contrast.contrast_id,feature_id=feature,tested=bool(tested[j]),_LFC_converged=None,_genewise_converged=None,_MAP_converged=None)
        if tested[j]:
            observed=stats.results_df.loc[feature]
            failures=[]
            for key in ('_LFC_converged','_genewise_converged','_MAP_converged'):
                value=dds.var.loc[feature,key] if key in dds.var else None
                diagnostic[key]=None if value is None or pd.isna(value) else bool(value)
                if diagnostic[key] is False:failures.append(key)
            for out,col in [('base_mean','baseMean'),('effect_value','log2FoldChange'),('lfc_se','lfcSE'),('statistic','stat'),('wald_statistic','stat'),('p_value','pvalue'),('original_method_adjustment','padj')]:
                value=observed[col];row[out]=float(value) if np.isfinite(value) else None
            if failures:
                row.update(test_status='not_computable',reason='model_not_converged:'+','.join(failures),effect_value=None,p_value=None,statistic=None,wald_statistic=None,original_method_adjustment=None)
            elif row['p_value'] is None:row.update(reason='cooks_filtered_or_undefined_wald')
            else:row.update(test_status='tested',effect_reason=None,p_value_underflow=row['p_value']==0)
        convergence.append(diagnostic);output.append(row)
    parameters=frozen_parameters(config)
    diagnostics=dict(contrast_id=contrast.contrast_id,formula=formula,rank=rank,residual_degrees_freedom=len(matrix)-rank,
        parameters=parameters,design_columns=list(dds.obsm['design_matrix'].columns),design_matrix=design.tolist(),sample_unit_ids=ids,
        warnings=[str(w.message) for w in captured],fit_type_requested='parametric',
        fit_type_effective='mean' if any('mean-based' in str(w.message) for w in captured) else 'parametric')
    model=dict(diagnostics=diagnostics,model_sample_metadata=metadata_rows,model_convergence=convergence,
        size_factors=[dict(contrast_id=contrast.contrast_id,unit_id=uid,processed_version_id=key[0],sample_id=key[1],factor=float(f),method=config.size_factor_method) for uid,(key,_,_),f in zip(ids,ordered,factors)],
        model_counts=[dict(contrast_id=contrast.contrast_id,unit_id=uid,feature_id=f,counts=int(matrix[i,j]),tested=bool(tested[j])) for i,uid in enumerate(ids) for j,f in enumerate(features)],
        model_normalized_counts=[dict(contrast_id=contrast.contrast_id,unit_id=uid,feature_id=f,normalized_counts=float(normalized[i,j])) for i,uid in enumerate(ids) for j,f in enumerate(features)])
    return output,model
