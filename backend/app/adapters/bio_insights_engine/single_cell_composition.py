"""Count fixed single-cell labels and call the isolated native propeller bridge."""
import io
from app.domain.bio_insights.single_cell_composition_contracts import SingleCellCompositionConfig
from app.domain.bio_insights.single_cell_composition import composition_data,validate_composition_design
from .inputs import load_processed,document


def run_composition(payload,writer):
    config=SingleCellCompositionConfig.model_validate(payload['config'])
    processed=next(s for s in payload['sources'] if s['source_kind']=='bio_processed_dataset_version' and s['source_id']==config.processed_source_id)
    annotation=next(s for s in payload['sources'] if s['source_kind']=='bio_annotation_version' and s['source_id']==config.annotation_source_id)
    if document(annotation['members']['assignments'])!=annotation['metadata']['assignments']:raise ValueError('annotation_assignments_mismatch')
    loaded=load_processed(processed,'donor_paired')
    data=composition_data(config,payload['sources'],loaded['observations'])
    preview=validate_composition_design(config,payload['sources'],loaded['observations'])
    if not preview.executable:raise ValueError('composition_design_blocked:'+','.join(r.code for r in preview.blocking_reasons))
    units=data['units'];categories=data['categories']
    single_condition=config.mode=='descriptive' and config.numerator==config.denominator
    label_names={r['id']:r.get('name') or r['id'] for r in annotation['metadata']['labels'] if r['id'] in config.label_ids}
    matrix=[[next(r['cell_count'] for r in data['counts'] if r['unit_id']==u['unit_id'] and (r['category'],r['label_id'])==c) for c in categories] for u in units]
    labels=[label if category=='label' else '__status_'+category for category,label in categories]
    native={}
    if config.mode!='descriptive':
        from app.adapters.single_cell_r.bridge import get_bridge
        native=get_bridge().propeller(matrix,[u['unit_id'] for u in units],labels,[u['condition'] for u in units],
            [u['donor'] for u in units],[u['batch'] or '' for u in units],config.mode,transform=config.transform,
            batch_adjustment=config.batch_adjustment,numerator=config.numerator,denominator=config.denominator)
        if native.get('status') not in ('ok','completed','not_computable'):raise ValueError('propeller_result_invalid')
        if native.get('sample_ids')!=[u['unit_id'] for u in units] or native.get('label_ids')!=labels:raise ValueError('propeller_axis_mismatch')
    native_rows={r['label_id']:r for r in native.get('rows',[])}
    results=[]
    for (category,label),native_label in zip(categories,labels):
        proportions=[[r['proportion'] for r in data['counts'] if r['condition']==condition and (r['category'],r['label_id'])==(category,label)] for condition in (config.denominator,config.numerator)]
        means=[sum(p)/len(p) if p else None for p in proportions]
        if single_condition:means[1]=None
        r=native_rows.get(native_label,{})
        status='not_requested' if config.mode=='descriptive' else 'not_computable' if r.get('p_value') is None else 'tested'
        results.append(dict(category=category,label_id=label,numerator=config.numerator,denominator=config.denominator,
            mean_proportion_denominator=means[0],mean_proportion_numerator=means[1],proportion_difference=means[1]-means[0] if None not in means else None,
            proportion_ratio=means[1]/means[0] if means[0] and means[1] is not None else None,ratio_status='not_applicable_single_condition' if single_condition else 'finite' if means[0] else 'zero_denominator',
            t_statistic=r.get('t_statistic'),p_value=r.get('p_value'),p_adjust=r.get('p_adjust'),inference_status=status,
            reason='single_condition_description' if single_condition else 'descriptive_only' if config.mode=='descriptive' else r.get('reason') or native.get('reason')))
    writer.table('composition_counts',data['counts']);writer.table('composition_units',units)
    writer.table('composition_assignments',data['assignments']);writer.table('composition_results',results)
    writer.json('composition_design',preview.model_dump())
    methods=dict(name='single_cell_composition_descriptive' if config.mode=='descriptive' else 'speckle_propeller',
        config=config.model_dump(mode='json'),single_condition_description=single_condition,direction='not_applicable_single_condition' if single_condition else 'numerator_relative_to_denominator',denominator='all_retained_cells_in_selected_conditions',
        aggregation='donor_x_condition_technical_samples_merged',labels_confirmed=config.labels_confirmed,label_basis=config.label_basis,
        actual_units=[u.model_dump() for u in preview.actual_units],warnings=preview.warnings,label_names=label_names,
        parameters=native.get('parameters',{}),versions=native.get('versions',{}),design=native.get('design',[]),
        design_columns=native.get('design_columns',[]),contrast=native.get('contrast',[]),logs=native.get('logs',[]),
        references=['https://bioconductor.org/packages/3.20/bioc/html/speckle.html','https://doi.org/10.1093/bioinformatics/btac582'],
        inference_status='not_requested' if config.mode=='descriptive' else native.get('status'),inference_reason=native.get('reason'))
    writer.json('composition_methods',methods)
    if native:writer.json('propeller_native',native)
    _plot(data,writer,label_names)
    return dict(summary=dict(row_count=len(results),total_cells=len(data['assignments']),unit_count=len(units),
        actual_units=methods['actual_units'],labels_confirmed=config.labels_confirmed,condition_count=len({u['condition'] for u in units}),
        inference_status=methods['inference_status'],inference_reason=methods['inference_reason'],result_member_key='composition_results',
        warnings=preview.warnings),methods=methods,inference_scope='sample_exploratory' if config.mode=='descriptive' else 'donor_inference',
        provenance={'sources':[{k:s[k] for k in ('source_kind','source_id','sha256')} for s in payload['sources']]})


def _plot(data,writer,label_names):
    from matplotlib import pyplot as plt
    units=data['units'];fig,ax=plt.subplots(figsize=(max(7,min(14,len(units)*.5)),5))
    bottom=[0.]*len(units)
    for category,label in data['categories']:
        values=[next(r['proportion'] for r in data['counts'] if r['unit_id']==u['unit_id'] and (r['category'],r['label_id'])==(category,label)) for u in units]
        ax.bar(range(len(units)),values,bottom=bottom,label=label_names.get(label,label) if label else category)
        bottom=[a+b for a,b in zip(bottom,values)]
    ax.set_xticks(range(len(units)),[str(u['donor'] or 'unmapped')+' / '+u['condition'] for u in units],rotation=60,ha='right')
    from pathlib import Path
    from matplotlib.font_manager import FontProperties
    font_path=Path('/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc')
    legend_font=FontProperties(fname=str(font_path),size=8) if font_path.is_file() else FontProperties(size=8)
    ax.set_ylim(0,1);ax.set_ylabel('Proportion of all retained cells');ax.legend(loc='upper left',bbox_to_anchor=(1,1),prop=legend_font)
    fig.tight_layout();stream=io.BytesIO();fig.savefig(stream,format='png',dpi=140);plt.close(fig)
    writer.add('composition_plot',stream.getvalue(),'png','figure')


def validate_composition_result(result,items,payload):
    """Parent verifies stored count arithmetic and method/scope claims independently."""
    import csv,json,math
    from pathlib import Path
    config=SingleCellCompositionConfig.model_validate(payload['config'])
    data=composition_data(config,payload['sources'])
    def table(key):
        if key not in items or items[key]['format']!='tsv':raise ValueError('composition_member_missing:'+key)
        with Path(items[key]['path']).open(encoding='utf8',newline='') as stream:return list(csv.DictReader(stream,delimiter='\t'))
    def doc(key):
        if key not in items or items[key]['format']!='json':raise ValueError('composition_member_missing:'+key)
        return json.loads(Path(items[key]['path']).read_bytes())
    def wire(value):
        if value is None:return ''
        if isinstance(value,(list,dict)):return json.dumps(value,ensure_ascii=False)
        return str(value)
    for key,expected in [('composition_counts',data['counts']),('composition_units',data['units']),('composition_assignments',data['assignments'])]:
        actual=table(key)
        if actual!=[{k:wire(v) for k,v in row.items()} for row in expected]:raise ValueError('composition_saved_counts_mismatch:'+key)
    preview=validate_composition_design(config,payload['sources'])
    if not preview.executable or doc('composition_design')!=preview.model_dump(mode='json'):raise ValueError('composition_design_mismatch')
    methods=doc('composition_methods')
    if any(result['methods'].get(k)!=v for k,v in methods.items()):raise ValueError('composition_methods_mismatch')
    if methods.get('config')!=config.model_dump(mode='json') or methods.get('actual_units')!=[u.model_dump() for u in preview.actual_units]:raise ValueError('composition_frozen_design_mismatch')
    if methods.get('denominator')!='all_retained_cells_in_selected_conditions':raise ValueError('composition_denominator_invalid')
    results=table('composition_results')
    if len(results)!=len(data['categories']):raise ValueError('composition_results_axis_invalid')
    for r,(category,label) in zip(results,data['categories']):
        if r['category']!=category or r['label_id']!=(label or '') or r['numerator']!=config.numerator or r['denominator']!=config.denominator:raise ValueError('composition_result_identity_invalid')
        means=[]
        for condition in (config.denominator,config.numerator):
            values=[row['proportion'] for row in data['counts'] if row['condition']==condition and (row['category'],row['label_id'])==(category,label)]
            means.append(sum(values)/len(values) if values else None)
        if config.mode=='descriptive' and config.numerator==config.denominator:means[1]=None
        for key,value in [('mean_proportion_denominator',means[0]),('mean_proportion_numerator',means[1]),('proportion_difference',means[1]-means[0] if None not in means else None)]:
            if value is None:
                if r[key]:raise ValueError('composition_result_mean_mismatch')
            elif not math.isclose(float(r[key]),value,rel_tol=1e-10,abs_tol=1e-12):raise ValueError('composition_result_mean_mismatch')
        if config.mode=='descriptive' and config.numerator==config.denominator:
            if r.get('proportion_ratio') or r.get('proportion_difference') or r.get('reason')!='single_condition_description':raise ValueError('composition_single_condition_effect_invalid')
        for key in ('p_value','p_adjust'):
            if r.get(key) and not 0<=float(r[key])<=1:raise ValueError('composition_pvalue_invalid')
        if config.mode=='descriptive' and (r.get('p_value') or r.get('p_adjust') or r.get('t_statistic') or r['inference_status']!='not_requested'):raise ValueError('composition_descriptive_inference_invalid')
    if config.mode=='descriptive':
        if methods.get('name')!='single_cell_composition_descriptive' or methods.get('inference_status')!='not_requested':raise ValueError('composition_method_invalid')
    else:
        native=doc('propeller_native')
        if methods.get('name')!='speckle_propeller' or native.get('status') not in ('ok','completed','not_computable'):raise ValueError('composition_method_invalid')
        expected_labels=[label if category=='label' else '__status_'+category for category,label in data['categories']]
        if native.get('sample_ids')!=[u['unit_id'] for u in data['units']] or native.get('label_ids')!=expected_labels:raise ValueError('propeller_axis_mismatch')
        native_rows=native.get('rows',[])
        if native.get('status')=='not_computable' and not native_rows:
            if any(r.get('p_value') or r.get('p_adjust') for r in results):raise ValueError('propeller_not_computable_has_pvalues')
        elif len(native_rows)!=len(results):raise ValueError('propeller_results_missing')
        for row,native_row,label in zip(results,native_rows,expected_labels):
            if native_row.get('label_id')!=label:raise ValueError('propeller_results_axis_invalid')
            for key in ('p_value','p_adjust','t_statistic'):
                expected=native_row.get(key)
                if (not row.get(key))!=(expected is None) or expected is not None and not math.isclose(float(row[key]),expected,rel_tol=1e-10,abs_tol=1e-12):raise ValueError('propeller_saved_result_mismatch')
    summary=result['summary']
    for key,value in [('total_cells',len(data['assignments'])),('unit_count',len(data['units'])),('row_count',len(results)),('actual_units',[u.model_dump() for u in preview.actual_units])]:
        if summary.get(key)!=value:raise ValueError('composition_summary_mismatch:'+key)
    if 'composition_plot' not in items or items['composition_plot']['format']!='png':raise ValueError('composition_plot_missing')
