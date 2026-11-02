"""Dedicated qPCR recipe over audited Cq wells and biological sample units."""
from statistics import mean
from app.domain.bio_insights.qpcr_design import prepare_qpcr, validate_qpcr_design, key
from app.domain.comparison.kernel import compute_comparison, ComparisonError
from .comparison import adjust_families

def run_qpcr(payload,writer):
    data=prepare_qpcr(payload['config'],payload['sources']);config=data['config']
    preview=validate_qpcr_design(config,payload['sources'])
    if not preview.executable:raise ValueError('qpcr_design_blocked:'+','.join(r.code for r in preview.blocking_reasons))
    family_id=key(dict(plan=payload['identity'].get('plan_version_id'),targets=config.targets,contrasts=config.family_contrast_ids,strata=sorted({r['stratum'] for r in data['samples']})))
    scale='delta_cq' if config.quantification=='delta_delta_cq' else 'log2_signal'
    rows=[];plot=[]
    inference_strata=['within_plate_pairs'] if config.paired_plate_policy=='within_plate_differences' else sorted({r['stratum'] for r in data['samples']})
    for stratum in inference_strata:
        for contrast in config.contrasts:
            for target in config.targets:
                groups=[[r for r in data['samples'] if (stratum=='within_plate_pairs' or r['stratum']==stratum) and r['condition']==condition and r['target_id']==target and r['reason'] is None] for condition in (contrast.numerator,contrast.denominator)]
                if config.design=='paired':
                    maps=[{r['pair_id']:r for r in group} for group in groups];pairs=sorted(set(maps[0])&set(maps[1]));groups=[[m[p] for p in pairs] for m in maps]
                values=[[r[scale] for r in group] for group in groups]
                log_effect=mean(r['log2_signal'] for r in groups[0])-mean(r['log2_signal'] for r in groups[1]) if all(groups) else None
                row=dict(row_key=key([stratum,target,contrast.contrast_id]),feature_id=target,symbol=target,contrast_id=contrast.contrast_id,stratum=stratum,numerator=contrast.numerator,denominator=contrast.denominator,
                    observation_level='sample',inference_scope='sample_inference',effect_name='log2_mean_difference',effect_value=log_effect,effect_unit='log2 relative expression',
                    statistical_scale=scale,statistical_effect_value=None,statistic=None,p_value=None,q_within_contrast=None,q_global_family=None,
                    correction_family_id=family_id,n_numerator=len(groups[0]),n_denominator=len(groups[1]),n_pairs=len(groups[0]) if config.design=='paired' else None,
                    tested=True,test_status='not_computable',reason=None,provenance='system_computed',ci_log2_low=None,ci_log2_high=None,fold_change=2**log_effect if log_effect is not None and -1022<log_effect<1023 else None,
                    ci_fold_low=None,ci_fold_high=None,ci_type='95% pointwise confidence interval',ci_reason='test_not_computable',p_value_underflow=False)
                try:computed=compute_comparison(values,method=config.method)
                except ComparisonError as exc:
                    if exc.code not in ('comparison_sample_size','comparison_constant','comparison_near_constant'):raise
                    row['reason']=exc.code
                else:
                    interval=computed['confidence_interval'];row.update(statistic=computed['statistic']['value'],p_value=computed['p_value']['value'],statistical_effect_value=computed['estimate']['value'],test_status='tested',ci_reason=interval['reason'])
                    if interval['low'] is not None and interval['high'] is not None:
                        low,high=(-interval['high'],-interval['low']) if scale=='delta_cq' else (interval['low'],interval['high'])
                        row.update(ci_log2_low=low,ci_log2_high=high)
                        if -1022<low<1023 and -1022<high<1023:row.update(ci_fold_low=2**low,ci_fold_high=2**high)
                        else:row['ci_reason']='fold_interval_out_of_finite_range'
                    row['p_value_underflow']=row['p_value']==0
                rows.append(row)
                for side,group in enumerate(groups):
                    plot.extend(dict(row_key=r['row_key'],feature_id=target,contrast_id=contrast.contrast_id,stratum=stratum,plate_id=r['plate_id'],sample_id=r['sample_id'],biological_unit_id=r['biological_unit_id'],pair_id=r['pair_id'],condition=r['condition'],group_index=side,
                        delta_cq=r['delta_cq'],log2_quantity=r['log2_quantity'],relative_quantity=r['relative_quantity'],measurement_unit='fold',error_type='none; individual biological sample',n_is_technical_wells=False) for r in group)
    family=adjust_families(rows,config.family_contrast_ids)
    methods=dict(name=config.recipe,config=config.model_dump(mode='json'),quantification=config.quantification,
        statistical_method=config.method,statistical_scale=scale,observation_level='sample',inference_unit='biological_unit_id',
        direction='positive delta Cq numerator-minus-denominator means lower expression; effect_value is log2 expression numerator-minus-denominator',
        technical_aggregation='Included technical wells: arithmetic mean Cq per sample x assay x plate; technical wells do not increase biological n.',
        reference_aggregation='Equal assay Cq means for delta-delta-Cq; geometric mean of reference efficiency ratios for efficiency correction; no missing-reference fallback.',
        calibrator_aggregation='Equal biological sample weights after technical averaging; incomplete calibrators make dependent quantities NA.',
        cross_plate=config.cross_plate,cross_plate_basis=config.cross_plate_basis,reference_basis=config.reference_basis,
        paired_plate_policy=config.paired_plate_policy,paired_plate_basis=config.paired_plate_basis,
        paired_plate_inference='When selected, only complete same-plate pair differences enter one paired test; no across-plate Cq pooling or common calibrator claim.',
        efficiency_factors={a:e.factor for a,e in config.efficiencies.items()},equal_efficiency_basis=config.equal_efficiency_basis,
        missing='Undetected/missing/excluded wells retained with reason, no zero/max-cycle imputation; feature complete cases or complete pairs.',
        correction='BH over all frozen target x contrast x plate-stratum tests; NA internally 1 and restored NA.',family_contrast_ids=config.family_contrast_ids,
        interval='Mean tests: 95% pointwise log-scale CI, exponentiated ordered endpoints; rank methods have no fold CI.',
        figures='Individual biological sample points and complete-pair lines, no symmetric fold error bars.',
        species_taxon_id=config.species_taxon_id,namespace=config.namespace,reference_version=config.reference_version,
        input_identity=dict(file_source_id=data['source']['source_id'],file_sha256=data['source']['sha256'],parse_version_id=config.parse_version_id,sheet=config.sheet),
        method_references=['Pfaffl 2001 doi:10.1093/nar/29.9.e45','MIQE 2.0 doi:10.1093/clinchem/hvaf043'],
        limitations='Software checks are not experimental quality certification or biological validation.',warnings=preview.warnings)
    writer.table('qpcr_well_audit',data['audit']);writer.table('qpcr_technical_summary',data['technical']);writer.table('qpcr_sample_quantities',data['samples'])
    writer.table('qpcr_calibration',data['calibration']);writer.table('qpcr_original_checks',data['original_checks'],list(data['original_checks'][0]) if data['original_checks'] else ['row_key','sample_id','plate_id','target_id','metric','original_value','recomputed_value','difference','tolerance','decision','unit','precision_basis','original_report_source','reason'])
    writer.table('comparison_results',rows);writer.table('qpcr_plot_data',plot,list(plot[0]) if plot else ['row_key','feature_id','contrast_id','stratum','sample_id','biological_unit_id','pair_id','condition','group_index','delta_cq','log2_quantity','relative_quantity','measurement_unit','error_type','n_is_technical_wells'])
    writer.json('comparison_design',preview.model_dump(mode='json'));writer.json('correction_families',family);writer.json('comparison_methods',methods)
    return dict(summary=dict(row_count=len(rows),feature_count=len(config.targets),contrast_count=len(config.contrasts),well_count=len(data['audit']),biological_units=len({r['biological_unit_id'] for r in data['samples']}),
        sample_count=len({r['sample_id'] for r in data['samples']}),result_member_key='comparison_results',tested_universe_complete=True,not_computable_rows=sum(r['p_value'] is None for r in rows),
        noncomputable_quantities=sum(r['reason'] is not None for r in data['samples']),family=family,actual_units=preview.actual_units,observation_level='sample'),methods=methods,inference_scope='sample_inference',provenance='system_computed')
