"""Fixed matrix/network/flow figures; statuses are categories, never scores."""
from app.domain.bio_insights.evidence_graph import evidence_plot_data

def draw_evidence(fig,ax,source,config,zh):
    data=evidence_plot_data(source,config);selected=set(data['display_candidates'])
    colors={'support':'#2563eb','conflict':'#dc2626','missing':'#d1d5db','context':'#f59e0b','unknown':'#9ca3af','not_applicable':'#8b5cf6','not_significant':'#10b981'}
    labels={'support':'同条件原文支持','conflict':'原文方向冲突','missing':'对象未提及','context':'条件背景','unknown':'未知','not_applicable':'不适用','not_significant':'未显著'}
    if config.figure_type=='evidence_matrix':
        rows=[r for r in data['matrix'] if r['feature_id'] in selected];xs=list(dict.fromkeys(r['source_id'] for r in rows));ys=data['display_candidates']
        for r in rows:
            x=xs.index(r['source_id']);y=ys.index(r['feature_id']);ax.scatter(x,y,c=colors[r['status']],s=260,marker='s');ax.text(x,y+.16,labels[r['status']] if zh else r['status'],ha='center',fontsize=7)
        ax.set_xticks(range(len(xs)),[next(n['label'] for n in data['nodes'] if n['id']=='evidence:'+sid) for sid in xs],rotation=25,ha='right',fontsize=7);ax.set_yticks(range(len(ys)),ys);ax.set_ylim(-.6,max(len(ys)-.4,.6));ax.set_xlim(-.6,max(len(xs)-.4,.6))
    else:
        # Fixed three-column layout makes actual dependency flow explicit; no random claims.
        columns=([['original_file','processed_source','integration_result'],['external_evidence','candidate'],['matrix_operation']] if config.figure_type=='evidence_flow' else [['dependency_group'],['external_evidence'],['candidate']]);positions={}
        for x,kinds in enumerate(columns):
            nodes=[n for n in data['display_nodes'] if n['kind'] in kinds and (n['kind']!='candidate' or n['label'] in selected)]
            for y,n in enumerate(nodes):positions[n['id']]=(x,-y)
        for edge in data['display_edges']:
            if edge['source'] not in positions or edge['target'] not in positions:continue
            x,y=positions[edge['source']];u,v=positions[edge['target']];ax.plot([x,u],[y,v],color=colors.get(edge['relation'],'#94a3b8'),alpha=.65,lw=1)
        for node in data['display_nodes']:
            if node['id'] not in positions:continue
            x,y=positions[node['id']];ax.scatter(x,y,s=140,color='#2563eb' if node['kind']=='candidate' else '#64748b');label=node['label'] if node['kind']!='dependency_group' else ('依赖组 ' if zh else 'Dependency ')+node['label'][:6];ax.text(x,y+.16,label,ha='center',fontsize=7,wrap=True)
        ax.set_xlim(-.6,2.6);ax.set_ylim(min((p[1] for p in positions.values()),default=0)-.5,.6);ax.axis('off')
    fig.text(.01,.01,'原文背景 ≠ 系统重算 ≠ 独立验证；未知不按零处理' if zh else 'Source context is not recomputation or independent validation; unknown is not zero',fontsize=7)
    return data,not bool(data['matrix'])
