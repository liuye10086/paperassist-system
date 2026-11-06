"""Parent-side checks of saved topic axes, finite values and stated method."""
import csv,json,math
from pathlib import Path
from app.domain.bio_insights.single_cell_topic_contracts import SingleCellTopicConfig
from app.domain.bio_insights.single_cell_topics import topic_selection


def validate_topic_result(result,items,payload):
    config=SingleCellTopicConfig.model_validate(payload['config'])
    expected=topic_selection(config,payload['sources'])
    def table(key):
        if key not in items or items[key]['format']!='tsv':raise ValueError('topic_required_member:'+key)
        with Path(items[key]['path']).open(encoding='utf-8',newline='') as stream:return list(csv.DictReader(stream,delimiter='\t'))
    def doc(key):
        if key not in items or items[key]['format']!='json':raise ValueError('topic_required_member:'+key)
        return json.loads(Path(items[key]['path']).read_bytes())
    methods=result['methods'];summary=result['summary']
    if methods.get('config')!=config.model_dump(mode='json') or methods.get('name')!=config.method:raise ValueError('topic_method_mismatch')
    if doc('topic_methods')!={k:v for k,v in methods.items() if k not in ('data_driven_grouping','upstream_inference_scopes')}:raise ValueError('topic_saved_method_mismatch')
    if summary.get('topic_method')!=config.method or summary.get('selected_cells')!=len(expected['selected']):raise ValueError('topic_selection_count_mismatch')
    selected=table('topic_selection')
    def wire(v):return '' if v is None else json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else str(v)
    fields=['barcode','cluster','label_id','annotation_status','donor','condition','sample','batch','selected','exclusion_reason','unit_id']
    if selected!=[{k:wire(row.get(k)) for k in fields} for row in expected['all_cells']]:raise ValueError('topic_saved_selection_mismatch')
    if 'topic_plot' not in items or items['topic_plot']['format']!='png':raise ValueError('topic_plot_missing')
    plot=doc('topic_plot_data')
    if plot.get('method')!=config.method:raise ValueError('topic_plot_method_mismatch')
    rows=table(summary['result_member_key'])
    if len(rows)!=summary.get('row_count'):raise ValueError('topic_row_count_mismatch')
    def finite(v,minimum=None,maximum=None):
        x=float(v)
        if not math.isfinite(x) or minimum is not None and x<minimum or maximum is not None and x>maximum:raise ValueError('topic_nonfinite_or_out_of_range')
        return x
    cells={r['barcode'] for r in expected['selected']}
    if config.method=='slingshot':
        if {r['barcode'] for r in rows}-cells:raise ValueError('trajectory_output_cell_mismatch')
        lineages={r['lineage_id'] for r in rows}
        if len(lineages)!=summary['lineage_count'] or len(rows)!=len(cells)*len(lineages):raise ValueError('trajectory_output_axis_mismatch')
        if len({(r['barcode'],r['lineage_id']) for r in rows})!=len(rows):raise ValueError('trajectory_duplicate_cell_lineage')
        for r in rows:
            finite(r['weight'],0,1)
            if r['pseudotime']:finite(r['pseudotime'])
    elif config.method=='genie3':
        edges={(r['regulator'],r['target']) for r in rows}
        if edges!={(a,b) for a in config.tf_ids for b in config.gene_ids if a!=b} or len(edges)!=len(rows):raise ValueError('regulation_output_axis_mismatch')
        for r in rows:
            a,b=finite(r['weight'],0),finite(r['stability_weight'],0)
            if not math.isclose(finite(r['absolute_weight_difference'],0),abs(a-b),rel_tol=1e-10,abs_tol=1e-12):raise ValueError('regulation_stability_mismatch')
        if doc('regulation_stability')!=summary['stability']:raise ValueError('regulation_saved_stability_mismatch')
    else:
        resource=doc('communication_resource')
        allowed=set(config.lr_ids) or {r['interaction_id'] for r in resource['interactions']}
        units={r['unit_id'] for r in expected['units']}
        keys={(r['unit_id'],r['sender'],r['receiver'],r['interaction_id']) for r in rows}
        if keys!={(u,a,b,lr) for u in units for a in config.label_ids for b in config.label_ids for lr in allowed} or len(keys)!=len(rows):raise ValueError('communication_output_axis_mismatch')
        for r in rows:
            if r['status']=='computed':finite(r['probability'],0,1);finite(r['cell_permutation_p_value'],0,1)
            elif r['probability'] or r['cell_permutation_p_value']:raise ValueError('communication_uncomputed_values')
        comparisons=table('communication_comparisons')
        if config.communication_mode=='per_donor' and comparisons:raise ValueError('communication_unrequested_comparison')
        for r in comparisons:
            if r['donor_p_value']:
                finite(r['donor_p_value'],0,1);finite(r['donor_q_value'],0,1)
                if min(int(r['n_denominator']),int(r['n_numerator']))<3:raise ValueError('communication_insufficient_donor_inference')
