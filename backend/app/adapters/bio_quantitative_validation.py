"""Reconcile V2 results with frozen sources, parameters and full sample axes."""
import csv,json,math
from pathlib import Path
import numpy as np
from app.adapters.bio_tabular_process import _ReconciliationWriter


class _ContinuousReconciliationWriter(_ReconciliationWriter):
    """Exact table structure/metadata with a narrow cross-runtime float tolerance."""
    numeric_tables={'comparison_results','posthoc_results'}
    numeric_fields={'effect_value','statistic','p_value','q_within_contrast','q_global_family',
                    'original_method_adjustment','base_mean','lfc_se','wald_statistic'}

    def __init__(self,items):
        super().__init__();self.items=items

    def table(self,key,rows,fields=None):
        rows=list(rows)
        if key in self.numeric_tables:
            from itertools import zip_longest
            from app.adapters.bio_engine.manifest import clean
            columns=fields or (list(rows[0]) if rows else ['reason'])
            with Path(self.items[key]['path']).open(encoding='utf-8',newline='') as stream:
                reader=csv.DictReader(stream,delimiter='\t')
                if reader.fieldnames!=columns:raise ValueError('quantitative_table_columns_mismatch:'+key)
                for expected,actual in zip_longest(rows,reader):
                    if expected is None or actual is None:raise ValueError('quantitative_table_rows_mismatch:'+key)
                    for column in columns:
                        value=clean(expected.get(column))
                        text='' if value is None else json.dumps(value,ensure_ascii=False) if isinstance(value,(dict,list)) else str(value)
                        observed=actual[column]
                        if observed==text:continue
                        # No absolute tolerance: zero/underflow, NA, direction and discrete fields stay exact.
                        if column not in self.numeric_fields or value is None or value==0:raise ValueError('quantitative_table_value_mismatch:'+key+':'+column)
                        try:number=float(observed)
                        except (ValueError,TypeError):raise ValueError('quantitative_table_number_invalid')
                        if column in {'p_value','q_within_contrast','q_global_family','original_method_adjustment'} and not 0<=number<=1:raise ValueError('quantitative_table_probability_invalid')
                        if not math.isfinite(number) or number==0 or math.copysign(1,number)!=math.copysign(1,value) or not math.isclose(number,value,rel_tol=1e-12,abs_tol=0):raise ValueError('quantitative_table_number_mismatch:'+key+':'+column)
        return super().table(key,rows,fields)


def validate_quantitative(result,items,payload):
    from app.domain.bio_insights.quantitative_contracts import QuantitativeComparisonConfig
    from app.adapters.bio_insights_engine.quantitative import run_quantitative,prepared_inputs,selected_groups,comparison_methods
    from app.adapters.bio_insights_engine.comparison import adjust_families,_identity
    from app.adapters.bio_insights_engine.counts_model import frozen_parameters
    config=QuantitativeComparisonConfig.model_validate(payload['config'])
    if result['methods']['config']!=config.model_dump():raise ValueError('frozen_quantitative_config_mismatch')
    def rows(key):
        with Path(items[key]['path']).open(encoding='utf-8',newline='') as stream:return list(csv.DictReader(stream,delimiter='\t'))
    def doc(key):return json.loads(Path(items[key]['path']).read_bytes())
    if config.mode=='continuous':
        expected_writer=_ContinuousReconciliationWriter(items);expected=run_quantitative(payload,expected_writer)
        for member in expected_writer.artifacts:
            if member['key'] in expected_writer.numeric_tables:
                if items[member['key']]['format']!='tsv':raise ValueError('quantitative_table_format_mismatch')
                continue
            if any(items[member['key']][key]!=member[key] for key in ('format','size_bytes','sha256')):raise ValueError('quantitative_full_table_mismatch:'+member['key'])
        if expected['summary']!=result['summary'] or any(result['methods'].get(k)!=v for k,v in expected['methods'].items()):raise ValueError('quantitative_summary_mismatch')
        return
    config,sources,loaded,preview,features,keys,values,missing,by_key,annotations,exclusions=prepared_inputs(payload)
    if doc('comparison_design')!=preview.model_dump():raise ValueError('quantitative_design_mismatch')
    if doc('comparison_methods')['config']!=config.model_dump():raise ValueError('quantitative_method_mismatch')
    table=rows('comparison_results');index={k:i for i,k in enumerate(keys)}
    if len(table)!=len(features)*len(config.contrasts) or result['summary']['row_count']!=len(table):raise ValueError('quantitative_incomplete_results')
    result_map={(r['contrast_id'],r['feature_id']):r for r in table}
    if len(result_map)!=len(table):raise ValueError('duplicate_quantitative_result')
    def number(row,key):
        if row[key]=='':return None
        value=float(row[key])
        if not math.isfinite(value):raise ValueError('quantitative_nonfinite')
        return value
    adjusted=[];actual_counts=[];model_counts=rows('model_counts');norm_counts=rows('model_normalized_counts');model_samples=rows('model_sample_metadata');factors=rows('size_factors')
    diagnostics=doc('model_diagnostics');convergence=rows('model_convergence')
    if len(diagnostics)!=len(config.contrasts):raise ValueError('model_diagnostic_missing')
    if len(convergence)!=len(table):raise ValueError('model_convergence_incomplete')
    if not {'_LFC_converged','_genewise_converged','_MAP_converged'}<=set(convergence[0]):raise ValueError('model_convergence_columns_missing')
    convergence_map={(r['contrast_id'],r['feature_id']):r for r in convergence}
    if len(convergence_map)!=len(convergence):raise ValueError('model_convergence_duplicate')
    for contrast in config.contrasts:
        cid=contrast.contrast_id;group_keys,groups=selected_groups(config,contrast,index,by_key)
        order=[(key,i,label) for side in (1,0) for key,i in zip(group_keys[side],groups[side]) for label in [contrast.groups[side].label]]
        matrix=values[[i for _,i,_ in order]];tested=matrix.sum(0)>=config.minimum_total_counts
        ids=['s'+_identity(key)[:24] for key,_,_ in order]
        samples=[r for r in model_samples if r['contrast_id']==cid]
        if [(r['unit_id'],r['processed_version_id'],r['sample_id'],r['condition']) for r in samples]!=[(uid,key[0],key[1],label) for uid,(key,_,label) in zip(ids,order)]:raise ValueError('model_sample_mapping_mismatch')
        for sample,(key,_,_) in zip(samples,order):
            source=by_key[key]
            expected=dict(donor=source.get(config.pairing_field) or '',batch=source.get('batch') or '',biological_unit_id=source.get('biological_unit_id') or source.get('donor') or '')
            if any(sample[k]!=str(v) for k,v in expected.items()):raise ValueError('model_sample_metadata_mismatch')
        diagnostic=diagnostics[config.contrasts.index(contrast)]
        covariate='donor' if config.design=='paired' else 'batch' if config.batch_adjustment else None
        formula='~ '+covariate+' + condition' if covariate else '~ condition'
        levels=sorted({r[covariate] for r in samples})[1:] if covariate else []
        columns=['Intercept']+[f'{covariate}[T.{v}]' for v in levels]+[f'condition[T.{contrast.groups[0].label}]']
        design=np.array([[1]+[int(r[covariate]==v) for v in levels]+[int(r['condition']==contrast.groups[0].label)] for r in samples],dtype=float)
        rank=int(np.linalg.matrix_rank(design))
        if diagnostic.get('contrast_id')!=cid or diagnostic.get('formula')!=formula or diagnostic.get('sample_unit_ids')!=ids or diagnostic.get('design_columns')!=columns or diagnostic.get('design_matrix')!=design.tolist() or diagnostic.get('rank')!=rank or diagnostic.get('residual_degrees_freedom')!=len(samples)-rank or diagnostic.get('parameters')!=frozen_parameters(config):raise ValueError('model_design_or_parameters_mismatch')
        warnings=diagnostic.get('warnings')
        if not isinstance(warnings,list) or any(not isinstance(w,str) for w in warnings) or diagnostic.get('fit_type_requested')!='parametric' or diagnostic.get('fit_type_effective')!=('mean' if any('mean-based' in w for w in warnings) else 'parametric'):raise ValueError('model_fit_diagnostics_invalid')
        factor_rows=[r for r in factors if r['contrast_id']==cid]
        if [r['unit_id'] for r in factor_rows]!=ids or any(r['method']!=config.size_factor_method for r in factor_rows):raise ValueError('size_factor_axis_mismatch')
        sf=np.array([float(r['factor']) for r in factor_rows])
        if not np.isfinite(sf).all() or np.any(sf<=0):raise ValueError('size_factor_invalid')
        fit=matrix[:,tested].astype(float)
        if config.size_factor_method=='ratio':
            usable=(fit>0).all(0)
            if not usable.any():raise ValueError('ratio_no_positive_features')
            logs=np.log(fit[:,usable]);expected=np.exp(np.median(logs-logs.mean(0),axis=1))
        else:
            logs=np.zeros_like(fit);np.log(fit,out=logs,where=fit>0);means=logs.mean(0);usable=means>0
            expected=np.array([np.exp(np.median(np.log(row[usable&(row>0)])-means[usable&(row>0)])) for row in fit]);expected/=np.exp(np.log(expected).mean())
        if not np.allclose(sf,expected,rtol=1e-8,atol=1e-10):raise ValueError('size_factor_formula_mismatch')
        actual=[r for r in model_counts if r['contrast_id']==cid];normalized=[r for r in norm_counts if r['contrast_id']==cid]
        if [r['feature_id'] for r in actual]!=features or [r['feature_id'] for r in normalized]!=features:raise ValueError('model_matrix_size_mismatch')
        for j,(rawrow,normrow) in enumerate(zip(actual,normalized)):
            if any(v!='' for k,v in rawrow.items() if k not in {'contrast_id','feature_id',*ids}) or any(v!='' for k,v in normrow.items() if k not in {'contrast_id','feature_id',*ids}):raise ValueError('model_extra_sample_values')
            for i,uid in enumerate(ids):
                if int(rawrow[uid])!=int(matrix[i,j]):raise ValueError('model_counts_mismatch')
                if not np.isclose(float(normrow[uid]),matrix[i,j]/sf[i],rtol=1e-10,atol=1e-10):raise ValueError('model_normalized_counts_mismatch')
        for j,feature in enumerate(features):
            row=result_map[(cid,feature)]
            conv=convergence_map[(cid,feature)]
            if (conv['tested']=='True')!=bool(tested[j]):raise ValueError('model_convergence_tested_mismatch')
            flags=['_LFC_converged','_genewise_converged','_MAP_converged']
            if any(conv.get(k,'') not in ('','True','False') for k in flags):raise ValueError('model_convergence_invalid')
            failures=[k for k in flags if conv.get(k)=='False']
            if failures and (row['reason']!='model_not_converged:'+','.join(failures) or row['test_status']!='not_computable' or any(row[k]!='' for k in ('p_value','effect_value','statistic','original_method_adjustment'))):raise ValueError('model_convergence_result_mismatch')
            if row['row_key']!=_identity({'feature_id':feature,'contrast_id':cid}) or row['observation_level']!='sample' or row['inference_scope']!=result['inference_scope']:raise ValueError('quantitative_result_axis_mismatch')
            if (row['numerator'],row['denominator'])!=(contrast.groups[0].label,contrast.groups[1].label) or [int(row['n_numerator']),int(row['n_denominator'])]!=list(map(len,groups)):raise ValueError('quantitative_actual_n_mismatch')
            if json.loads(row['feature_annotation'])!=annotations[feature] or json.loads(row['group_sizes'])!={g.label:len(indices) for g,indices in zip(contrast.groups,groups)} or row['n_pairs']!=(str(len(groups[0])) if config.design=='paired' else '') or row['provenance']!='system_computed':raise ValueError('quantitative_feature_metadata_mismatch')
            if row['symbol']!=(annotations[feature].get('display_name') or feature) or row['feature_kind']!=(annotations[feature].get('feature_kind') or '') or row['correction_family_id']!=_identity({'plan':payload.get('identity',{}).get('plan_version_id'),'contrasts':config.family_contrast_ids}) or row['data_driven_grouping']!=str(config.data_driven_grouping):raise ValueError('quantitative_result_metadata_mismatch')
            if (row['tested']=='True')!=bool(tested[j]) or row['effect_name']!='effect_log2fc' or row['effect_unit']!='log2 count fold change':raise ValueError('quantitative_effect_contract_mismatch')
            p=number(row,'p_value')
            if p is not None and not 0<=p<=1:raise ValueError('p_value_invalid')
            for field in ('effect_value','lfc_se','statistic','wald_statistic','original_method_adjustment'):number(row,field)
            if row['statistic']!=row['wald_statistic']:raise ValueError('wald_statistic_mismatch')
            if p is not None:
                from scipy.special import ndtr
                effect=number(row,'effect_value');se=number(row,'lfc_se');stat=number(row,'statistic')
                if row['test_status']!='tested' or row['reason'] or row['effect_reason'] or se is None or se<=0 or not np.isclose(stat,effect/se,rtol=1e-9,atol=1e-10) or not np.isclose(p,2*ndtr(-abs(stat)),rtol=1e-9,atol=1e-300):raise ValueError('wald_relationship_mismatch')
            if row['p_value_underflow']!=str(p==0):raise ValueError('p_underflow_mismatch')
            padj=number(row,'original_method_adjustment')
            if padj is not None and not 0<=padj<=1:raise ValueError('original_method_adjustment_invalid')
            if tested[j] and not np.isclose(number(row,'base_mean'),np.mean(matrix[:,j]/sf),rtol=1e-8,atol=1e-8):raise ValueError('base_mean_mismatch')
            if not tested[j] and (row['reason']!='minimum_total_counts' or p is not None):raise ValueError('prefilter_mismatch')
            adjusted.append(dict(tested=bool(tested[j]),contrast_id=cid,p_value=p,row=row))
            actual_counts.append(dict(contrast_id=cid,feature_id=feature,group_sizes={g.label:len(indices) for g,indices in zip(contrast.groups,groups)},n_pairs=len(groups[0]) if config.design=='paired' else None,missing_policy=config.missing_policy))
    family=adjust_families(adjusted,config.family_contrast_ids)
    if family!=doc('correction_families') or family!=result['summary']['family']:raise ValueError('correction_family_mismatch')
    for item in adjusted:
        for field in ('q_within_contrast','q_global_family'):
            observed=number(item['row'],field);expected=item[field]
            if (observed is None)!=(expected is None) or observed is not None and not np.isclose(observed,expected,rtol=1e-10,atol=0):raise ValueError('quantitative_q_mismatch')
    if result['summary']!=dict(row_count=len(table),feature_count=len(features),contrast_count=len(config.contrasts),family=family,actual_units=preview.actual_units,
        not_computable_rows=sum(r['p_value']=='' for r in table),result_member_key='comparison_results',tested_universe_complete=True,feature_exclusions=len(exclusions),sample_exclusions=len(preview.exclusions),data_driven_grouping=config.data_driven_grouping,observation_level='sample'):raise ValueError('quantitative_summary_mismatch')
    method=doc('comparison_methods')
    expected_layer={k:v for k,v in loaded[0]['layer'].items() if k not in ('values','missing','shape')}
    if method!=comparison_methods(config,result['inference_scope'],expected_layer,preview,diagnostics) or any(result['methods'].get(k)!=v for k,v in method.items()):raise ValueError('quantitative_model_methods_mismatch')
    writer=_ReconciliationWriter()
    writer.table('feature_sample_counts',actual_counts)
    writer.table('feature_exclusions',exclusions,['processed_version_id','feature_id','reason']);writer.table('sample_exclusions',preview.exclusions,['processed_version_id','sample_id','reason'])
    writer.table('common_features',[dict(feature_id=f,symbol=annotations[f].get('display_name') or f,feature_kind=annotations[f].get('feature_kind')) for f in features])
    writer.table('posthoc_results',[],['feature_id','contrast_id','numerator','denominator','method','effect_name','effect_value','effect_unit','statistic','p_value','original_method_adjustment','adjustment'])
    for member in writer.artifacts:
        if any(items[member['key']][key]!=member[key] for key in ('format','size_bytes','sha256')):raise ValueError('quantitative_support_table_mismatch')
