"""Draw the pure frozen graph display projection."""
from app.domain.bio_insights.integration_graph import integration_plot_data

def draw_integration(fig,ax,source,config,zh):
    data=integration_plot_data(source,config);positions={n['node_id']:(n['x'],n['y']) for n in data['display_nodes']};ids=set(data['display_edge_ids'])
    for e in data['edges']:
        if e['edge_id'] not in ids:continue
        a,b=positions[e['source_node_id']],positions[e['target_node_id']]
        color=config.palette[-1] if e['edge_type']=='correlation' and (e['weight'] or 0)<0 else '#94a3b8'
        if config.figure_type=='integration_flow' and e['directed']:ax.annotate('',xy=b,xytext=a,arrowprops={'arrowstyle':'->','color':color,'lw':1})
        else:ax.plot([a[0],b[0]],[a[1],b[1]],color=color,linewidth=1,alpha=.7)
    for n in data['display_nodes']:
        ax.scatter(n['x'],n['y'],s=28,color=config.palette[0]);label=n['label'] if n['node_type'] not in ('source','canonical_lineage') else n['node_type']+':'+n['label'][:8]
        ax.annotate(label,(n['x'],n['y']),xytext=(4,4),textcoords='offset points',fontsize=7)
    ax.margins(.25);ax.set_axis_off()
    if not positions:ax.text(.5,.5,'无可显示关系' if zh else 'No display relationships',ha='center')
    return data,not bool(positions)
