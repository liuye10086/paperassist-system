"""Feature views use frozen extraction values, never reparse source structures."""
from .inputs import document


def feature_plot_data(source,config):
    if source['metadata'].get('kind')!='feature_extract':raise ValueError('feature_result_required')
    data=document(source['members']['feature_data']);fields=set(data['fields'])
    if config.x_column not in fields or config.figure_type=='feature_scatter' and config.y_column not in fields:raise ValueError('unknown_feature_plot_axis')
    rows=[]
    for r in data['rows']:
        x=r.get(config.x_column);y=r.get(config.y_column) if config.figure_type=='feature_scatter' else None
        rows.append(dict(feature_id=r['feature_id'],original_id=r['original_id'],resource_version_id=r['resource_version_id'],row_key=r['row_key'],selected=r['selected'],x=x,y=y,
            displayed=x is not None and (config.figure_type!='feature_scatter' or y is not None)))
    return dict(rows=rows,x_field=config.x_column,y_field=config.y_column if config.figure_type=='feature_scatter' else None,
        x_unit='Angstrom' if config.x_column.startswith('centroid_') or config.x_column=='radius_of_gyration' else '',
        y_unit='Angstrom' if config.y_column and (config.y_column.startswith('centroid_') or config.y_column=='radius_of_gyration') else '',
        missing_policy='retain all rows; do not plot missing axis values',analysis_recomputed=False)


def draw_feature(fig,ax,source,config,zh):
    data=feature_plot_data(source,config);rows=[r for r in data['rows'] if r['displayed']]
    if not rows:
        ax.text(.5,.5,'没有有效特征值' if zh else 'No valid feature values',ha='center',va='center',transform=ax.transAxes)
    elif config.figure_type=='feature_distribution':
        ax.hist([r['x'] for r in rows],bins=min(20,max(1,len(rows))),color=config.palette[0]);ax.set_ylabel('对象数' if zh else 'Object count')
    else:
        for selected,color,label in [(True,config.palette[0],'保留' if zh else 'Retained'),(False,config.palette[-1],'排除' if zh else 'Filtered')]:
            values=[r for r in rows if r['selected']==selected]
            if values:ax.scatter([r['x'] for r in values],[r['y'] for r in values],c=color,label=label,s=20,alpha=.8)
        ax.legend();ax.set_ylabel(config.y_column+(' (Angstrom)' if data['y_unit'] else ''))
    ax.set_xlabel(config.x_column+(' (Angstrom)' if data['x_unit'] else ''))
    return data,not rows
