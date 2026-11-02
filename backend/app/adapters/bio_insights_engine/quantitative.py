"""Frozen sample-level continuous and raw-count comparisons."""
import math
import numpy as np
from app.domain.bio_insights.quantitative_contracts import QuantitativeComparisonConfig,quantitative_scope
from app.domain.bio_insights.quantitative_design import validate_quantitative_design,sample_key
from app.domain.comparison.kernel import compute_comparison,ComparisonError
from .comparison import adjust_families,_identity
from .quantitative_inputs import load_quantitative


def prepared_inputs(payload):
    config=QuantitativeComparisonConfig.model_validate(payload['config'])
    sources=[s for s in payload['sources'] if s['source_kind']=='bio_processed_dataset_version']
    loaded=[load_quantitative(s,config) for s in sources]
    verified_sources=[{**data['source'],'metadata':{**data['source']['metadata'],'feature_ids':data['raw_feature_ids'],'retained_feature_ids':data['feature_ids']}} for data in loaded]
    preview=validate_quantitative_design(config,verified_sources)
    if not preview.executable:raise ValueError('quantitative_design_blocked:'+','.join(r.code for r in preview.blocking_reasons))
    common=sorted(set.intersection(*(set(s['feature_ids']) for s in loaded)))
    if not common or len(common)*len(config.contrasts)>1000000:raise ValueError('quantitative_feature_budget')
    keys=[];values=[];missing=[];annotations={};exclusions=[]
    for data in loaded:
        index={f:i for i,f in enumerate(data['feature_ids'])};columns=[index[f] for f in common]
        keys.extend(data['retained_keys']);values.append(data['values'][:,columns]);missing.append(data['missing'][:,columns]);annotations.update(data['annotations'])
        exclusions.extend(dict(processed_version_id=data['source']['source_id'],feature_id=f,reason='non_common_or_processing_excluded') for f in data['raw_feature_ids'] if f not in common)
    if len(keys)*len(common)>1000000:raise ValueError('quantitative_matrix_budget')
    by_key={sample_key(r):r for source in sources for r in source['metadata']['observations']}
    return config,sources,loaded,preview,common,keys,np.vstack(values),np.vstack(missing),by_key,annotations,exclusions


def selected_groups(config,contrast,index,by_key):
    excluded={sample_key(e) for e in config.excluded_samples}
    groups=[[sample_key(s) for s in g.sample_keys if sample_key(s) not in excluded] for g in contrast.groups]
    if config.design=='paired':
        maps=[{by_key[k][config.pairing_field]:k for k in group} for group in groups]
        pairs=sorted(maps[0]);groups=[[m[p] for p in pairs] for m in maps]
    return groups,[[index[k] for k in group] for group in groups]


def feature_groups(values,missing,groups,j,paired):
    if paired:
        complete=~missing[groups[0],j]&~missing[groups[1],j]
        return [values[g,j][complete].astype(float).tolist() for g in groups]
    return [values[g,j][~missing[g,j]].astype(float).tolist() for g in groups]


def comparison_methods(config,scope,layer,preview,diagnostics):
    methods=dict(name='PyDESeq2_0.5.4_Wald' if config.mode=='bulk_counts' else config.method,config=config.model_dump(),observation_level='sample',inference_scope=scope,
        inference_unit=config.inference_unit,analysis_layer=config.analysis_layer,layer=layer,direction='groups[0] relative to groups[1]; omnibus has no single effect',
        correction='BH_predeclared_tests_NA_internal_one',family_contrast_ids=config.family_contrast_ids,posthoc=config.posthoc,
        missing='per-feature complete cases or complete pairs; no imputation; zero retained; LOD/nonrandom missingness may bias results',
        biological_n_by_contrast={u['contrast_id']:u['biological_n'] for u in preview.actual_units},warnings=preview.warnings,
        species_taxon_id=config.species_taxon_id,namespace=config.namespace,reference_version=config.reference_version,model_diagnostics=diagnostics)
    if config.inference_unit=='technical':methods['technical_replicate_qc']=dict(member_key='technical_replicate_qc',grouping='explicit frozen contrast.groups after declared sample exclusions',
        statistics='mean=fsum(x)/n; sample SD=sqrt(fsum((x-mean)^2)/(n-1)); CV=sample SD/positive mean',
        missing='per-group measured values; no imputation; full features and missing counts retained',
        cv_applicability='nonnegative linear measurements and positive mean only; nonlinear/log scales or n<2 produce NA with reason',
        inference='descriptive technical repeat consistency only; no P/q and biological n=0')
    return methods


def technical_qc_row(contrast,group,feature,measured,total,layer):
    n=len(measured);mean=math.fsum(measured)/n if n else None
    sd=math.sqrt(math.fsum((x-mean)**2 for x in measured)/(n-1)) if n>=2 else None
    linear=layer['scale'] in {'raw_counts','tpm','fpkm','normalized','intensity','relative_abundance','concentration'} and layer.get('transform','none')=='none'
    reason='no_measured_values' if not n else 'insufficient_measurements' if n<2 else 'nonlinear_scale' if not linear else 'nonpositive_mean' if mean<=0 else 'negative_measurements' if any(x<0 for x in measured) else None
    return dict(row_key=_identity(dict(kind='technical_replicate_qc',contrast_id=contrast.contrast_id,group=group.label,feature_id=feature)),contrast_id=contrast.contrast_id,group=group.label,feature_id=feature,n_total=total,n_measured=n,n_missing=total-n,
        mean=mean,sample_sd=sd,coefficient_of_variation=sd/mean if reason is None else None,cv_status='available' if reason is None else 'not_applicable',cv_reason=reason,
        measurement_unit=layer['unit'],observation_level='sample',inference_scope='sample_exploratory',biological_n=0)


def run_quantitative(payload,writer):
    config,sources,loaded,preview,features,keys,values,missing,by_key,annotations,exclusions=prepared_inputs(payload)
    index={k:i for i,k in enumerate(keys)};scope=quantitative_scope(config,[s['metadata']['assay'] for s in sources])
    family_id=_identity({'plan':payload.get('identity',{}).get('plan_version_id'),'contrasts':config.family_contrast_ids})
    rows=[];counts=[];posthoc=[];models=[];technical_qc=[]
    layer={k:v for k,v in loaded[0]['layer'].items() if k not in ('values','missing','shape')}
    for contrast in config.contrasts:
        group_keys,groups=selected_groups(config,contrast,index,by_key)
        fitted=None
        if config.mode=='bulk_counts':
            from .counts_model import fit_counts
            fitted,model=fit_counts(values,features,contrast,groups,group_keys,by_key,config);models.append(model)
        for j,feature in enumerate(features):
            group_values=feature_groups(values,missing,groups,j,config.design=='paired');ns=list(map(len,group_values));annotation=annotations[feature]
            if config.inference_unit=='technical':
                measured_groups=feature_groups(values,missing,groups,j,False)
                technical_qc.extend(technical_qc_row(contrast,group,feature,measured,len(indices),layer) for group,indices,measured in zip(contrast.groups,groups,measured_groups))
            row=dict(row_key=_identity({'feature_id':feature,'contrast_id':contrast.contrast_id}),feature_id=feature,symbol=annotation.get('display_name') or feature,
                feature_kind=annotation.get('feature_kind'),contrast_id=contrast.contrast_id,numerator=contrast.groups[0].label if config.design!='multiple' else None,
                denominator=contrast.groups[1].label if config.design!='multiple' else None,observation_level='sample',inference_scope=scope,
                effect_name=None,effect_value=None,effect_unit=None,effect_reason='not_computable',statistic=None,p_value=None,
                q_within_contrast=None,q_global_family=None,original_method_adjustment=None,correction_family_id=family_id,
                n_numerator=ns[0],n_denominator=ns[1],n_pairs=ns[0] if config.design=='paired' else None,
                group_sizes={g.label:n for g,n in zip(contrast.groups,ns)},tested=True,test_status='not_computable',reason=None,
                p_value_underflow=False,data_driven_grouping=config.data_driven_grouping,provenance='system_computed',
                base_mean=None,lfc_se=None,wald_statistic=None,feature_annotation=annotation)
            if fitted is not None:row.update(fitted[j])
            else:
                try:
                    computed=compute_comparison(group_values,method=config.method,posthoc=config.posthoc)
                except ComparisonError as exc:
                    if exc.code not in ('comparison_sample_size','comparison_constant','comparison_near_constant'):raise
                    row['reason']=exc.code
                else:
                    estimate=computed['estimate'];row.update(effect_name=estimate['name'],effect_value=estimate['value'],effect_unit=layer['unit'] if estimate['unit']=='outcome' else estimate['unit'],
                        effect_reason=estimate['reason'],statistic=computed['statistic']['value'],p_value=computed['p_value']['value'],test_status='tested')
                    row['p_value_underflow']=row['p_value']==0
                    for pair in computed['pairwise']:
                        posthoc.append(dict(feature_id=feature,contrast_id=contrast.contrast_id,numerator=contrast.groups[pair['left_index']].label,
                            denominator=contrast.groups[pair['right_index']].label,method=pair['method'],effect_name=pair['estimate']['name'],effect_value=pair['estimate']['value'],
                            effect_unit=layer['unit'] if pair['estimate']['unit']=='outcome' else pair['estimate']['unit'],statistic=pair['statistic']['value'],p_value=pair['p_value']['value'],
                            original_method_adjustment=pair['adjusted_p_value'],adjustment=pair['adjustment']))
            counts.append(dict(contrast_id=contrast.contrast_id,feature_id=feature,group_sizes=row['group_sizes'],n_pairs=row['n_pairs'],missing_policy=config.missing_policy))
            rows.append(row)
    family=adjust_families(rows,config.family_contrast_ids)
    writer.table('comparison_results',rows);writer.table('feature_sample_counts',counts)
    if config.inference_unit=='technical':writer.table('technical_replicate_qc',technical_qc)
    writer.table('posthoc_results',posthoc,['feature_id','contrast_id','numerator','denominator','method','effect_name','effect_value','effect_unit','statistic','p_value','original_method_adjustment','adjustment'])
    writer.table('feature_exclusions',exclusions,['processed_version_id','feature_id','reason']);writer.table('sample_exclusions',preview.exclusions,['processed_version_id','sample_id','reason'])
    writer.table('common_features',[dict(feature_id=f,symbol=annotations[f].get('display_name') or f,feature_kind=annotations[f].get('feature_kind')) for f in features])
    writer.json('comparison_design',preview.model_dump());writer.json('correction_families',family)
    if models:
        for key,value_key in (('model_counts','counts'),('model_normalized_counts','normalized_counts')):
            tables=[];fields=['contrast_id','feature_id']
            for model in models:
                cid=model['diagnostics']['contrast_id'];wide={f:dict(contrast_id=cid,feature_id=f) for f in features}
                for entry in model.pop(key):
                    wide[entry['feature_id']][entry['unit_id']]=entry[value_key]
                    if entry['unit_id'] not in fields:fields.append(entry['unit_id'])
                tables.extend(wide.values())
            if len(fields)>512:raise ValueError('model_export_sample_limit')
            writer.table(key,tables,fields)
        for key in ('model_sample_metadata','size_factors','model_convergence'):
            writer.table(key,[row for model in models for row in model[key]])
        writer.json('model_diagnostics',[m['diagnostics'] for m in models])
    methods=comparison_methods(config,scope,layer,preview,[m['diagnostics'] for m in models])
    writer.json('comparison_methods',methods)
    summary=dict(row_count=len(rows),feature_count=len(features),contrast_count=len(config.contrasts),family=family,actual_units=preview.actual_units,
        not_computable_rows=sum(r['p_value'] is None for r in rows),result_member_key='comparison_results',tested_universe_complete=True,
        feature_exclusions=len(exclusions),sample_exclusions=len(preview.exclusions),data_driven_grouping=config.data_driven_grouping,observation_level='sample')
    return dict(summary=summary,methods=methods,inference_scope=scope,provenance='system_computed')
