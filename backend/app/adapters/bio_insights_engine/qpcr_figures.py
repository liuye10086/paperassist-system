"""View frozen biological qPCR quantities; never refit the comparison."""
from collections import defaultdict
import math
from .figure_data import rows

def qpcr_plot_data(source,config):
    plan=source['metadata'].get('plan_config',{})
    if plan.get('schema_version')!=3 or plan.get('recipe')!='qpcr_relative_quantification_v1':raise ValueError('qpcr_figure_requires_qpcr_result')
    points=[]
    available=rows(source,'qpcr_plot_data')
    strata={r['stratum'] for r in available if r['feature_id']==config.feature_ids[0] and r['contrast_id']==config.contrast_id}
    if config.figure_stratum is None and len(strata)>1:raise ValueError('qpcr_select_one_plate_stratum')
    selected=config.figure_stratum or next(iter(strata),None)
    if selected is not None and strata and selected not in strata:raise ValueError('qpcr_figure_stratum_missing')
    for row in available:
        if row['feature_id']!=config.feature_ids[0] or row['contrast_id']!=config.contrast_id or row['stratum']!=selected:continue
        quantity=float(row['relative_quantity'])
        if not math.isfinite(quantity) or quantity<=0:raise ValueError('qpcr_plot_quantity_invalid')
        points.append(dict(row_key=row['row_key'],sample_id=row['sample_id'],biological_unit_id=row['biological_unit_id'],pair_id=row['pair_id'] or None,
            plate_id=row.get('plate_id'),condition=row['condition'],x=int(row['group_index']),relative_quantity=quantity,log2_quantity=float(row['log2_quantity'])))
    pairs=[]
    if plan.get('design')=='paired':
        mapping=defaultdict(dict)
        for point in points:
            if point['x'] in mapping[point['pair_id']]:raise ValueError('qpcr_plot_duplicate_pair')
            mapping[point['pair_id']][point['x']]=point
        pairs=[dict(pair_id=pair,left=group[0]['row_key'],right=group[1]['row_key']) for pair,group in sorted(mapping.items()) if set(group)=={0,1}]
    return dict(actual_figure_type='qpcr_samples',feature_id=config.feature_ids[0],contrast_id=config.contrast_id,stratum=selected,points=points,pairs=pairs,
        measurement_unit='fold',display_scale='log2 axis',error_type='none; biological sample points',analysis_recomputed=False,
        cross_plate=plan['cross_plate'],paired_plate_policy=plan.get('paired_plate_policy','separate'),calibration_scope='plate-local' if plan['cross_plate']=='separate' else 'confirmed comparable plates')

def draw_qpcr(fig,ax,source,config,zh):
    data=qpcr_plot_data(source,config);points=data['points'];by_key={r['row_key']:r for r in points}
    for pair in data['pairs']:
        left,right=by_key[pair['left']],by_key[pair['right']]
        ax.plot([0,1],[left['relative_quantity'],right['relative_quantity']],color='#94a3b8',lw=.8,zorder=1)
    for side in (0,1):
        selected=[p for p in points if p['x']==side]
        if selected:ax.scatter([side]*len(selected),[p['relative_quantity'] for p in selected],s=28,color=config.palette[side%len(config.palette)],zorder=2)
    contrast=next((c for c in source['metadata']['plan_config']['contrasts'] if c['contrast_id']==config.contrast_id),None)
    if contrast is None:raise ValueError('qpcr_figure_contrast_missing')
    ax.set_xticks([0,1],[contrast['numerator'],contrast['denominator']]);ax.set_yscale('log',base=2)
    ax.set_ylabel('相对数量（倍数；log2坐标）' if zh else 'Relative quantity (fold; log2 axis)')
    ax.set_xlabel('生物学样本；连线为完整配对' if zh else 'Biological samples; lines indicate complete pairs')
    if not points:ax.text(.5,.5,'无可计算样本' if zh else 'No computable samples',transform=ax.transAxes,ha='center')
    return data,not points
