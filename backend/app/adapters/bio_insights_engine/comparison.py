"""Fixed spot rank-sum and raw-count donor models for frozen comparison plans."""
from collections import defaultdict
import hashlib
import json
import warnings
import numpy as np
import pandas as pd
from scipy import sparse
from scipy.stats import rankdata, norm, false_discovery_control
from app.domain.bio_insights.contracts import ComparisonConfig
from app.domain.bio_insights.design import validate_design
from .inputs import load_processed


def adjust_families(rows, contrast_ids):
    """Predeclared tests include NA as one internally; excluded rows stay outside."""
    summary = {'by_contrast':{}}
    for row in rows: row.update(q_within_contrast=None, q_global_family=None)
    for cid in list(contrast_ids) + [None]:
        selected = [row for row in rows if row['tested'] and (cid is None or row['contrast_id']==cid)]
        counts = {'family_size':len(selected), 'valid_p_values':sum(r['p_value'] is not None for r in selected),
                  'na_p_values':sum(r['p_value'] is None for r in selected)}
        if cid is None:summary['global']=counts
        else:summary['by_contrast'][cid]=counts
        if not selected: continue
        vector = [1 if r['p_value'] is None else r['p_value'] for r in selected]
        if not np.isfinite(vector).all() or any(not 0<=v<=1 for v in vector): raise ValueError('p_value_invalid')
        adjusted = false_discovery_control(vector, method='bh')
        column = 'q_global_family' if cid is None else 'q_within_contrast'
        for row,q in zip(selected,adjusted):
            if row['p_value'] is not None: row[column]=float(q)
    return summary


def _identity(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def _selected(config, contrast, by_key):
    explicit={(e.processed_version_id,e.barcode) for e in config.excluded_observations}
    donors={e.donor for e in config.excluded_donors}
    result=[]
    for group in (contrast.numerator,contrast.denominator):
        keys=[(k.processed_version_id,k.barcode) for k in group.observation_keys]
        result.append([k for k in keys if k not in explicit and by_key[k]['donor'] not in donors])
    return result


def _base_row(feature, symbol, contrast, scope, family_id, n, spots, provenance):
    return {'row_key':_identity({'feature_id':feature,'contrast_id':contrast.contrast_id}),
            'feature_id':feature,'symbol':symbol,'contrast_id':contrast.contrast_id,
            'numerator':contrast.numerator.label,'denominator':contrast.denominator.label,
            'observation_level':'spot' if scope=='spot_exploratory' else 'donor','inference_scope':scope,
            'effect_name':'effect_log2_normalized' if scope=='spot_exploratory' else 'effect_log2fc',
            'effect_value':None,'effect_unit':'log2 normalized expression ratio' if scope=='spot_exploratory' else 'log2 count fold change',
            'statistic':None,'p_value':None,'q_within_contrast':None,'q_global_family':None,
            'correction_family_id':family_id,'n_numerator':n[0],'n_denominator':n[1],
            'spots_numerator':spots[0],'spots_denominator':spots[1],
            'donors_numerator':None if scope=='spot_exploratory' else n[0],
            'donors_denominator':None if scope=='spot_exploratory' else n[1],
            'mean_normalized_numerator':None,'mean_normalized_denominator':None,
            'detection_numerator':None,'detection_denominator':None,
            'lfc_se':None,'wald_statistic':None,'base_mean':None,
            'test_status':'not_computable','reason':None,'tested':True,'p_value_underflow':False,
            'data_driven_grouping':False,'provenance':provenance}


def run_comparison(payload, writer):
    if payload.get('schema_version')!=1 or payload.get('kind')!='bio_comparison': raise ValueError('comparison_payload_invalid')
    config=ComparisonConfig.model_validate(payload['config'])
    selected_sources=[s for s in payload['sources'] if s['source_kind']=='bio_processed_dataset_version']
    if not selected_sources or len(selected_sources)>100: raise ValueError('processed_sources_invalid')
    ids=[s['source_id'] for s in selected_sources]
    canonical=[s['metadata']['canonical_dataset_id'] for s in selected_sources]
    if len(set(ids))!=len(ids): raise ValueError('duplicate_processed_source')
    if len(set(canonical))!=len(canonical): raise ValueError('duplicate_canonical_dataset')
    for source in selected_sources:
        metadata=source['metadata']
        if (metadata['species_taxon_id'],metadata['namespace'],metadata['reference_version'])!=(
                config.species_taxon_id,config.namespace,config.reference_version): raise ValueError('incompatible_feature_metadata')
    loaded=[load_processed(s,config.mode) for s in selected_sources]
    common=sorted(set.intersection(*(set(s['feature_ids']) for s in loaded)))
    if not common: raise ValueError('empty_common_feature_axis')
    if len(config.contrasts)>10 or len(common)*len(config.contrasts)>1000000: raise ValueError('comparison_budget_exceeded')
    observations=[o for s in loaded for o in s['observations']]
    if len(observations)>20000: raise ValueError('observation_budget_exceeded')
    by_key={(o['processed_version_id'],o['barcode']):o for o in observations}
    if len(by_key)!=len(observations): raise ValueError('duplicate_observation_key')
    feature_exclusions=[]; matrices=defaultdict(list); ordered_keys=[]; symbols={}
    for source in loaded:
        index={f:i for i,f in enumerate(source['feature_ids'])}; columns=[index[f] for f in common]
        for feature in source['raw_feature_ids']:
            if feature not in common:
                feature_exclusions.append({'processed_version_id':source['source']['source_id'],'feature_id':feature,
                    'reason':'non_common_stable_id' if feature in index else 'not_in_eligible_gene_axis'})
        ordered_keys.extend(source['retained_keys']);symbols.update(source['symbols'])
        for layer in ('counts','normalized','log1p'):
            if layer in source: matrices[layer].append(source[layer][:,columns])
    matrices={name:sparse.vstack(values,format='csr') for name,values in matrices.items()}
    if sum(map(int,matrices['counts'].data))>np.iinfo(np.int64).max: raise ValueError('combined_counts_overflow')
    if sum(m.nnz for m in matrices.values())>30000000: raise ValueError('sparse_entry_budget_exceeded')
    index={key:i for i,key in enumerate(ordered_keys)}
    metadata=[]
    total=np.asarray(matrices['counts'].sum(0)).ravel()
    for source in loaded:
        meta=source['source']['metadata']
        metadata.append({'processed_version_id':source['source']['source_id'],
                         **{k:meta[k] for k in ['species_taxon_id','namespace','reference_version','canonical_dataset_id']},
                         'feature_count':len(source['feature_ids']),'counts_nonnegative_integer':True,
                         'counts_provenance':'raw_gene_expression','filtered_feature_count':int((total>=config.minimum_total_counts).sum()),
                         'common_feature_count':len(common)})
    preview=validate_design(config.model_dump(),observations,metadata)
    if not preview.executable:
        raise ValueError('design_blocked:'+','.join(r.code for r in preview.blocking_reasons))
    provenance={'sources':[{'source_kind':s['source_kind'],'source_id':s['source_id'],'sha256':s['sha256'],
                            'canonical_dataset_id':s['metadata']['canonical_dataset_id']} for s in selected_sources],
                'identity':payload.get('identity',{}),'feature_axis':'explicit_shared_stable_ids',
                'species_taxon_id':config.species_taxon_id,'namespace':config.namespace,'reference_version':config.reference_version}
    family_id=_identity({'plan':payload.get('identity',{}).get('plan_version_id'),'contrasts':config.family_contrast_ids})
    result_rows=[]; aggregate_rows=[]; aggregate_members=[]; bulk_rows=[]; diagnostics=[]
    scope='spot_exploratory' if config.mode=='spot_exploratory' else 'donor_inference'
    for contrast,units in zip(config.contrasts,preview.actual_units):
        if contrast.numerator.label==contrast.denominator.label: raise ValueError('contrast_labels_equal')
        keys=_selected(config,contrast,by_key); groups=[[index[k] for k in side] for side in keys]
        if config.mode=='spot_exploratory':
            # B02 may store float32 layers. Promote the scalar means before
            # pseudocount/ratio/log operations (NumPy 2 keeps float32 scalars).
            group_means=[np.asarray(matrices['normalized'][side].mean(0),dtype=np.float64).ravel() for side in groups]
            detection=[np.asarray((matrices['counts'][side]>0).mean(0)).ravel() for side in groups]
            both=matrices['log1p'][groups[0]+groups[1]].tocsc(); ng,nr=map(len,groups); size=ng+nr
            for j,feature in enumerate(common):
                row=_base_row(feature,symbols[feature],contrast,scope,family_id,[ng,nr],[ng,nr],provenance)
                row.update(mean_normalized_numerator=float(group_means[0][j]),mean_normalized_denominator=float(group_means[1][j]),
                           detection_numerator=float(detection[0][j]),detection_denominator=float(detection[1][j]),
                           effect_value=float(np.log2((group_means[0][j]+1e-9)/(group_means[1][j]+1e-9))),
                           data_driven_grouping=config.data_driven_grouping)
                values=both[:,j].toarray().ravel().astype('float64')
                _,ties=np.unique(values,return_counts=True)
                variance=ng*nr/12*((size+1)-np.sum(ties.astype(float)**3-ties)/(size*(size-1)))
                if variance<=0: row.update(reason='constant_gene',effect_value=None)
                else:
                    z=(rankdata(values,method='average')[:ng].sum()-ng*(size+1)/2)/np.sqrt(variance)
                    p=float(2*norm.sf(abs(z)))
                    row.update(statistic=float(z),p_value=p,test_status='tested',p_value_underflow=p==0)
                result_rows.append(row)
        else:
            fitted,agg,members,bulk,diag=_donor(contrast,groups,keys,by_key,matrices['counts'],common,config,
                                               symbols,scope,family_id,provenance)
            result_rows.extend(fitted);aggregate_rows.extend(agg);aggregate_members.extend(members);bulk_rows.extend(bulk);diagnostics.append(diag)
    family=adjust_families(result_rows,list(config.family_contrast_ids))
    writer.table('comparison_results',result_rows)
    writer.table('feature_exclusions',feature_exclusions,['processed_version_id','feature_id','reason'])
    writer.table('observation_exclusions',[r.model_dump() for r in preview.exclusions],['processed_version_id','barcode','reason'])
    writer.table('common_features',[{'feature_id':f,'symbol':symbols[f]} for f in common])
    writer.json('correction_families',family)
    if aggregate_rows:
        writer.table('aggregation_units',aggregate_rows);writer.table('aggregation_members',aggregate_members)
        writer.table('pseudobulk_counts',bulk_rows)
        writer.json('model_diagnostics',diagnostics)
    methods={'name':'two_sided_rank_sum_normal_tie_corrected' if scope=='spot_exploratory' else 'PyDESeq2_0.5.4_Wald',
             'direction':'numerator_relative_to_denominator','correction':'BH_predeclared_tests_NA_internal_one',
             'family_contrast_ids':config.family_contrast_ids,'data_driven_grouping':config.data_driven_grouping,
             'parameters':{'continuity_correction':False,'ties':'average_rank_variance_correction','effect_pseudocount':1e-9} if scope=='spot_exploratory' else
                 {'size_factors_fit_type':'poscounts','refit_cooks':False,'cooks_filter':True,'independent_filter':False,
                  'low_memory':True,'n_cpus':1,'lfc_shrinkage':False,'minimum_total_counts':config.minimum_total_counts},
             'warnings':preview.warnings,'model_diagnostics':diagnostics}
    summary={'row_count':len(result_rows),'feature_count':len(common),'contrast_count':len(config.contrasts),
             'family':family,'actual_units':[u.model_dump() for u in preview.actual_units],
             'not_computable_rows':sum(r['p_value'] is None for r in result_rows),
             'result_member_key':'comparison_results','data_driven_grouping':config.data_driven_grouping,
             'tested_universe_complete':True,'feature_exclusions':len(feature_exclusions),
             'observation_exclusions':len(preview.exclusions),'p_value_underflow_rows':sum(r['p_value_underflow'] for r in result_rows)}
    writer.json('comparison_design',preview.model_dump());writer.json('comparison_methods',methods)
    return {'summary':summary,'methods':methods,'inference_scope':scope,'provenance':provenance}


def _donor(contrast,groups,keys,by_key,counts,features,config,symbols,scope,family_id,provenance):
    from pydeseq2.dds import DeseqDataSet
    from pydeseq2.ds import DeseqStats
    from pydeseq2.default_inference import DefaultInference
    aggregates=[]; members=[]; values=[]
    # Denominator first is fixed and independent of selected input order.
    for side in (1,0):
        label=(contrast.numerator,contrast.denominator)[side].label
        donor_groups=defaultdict(list)
        for key,i in zip(keys[side],groups[side]):
            observation=by_key[key]
            if observation['condition']!=label: raise ValueError('condition_group_mismatch')
            donor_groups[observation['donor']].append((key,i))
        for donor,items in sorted(donor_groups.items()):
            unit_id='u'+_identity({'contrast':contrast.contrast_id,'donor':donor,'condition':label})[:24]
            v=np.asarray(counts[[i for _,i in items]].sum(0)).ravel().astype('int64')
            if not int(v.sum()): raise ValueError('zero_common_gene_library')
            values.append(v)
            aggregates.append({'contrast_id':contrast.contrast_id,'unit_id':unit_id,'donor':donor,'condition':label,
                               'batch':by_key[items[0][0]]['batch'],'spot_count':len(items),'library_counts':int(v.sum()),
                               'observation_keys':[{'processed_version_id':k[0],'barcode':k[1]} for k,_ in items]})
            for key,_ in items:members.append({'contrast_id':contrast.contrast_id,'unit_id':unit_id,
                                              'processed_version_id':key[0],'barcode':key[1]})
    if len(values)>200 or len(values)*len(features)>20000000: raise ValueError('pseudobulk_budget_exceeded')
    matrix=np.asarray(values,dtype='int64'); tested=matrix.sum(0)>=config.minimum_total_counts
    if not tested.any(): raise ValueError('no_features_after_filter')
    if np.any(matrix[:,tested].sum(1)==0): raise ValueError('zero_library_after_prefilter')
    ids=[a['unit_id'] for a in aggregates]
    frame=pd.DataFrame(matrix[:,tested],index=ids,columns=np.asarray(features)[tested])
    metadata=pd.DataFrame([{k:a[k] for k in ['condition','donor','batch']} for a in aggregates],index=ids)
    design='~ donor + condition' if config.mode=='donor_paired' else '~ batch + condition' if config.batch_adjustment else '~ condition'
    inference=DefaultInference(n_cpus=1)
    try:
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter('always')
            dds=DeseqDataSet(counts=frame,metadata=metadata,design=design,size_factors_fit_type='poscounts',
                             refit_cooks=False,low_memory=True,n_cpus=1,inference=inference,quiet=True)
            rank=int(np.linalg.matrix_rank(np.asarray(dds.obsm['design_matrix'],dtype=float)))
            if rank!=dds.obsm['design_matrix'].shape[1] or len(frame)-rank<=0: raise ValueError('actual_design_rank_invalid')
            dds.deseq2()
            statistics=DeseqStats(dds,contrast=['condition',contrast.numerator.label,contrast.denominator.label],
                                  cooks_filter=True,independent_filter=False,n_cpus=1,inference=inference,quiet=True)
            statistics.summary()
    except Exception as exc:
        raise ValueError('pseudobulk_model_failed:'+type(exc).__name__) from exc
    diagnostic={'contrast_id':contrast.contrast_id,'formula':design,'rank':rank,'residual_degrees_freedom':len(frame)-rank,
                'warnings':[str(w.message) for w in captured],'fit_type_requested':'parametric',
                'fit_type_effective':'mean' if any('mean-based' in str(w.message) for w in captured) else 'parametric'}
    result=[]; n=[len({by_key[k]['donor'] for k in group}) for group in keys]
    for j,feature in enumerate(features):
        row=_base_row(feature,symbols[feature],contrast,scope,family_id,n,list(map(len,groups)),provenance)
        if not tested[j]:row.update(tested=False,test_status='excluded',reason='minimum_total_counts')
        else:
            observed=statistics.results_df.loc[feature]
            row.update(base_mean=float(observed['baseMean']))
            failures=[key for key in ['_LFC_converged','_genewise_converged','_MAP_converged']
                      if key in dds.var and not pd.isna(dds.var.loc[feature,key]) and not bool(dds.var.loc[feature,key])]
            if failures:row.update(reason='model_not_converged:'+','.join(failures))
            else:
                for output,column in [('effect_value','log2FoldChange'),('lfc_se','lfcSE'),('statistic','stat'),('wald_statistic','stat'),('p_value','pvalue')]:
                    value=observed[column];row[output]=float(value) if np.isfinite(value) else None
                if row['p_value'] is None:row.update(reason='cooks_filtered_or_undefined_wald')
                else:row.update(test_status='tested',p_value_underflow=row['p_value']==0)
        result.append(row)
    bulk=[{'contrast_id':contrast.contrast_id,'unit_id':a['unit_id'],'feature_id':feature,'counts':int(matrix[i,j])}
          for i,a in enumerate(aggregates) for j,feature in enumerate(features)]
    return result,aggregates,members,bulk,diagnostic
