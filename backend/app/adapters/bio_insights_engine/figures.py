"""Plots are views of immutable full results; rendering never refits a model."""
import io
import itertools
import math
import textwrap
from pathlib import Path
import numpy as np
from matplotlib import pyplot as plt
from matplotlib.colors import ListedColormap,BoundaryNorm
from matplotlib.font_manager import FontProperties
from matplotlib.patches import Circle,Patch
from matplotlib.ticker import MaxNLocator
from PIL import Image
from .inputs import document,iter_table,load_processed
from .evidence import numeric,source_numeric
from .figure_data import rows,contrast_rows,q_column as _q_column


number=numeric

def running_enrichment(values,hit_indices,weight,expected_es):
    ranking=np.asarray(values,dtype=float);hits=np.asarray(hit_indices,dtype=int)
    if (ranking.ndim!=1 or not np.isfinite(ranking).all() or not 0<len(hits)<len(ranking)
            or len(set(hits))!=len(hits) or np.any(hits<0) or np.any(hits>=len(ranking))):raise ValueError('invalid_gsea_curve_inputs')
    mass=np.abs(ranking[hits])**weight
    if not np.isfinite(mass).all() or mass.sum()<=0:raise ValueError('gsea_hit_weights_not_computable')
    increments=np.full(len(ranking),-1/(len(ranking)-len(hits)),dtype=float);increments[hits]=mass/mass.sum()
    result=np.cumsum(increments)
    observed=float(result.max() if abs(result.max())>abs(result.min()) else result.min())
    if not np.isclose(observed,expected_es,rtol=1e-6,atol=1e-8):raise ValueError('gsea_curve_es_mismatch')
    return result.tolist()


def intersections(sets):
    if not 2<=len(sets)<=8:raise ValueError('set_plot_count_limit')
    universe=set().union(*sets);result=[]
    for pattern in itertools.product((False,True),repeat=len(sets)):
        if not any(pattern):continue
        included=set.intersection(*(values for flag,values in zip(pattern,sets) if flag))
        excluded=set().union(*(values for flag,values in zip(pattern,sets) if not flag))
        exclusive=included-excluded
        result.append(dict(membership=list(pattern),inclusive_count=len(included),exclusive_count=len(exclusive),
                           inclusive_features=sorted(included),exclusive_features=sorted(exclusive)))
    return result


def _empty(ax,text):
    ax.text(.5,.5,text,ha='center',va='center',wrap=True,transform=ax.transAxes);ax.set_xticks([]);ax.set_yticks([])


def _volcano(fig,ax,source,config,zh):
    if source['metadata'].get('plan_config',{}).get('design')=='multiple':raise ValueError('omnibus_has_no_direction')
    data=contrast_rows(rows(source,'comparison_results'),config.contrast_id);qcol=_q_column(source,config);plot=[]
    for row in data:
        q=source_numeric(source,row.get(qcol));effect=source_numeric(source,row.get('effect_value'))
        if q is not None and not 0<=q<=1:raise ValueError('figure_invalid_q')
        plot.append(dict(row_key=row['row_key'],feature_id=row['feature_id'],effect_value=effect,q_value=q,
            display_neg_log10_q=-math.log10(max(q,1e-300)) if q is not None else None,
            displayed=effect is not None and q is not None))
    eligible=[r for r in plot if r['displayed']]
    plan=source['metadata'].get('plan_config',{})
    sample=plan.get('kind')=='comparison' and plan.get('schema_version')==2
    labels=['numerator higher','denominator higher','other']
    if sample and data:
        labels=[str(data[0][k])+('较高' if zh else ' higher') for k in ('numerator','denominator')]+['未同时满足阈值' if zh else 'Does not meet both thresholds']
        labels=[textwrap.fill(label,width=22 if index==2 else 32) for index,label in enumerate(labels)]
    for direction,color,label in [(1,config.palette[1%len(config.palette)],labels[0]),(-1,config.palette[0],labels[1]),(0,'#94a3b8',labels[2])]:
        subset=[r for r in eligible if (1 if r['q_value']<=.05 and r['effect_value']>=1 else -1 if r['q_value']<=.05 and r['effect_value']<=-1 else 0)==direction]
        if subset:ax.scatter([r['effect_value'] for r in subset],[r['display_neg_log10_q'] for r in subset],s=11,alpha=.7,c=color,label=label,rasterized=False)
    if not eligible:_empty(ax,'没有可绘制的效应与 q 值' if zh else 'No computable effect and q values')
    else:
        ax.axhline(-math.log10(.05),ls='--',lw=.7,c='#64748b')
        if sample:
            title=('着色条件：q <= 0.05\n且 |效应| >= 1\n（效应单位同横轴）' if zh else
                   'Color rule: q <= 0.05\nand |effect| >= 1\n(effect unit as\non x-axis)')
            ax.legend(fontsize=7,title=title,title_fontsize=7)
        else:ax.legend(fontsize=7)
    ax.set_xlabel(data[0].get('effect_unit') or 'effect' if data else 'effect');ax.set_ylabel('-log10('+qcol+')')
    if sample and data:
        row=next((r for r in data if r.get('effect_name') and r.get('effect_unit')),next((r for r in data if r.get('effect_name')),data[0]))
        effect=row.get('effect_name');numerator=row['numerator'];denominator=row['denominator']
        name={'mean_difference':('均值差','Mean difference'),'effect_log2fc':('log2倍数变化','log2 fold change'),
              'rank_biserial':('秩二列效应','Rank-biserial effect')}.get(effect,(str(effect),str(effect)) if effect else ('效应','Effect'))[0 if zh else 1]
        direction=(f'{numerator}/{denominator}' if effect=='effect_log2fc' else f'{numerator} - {denominator}' if effect=='mean_difference'
                   else f'{numerator} 相对于 {denominator}' if zh else f'{numerator} relative to {denominator}')
        label=textwrap.fill(name+' ('+direction+')',width=48)
        if row.get('effect_unit'):label+='\n'+textwrap.fill(row['effect_unit'],width=48)
        ax.set_xlabel(label)
    return dict(rows=plot,q_column=qcol,display_q_floor=1e-300,thresholds=dict(q=.05,absolute_effect=1),
                direction=dict(numerator=data[0].get('numerator'),denominator=data[0].get('denominator')) if data else {}),len(eligible)==0


def _place_small_sample_volcano_legend(fig,ax):
    """Place the expanded key after layout using real scatter/legend geometry."""
    legend=ax.get_legend()
    if legend is None or fig.get_figwidth()>=5:return
    fig.canvas.draw();box=legend.get_window_extent();bounds=ax.bbox
    if box.width+6>bounds.width or box.height+6>bounds.height:return
    points=np.concatenate([item.get_offset_transform().transform(item.get_offsets()) for item in ax.collections],axis=0)
    candidates=[]
    for y in np.linspace(bounds.y1-box.height/2-3,bounds.y0+box.height/2+3,5):
        for x in np.linspace(bounds.x1-box.width/2-3,bounds.x0+box.width/2+3,5):
            obscured=np.count_nonzero((np.abs(points[:,0]-x)<=box.width/2+3)&(np.abs(points[:,1]-y)<=box.height/2+3))
            candidates.append((obscured,x,y))
    _,x,y=min(candidates,key=lambda item:item[0])
    legend.set_loc('center')
    legend.set_bbox_to_anchor(ax.transAxes.inverted().transform((x,y)),transform=ax.transAxes)


def _heatmap(fig,ax,source,config,sources,zh):
    processed=sources[config.processed_source_id]
    for key in ('species_taxon_id','namespace','reference_version'):
        if source['metadata'].get(key)!=processed['metadata'].get(key):raise ValueError('heatmap_feature_identity_mismatch')
    key='candidate_results' if source['metadata'].get('kind')=='candidate' else 'comparison_results'
    result=contrast_rows(rows(source,key),config.contrast_id);qcol=_q_column(source,config)
    def ranking(row):
        value=source_numeric(source,row.get('primary_q') if key=='candidate_results' else row.get(qcol))
        return (value is None,value if value is not None else 0,row['feature_id'])
    result.sort(key=ranking)
    features=list(dict.fromkeys(r['feature_id'] for r in result))[:config.top_n]
    loaded=load_processed(processed,'spot_exploratory');feature_index={f:i for i,f in enumerate(loaded['feature_ids'])}
    selected=[f for f in features if f in feature_index];excluded=[f for f in features if f not in feature_index]
    observations={key:i for i,key in enumerate(loaded['retained_keys'])};matrix=[];plot=[]
    for group in config.expression_groups:
        keys=[(key.processed_version_id,key.barcode) for key in group.observation_keys]
        if len(set(keys))!=len(keys) or any(key not in observations for key in keys):raise ValueError('heatmap_observation_invalid')
        values=np.asarray(loaded['log1p'][[observations[k] for k in keys]][:,[feature_index[f] for f in selected]].mean(0)).ravel()
        matrix.append(values)
        plot.extend(dict(feature_id=f,group=group.label,mean_log1p=float(value),spot_count=len(keys)) for f,value in zip(selected,values))
    if not selected:_empty(ax,'所选表达矩阵中没有候选基因' if zh else 'No selected features in the expression matrix')
    else:
        image=ax.imshow(np.asarray(matrix).T,aspect='auto',interpolation='nearest',cmap='viridis')
        ax.set_xticks(range(len(config.expression_groups)),[g.label for g in config.expression_groups],rotation=45,ha='right')
        ax.set_yticks(range(len(selected)),selected,fontsize=7);fig.colorbar(image,ax=ax,label='Mean log1p normalized expression')
    return dict(rows=plot,excluded_feature_ids=excluded,aggregation='mean of actual retained-spot log1p layer; no row z-score'),not selected


def _enrichment(fig,ax,source,config,zh):
    data=contrast_rows(rows(source,'enrichment_results'),config.contrast_id)
    is_gsea=source['metadata'].get('kind')=='gsea_prerank';qcol='fdr_q_value' if is_gsea else 'q_value'
    valid=[r for r in data if number(r.get(qcol)) is not None]
    valid.sort(key=lambda r:(number(r[qcol]),r['row_key']));display=valid[:config.top_n]
    values=[number(r.get('nes') if is_gsea else r.get('gene_ratio')) for r in display]
    if not display or not any(v is not None for v in values):
        _empty(ax,'没有可计算的富集条目' if zh else 'No computable enrichment terms');empty=True
    else:
        selected=[(r,v) for r,v in zip(display,values) if v is not None];display=[r for r,_ in selected];values=[v for _,v in selected]
        labels=[r.get('term_name') or r['term_id'] for r in display];y=np.arange(len(values))
        if config.enrichment_style=='bar':ax.barh(y,values,color=config.palette[0])
        else:
            image=ax.scatter(values,y,c=[-math.log10(max(number(r[qcol]),1e-300)) for r in display],
                s=[max(15,min(200,math.sqrt(float(r.get('k') or r.get('set_size') or 1))*15)) for r in display],cmap='viridis')
            fig.colorbar(image,ax=ax,label='-log10('+qcol+')')
        ax.set_yticks(y,labels,fontsize=7);ax.invert_yaxis();ax.set_xlabel('NES' if is_gsea else 'GeneRatio (hits / foreground)');empty=False
        if all(number(r[qcol])>.05 for r in display):ax.set_title('q ≤ 0.05 无显著条目' if zh else 'No terms with q ≤ 0.05')
    return dict(rows=data,displayed_row_keys=[r['row_key'] for r in display],q_column=qcol,top_n=config.top_n,
        correction='GSEA joint-null FDR' if is_gsea else 'BH within frozen enrichment family',style=config.enrichment_style),empty


def _gsea(fig,ax,source,config,zh):
    curves=document(source['members']['gsea_curves'])
    term=next((t for t in curves['terms'] if t['row_key']==config.term_row_key),None)
    if not term or curves.get('rank_zero_based') is not True:raise ValueError('gsea_term_identity_missing')
    rank=rows(source,curves['rank_member_key']);values=[number(row['statistic']) for row in rank]
    if any(v is None for v in values):raise ValueError('gsea_rank_missing_value')
    res=running_enrichment(values,term['hit_indices'],term['weight'],term['es'])
    ax.plot(np.arange(len(res)),res,c=config.palette[0],lw=1.5);ax.axhline(0,c='#64748b',lw=.7)
    low=min(res);span=max(res)-low or 1
    ax.vlines(term['hit_indices'],low-span*.15,low-span*.07,linewidth=.5,color='#111827')
    ax.set_xlabel('Rank in the complete signed gene list');ax.set_ylabel('Running enrichment score')
    # Keep statistics outside the axes for both positive and negative peaks.
    fig.text(.5,.98,f"{term['term_id']}\nES={term['es']:.4g}; NES={term['nes']:.4g}\nGSEA FDR={term['fdr_q_value']:.4g}",
             ha='center',va='top',fontsize=8)
    if term['fdr_q_value']==0:
        note=('FDR=0 为经验置换估计，\n不表示假发现风险为零。' if zh else
              'FDR=0 is an empirical\npermutation estimate; it does not\nestablish zero false-discovery risk.')
        fig.text(.5,.02,note,ha='center',va='bottom',fontsize=7)
    return dict(term=term,ranking=rank,running_enrichment=res,es_reconciled=True),False


def _sets(fig,ax,config,sources,zh):
    sets=[];definitions=[];identity=None
    for selection in config.selected_sets:
        source=sources[selection.result_source_id];meta=source['metadata'];current=tuple(meta.get(k) for k in ('species_taxon_id','namespace','reference_version'))
        if any(value is None for value in current) or identity is not None and current!=identity:raise ValueError('set_plot_identity_mismatch')
        identity=current;data=contrast_rows(rows(source,'comparison_results'),selection.contrast_id);selected=set()
        for row in data:
            q=source_numeric(source,row.get(selection.q_column));effect=source_numeric(source,row.get('effect_value'))
            if q is None or effect is None or q>selection.q_threshold or abs(effect)<selection.minimum_absolute_effect:continue
            if selection.direction=='up' and effect<=0 or selection.direction=='down' and effect>=0:continue
            if row.get('tested','True').lower() not in ('true','1'):continue
            selected.add(row['feature_id'])
        sets.append(selected);definitions.append({**selection.model_dump(mode='json'),'feature_ids':sorted(selected)})
    counts=intersections(sets);actual='upset' if config.figure_type=='upset' or len(sets)>3 or config.intersection_mode!='exclusive' else 'venn'
    if actual=='venn':
        positions=[(-.45,0),(.45,0)] if len(sets)==2 else [(-.45,.25),(.45,.25),(0,-.5)]
        for i,(x,y) in enumerate(positions):
            ax.add_patch(Circle((x,y),.85,color=config.palette[i%len(config.palette)],alpha=.22));ax.text(x,y+.98 if i<2 else y-1.,config.selected_sets[i].label,ha='center',fontsize=8)
        coordinates={(True,False):(-.8,0),(False,True):(.8,0),(True,True):(0,0)} if len(sets)==2 else {
            (True,False,False):(-.8,.45),(False,True,False):(.8,.45),(False,False,True):(0,-.95),
            (True,True,False):(0,.55),(True,False,True):(-.45,-.35),(False,True,True):(.45,-.35),(True,True,True):(0,-.05)}
        for count in counts:
            x,y=coordinates[tuple(count['membership'])];ax.text(x,y,str(count['exclusive_count']),ha='center',va='center')
        ax.set_xlim(-1.5,1.5);ax.set_ylim(-1.7,1.6);ax.set_aspect('equal');ax.axis('off');display=counts
    else:
        field='inclusive_count' if config.intersection_mode=='all' else 'exclusive_count'
        display=[r for r in counts if r[field] and (config.intersection_mode!='at_least_k' or sum(r['membership'])>=config.intersection_k)]
        display.sort(key=lambda r:(-r[field],r['membership']));display=display[:config.top_n]
        if not display:_empty(ax,'交集为空' if zh else 'Empty intersections')
        else:
            ax.bar(range(len(display)),[r[field] for r in display],color=config.palette[0])
            label=('包容交集\n基因数' if field=='inclusive_count' else '互斥交集\n基因数') if zh else (
                'Inclusive\ngene count' if field=='inclusive_count' else 'Exclusive\ngene count')
            ax.set_ylabel(label,fontsize=8);ax.tick_params(axis='y',labelsize=7)
            ax.yaxis.set_major_locator(MaxNLocator(nbins=4,integer=True,prune='upper'))
            ax.set_xlim(-.5,len(display)-.5);ax.set_xticks([])
            inset=fig.add_axes([.2,.1,.75,.25],sharex=ax);inset.set_ylim(-.5,len(sets)-.5)
            for x,row in enumerate(display):
                active=[i for i,flag in enumerate(row['membership']) if flag]
                inset.scatter([x]*len(sets),range(len(sets)),c=['#111827' if flag else '#e2e8f0' for flag in row['membership']],s=18)
                inset.plot([x,x],[min(active),max(active)],c='#111827',lw=1)
            inset.set_yticks(range(len(sets)),[s.label for s in config.selected_sets],fontsize=7);inset.set_xticks([])
            inset.tick_params(axis='y',length=0)
            for spine in inset.spines.values():spine.set_visible(False)
    return dict(definitions=definitions,intersections=counts,displayed_memberships=[r['membership'] for r in display],actual_figure_type=actual,
        intersection_mode=config.intersection_mode,venn_region_numbers='exclusive; circle areas are schematic' if actual=='venn' else None),not set().union(*sets)


def _layout_upset(fig,ax,config,zh):
    """Measure complete labels in points; keep the requested physical canvas."""
    if len(fig.axes)<2:return
    matrix=fig.axes[1];renderer=fig.canvas.get_renderer();width,height=fig.bbox.size
    point=fig.dpi/72;pad=6*point

    def wrap(text,properties,maximum):
        # Only insert line breaks. Never shorten a source label or identifier.
        lines=[]
        for paragraph in text.split('\n'):
            line=''
            for character in paragraph:
                candidate=line+character
                if line and renderer.get_text_width_height_descent(candidate,properties,False)[0]>maximum:
                    boundary=line.rfind(' ')
                    if boundary>0:
                        lines.append(line[:boundary]);line=line[boundary+1:]+character
                    else:lines.append(line);line=character
                else:line=candidate
            lines.append(line)
        return '\n'.join(lines)

    title=fig.text(.5,1-pad/height,'',ha='center',va='top',fontsize=7 if width<300 else 10)
    title.set_text(wrap(ax.get_title(),title.get_fontproperties(),width-2*pad));ax.title.set_visible(False)
    explanation=('黑点：必须属于；浅点：不限定。\n交集可重叠。' if zh else
                 'Black: required; pale: unrestricted.\nIntersections may overlap.') if config.intersection_mode=='all' else (
                 '黑点：属于；浅点：排除集合。' if zh else 'Black: included; pale: excluded.')
    note=fig.text(.5,pad/height,'',ha='center',va='bottom',fontsize=7)
    note.set_text(wrap(explanation,note.get_fontproperties(),width-2*pad))
    labels=matrix.get_yticklabels()
    matrix.set_yticklabels([wrap(text.get_text(),text.get_fontproperties(),width*.38) for text in labels],fontsize=7)
    fig.canvas.draw();renderer=fig.canvas.get_renderer();labels=matrix.get_yticklabels()
    label_width=max(text.get_window_extent(renderer).width for text in labels)
    row_height=max(text.get_window_extent(renderer).height for text in labels)+4*point
    # Reserve enough space for both the matrix names and the count-axis label.
    left=max(label_width+4*point,ax.get_window_extent(renderer).x0-ax.get_tightbbox(renderer).x0)+pad
    matrix_height=max(len(labels)*row_height,height*.22)
    top=height-pad-title.get_window_extent(renderer).height-pad
    matrix_bottom=2*pad+note.get_window_extent(renderer).height
    bottom=matrix_bottom+matrix_height+2*pad
    bar_height=top-bottom;plot_width=width-left-pad
    if (plot_width<36*point or bar_height<max(36*point,ax.yaxis.label.get_window_extent(renderer).height+pad)
            or plot_width/len(ax.patches)<5*point):
        raise ValueError('figure_layout_too_small')
    ax.set_position([left/width,bottom/height,plot_width/width,bar_height/height])
    matrix.set_position([left/width,matrix_bottom/height,plot_width/width,matrix_height/height])
    # Re-evaluate the actual final artists, including count tick labels, before saving.
    fig.canvas.draw();renderer=fig.canvas.get_renderer()
    texts=[title,note,ax.yaxis.label,*ax.get_yticklabels(),*matrix.get_yticklabels()]
    bounds=[text.get_window_extent(renderer) for text in texts if text.get_visible() and text.get_text()]
    if (any(b.x0<0 or b.y0<0 or b.x1>width or b.y1>height for b in bounds)
            or any(first.overlaps(second) for i,first in enumerate(bounds) for second in bounds[i+1:])):
        raise ValueError('figure_layout_too_small')


def _candidate(fig,ax,source,config,zh):
    candidates=rows(source,'candidate_results')[:config.top_n];features=[r['feature_id'] for r in candidates]
    data=rows(source,'candidate_evidence');ids=sorted({r['source_id'] for r in data});by_key={(r['feature_id'],r['source_id']):r for r in data};values=[]
    for feature in features:
        row=[]
        for sid in ids:
            item=by_key.get((feature,sid));missing=not item or item['missing'].lower() in ('true','1')
            value=float('nan') if missing else 0 if item['supported'].lower() not in ('true','1') else number(item.get('direction'))
            row.append(2 if value is None else value)
        values.append(row)
    if not features:_empty(ax,'候选集合为空' if zh else 'Empty candidate set')
    else:
        cmap=ListedColormap(['#2563eb','#f1f5f9','#dc2626','#eab308']);cmap.set_bad('#94a3b8')
        ax.imshow(np.ma.masked_invalid(np.asarray(values)),cmap=cmap,norm=BoundaryNorm([-1.5,-.5,.5,1.5,2.5],4),aspect='auto')
        ax.set_xticks(range(len(ids)),ids,rotation=45,ha='right',fontsize=6);ax.set_yticks(range(len(features)),features,fontsize=7)
        ax.legend(handles=[Patch(color=c,label=l) for c,l in [('#dc2626','up'),('#2563eb','down'),('#f1f5f9','not supported'),('#eab308','direction unknown'),('#94a3b8','missing')]],loc='upper left',bbox_to_anchor=(1,1),fontsize=6)
    return dict(rows=[r for r in data if r['feature_id'] in features],selected_features=features,missing_is_not_zero=True),not features


def run_figure(payload,writer):
    from app.domain.bio_insights.contracts import FigureConfig
    config=FigureConfig.model_validate(payload['config']);sources={s['source_id']:s for s in payload['sources']};source=sources[config.result_source_id]
    axes_members={
        'integration_network':('layout_x','layout_y','integration_data'),
        'integration_flow':('lineage_stage','layout_y','integration_data'),
        'feature_distribution':(config.x_column,None,'feature_results'),
        'feature_scatter':(config.x_column,config.y_column,'feature_results'),
        'volcano':('effect_value',_q_column(source,config),'comparison_results'),
        'distribution':('group','value','comparison_results'),
        'qpcr_samples':('condition','relative_quantity','qpcr_plot_data'),
        'microbiome_composition':('sample','relative_abundance','microbiome_composition'),
        'microbiome_alpha':('sample','alpha_diversity','microbiome_alpha'),
        'microbiome_pcoa':('PCoA1','PCoA2','microbiome_pcoa'),
        'heatmap':('group','feature_id','candidate_results' if source['metadata'].get('kind')=='candidate' else 'comparison_results'),
        'enrichment':('nes' if source['metadata'].get('kind')=='gsea_prerank' else 'gene_ratio','term_name','enrichment_results'),
        'gsea':('rank','running_enrichment','gsea_curves'),
        'venn':('membership','gene_count','comparison_results'),'upset':('membership','gene_count','comparison_results'),
        'candidate_evidence':('source_id','feature_id','candidate_evidence'),'evidence_matrix':('source_id','feature_id','evidence_data'),'evidence_network':('source','target','evidence_data'),'evidence_flow':('source','target','evidence_data')}
    x,y,member_key=axes_members[config.figure_type]
    if any(actual is not None and actual!=expected for actual,expected in [(config.x_column,x),(config.y_column,y),(config.member_key,member_key)]):
        raise ValueError('figure_axis_contract_mismatch')
    width=round(config.width_inches*config.dpi);height=round(config.height_inches*config.dpi)
    if max(width,height)>4096 or width*height>16_000_000 or config.figure_type=='heatmap' and config.top_n>100:
        raise ValueError('figure_budget_exceeded')
    font=Path('/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc')
    if not font.is_file():raise RuntimeError('bio_insights_environment_unavailable')
    plt.rcParams.update({'font.family':FontProperties(fname=str(font)).get_name(),'axes.unicode_minus':False,'svg.fonttype':'path','pdf.fonttype':42})
    fig,ax=plt.subplots(figsize=(config.width_inches,config.height_inches));zh=config.output_language=='zh-CN'
    try:
        if config.figure_type=='distribution' or config.figure_type=='heatmap' and config.sample_groups:
            from .quantitative_figures import draw_sample_plot
            data,empty=draw_sample_plot(fig,ax,source,config,sources,zh)
        elif config.figure_type.startswith('evidence_'):
            from .evidence_figures import draw_evidence
            data,empty=draw_evidence(fig,ax,source,config,zh)
        elif config.figure_type.startswith('integration_'):
            from .integration_figures import draw_integration
            data,empty=draw_integration(fig,ax,source,config,zh)
        elif config.figure_type.startswith('feature_'):
            from .feature_figures import draw_feature
            data,empty=draw_feature(fig,ax,source,config,zh)
        elif config.figure_type.startswith('microbiome_'):
            from .microbiome_figures import draw_microbiome
            data,empty=draw_microbiome(fig,ax,source,config,zh)
        elif config.figure_type=='qpcr_samples':
            from .qpcr_figures import draw_qpcr
            data,empty=draw_qpcr(fig,ax,source,config,zh)
        elif config.figure_type=='volcano':data,empty=_volcano(fig,ax,source,config,zh)
        elif config.figure_type=='heatmap':data,empty=_heatmap(fig,ax,source,config,sources,zh)
        elif config.figure_type=='enrichment':data,empty=_enrichment(fig,ax,source,config,zh)
        elif config.figure_type=='gsea':data,empty=_gsea(fig,ax,source,config,zh)
        elif config.figure_type in ('venn','upset'):data,empty=_sets(fig,ax,config,sources,zh)
        else:data,empty=_candidate(fig,ax,source,config,zh)
        scope=source['metadata'].get('inference_scope','derived')
        upstream=set()
        for item in sources.values():
            meta=item.get('metadata',{});upstream.update(meta.get('upstream_inference_scopes',[]))
            if meta.get('inference_scope') in ('spot_exploratory','donor_inference','sample_exploratory','sample_inference','external_result'):upstream.add(meta['inference_scope'])
        driven=any(s.get('metadata',{}).get('data_driven_grouping') is True for s in sources.values())
        labels={'spot_exploratory':'空间探索' if zh else 'Spot exploratory','donor_inference':'供体层面比较' if zh else 'Donor comparison',
                'sample_exploratory':'样本探索' if zh else 'Sample exploratory','sample_inference':'样本比较' if zh else 'Sample comparison',
                'external_result':'外部结果' if zh else 'External result','derived':'派生分析' if zh else 'Derived analysis'}
        title=config.title or config.figure_type
        restrictions=' / '.join(labels.get(s,s) for s in sorted(upstream)) or labels.get(scope,scope)
        if driven:restrictions+='; '+('数据驱动分组' if zh else 'data-driven grouping')
        notice=ax.get_title() if config.figure_type=='enrichment' or config.figure_type=='microbiome_pcoa' else ''
        ax.set_title(title+'\n'+restrictions+('\n'+notice if notice else ''),fontsize=10)
        if config.figure_type=='gsea':fig.tight_layout(rect=(0,.16,1,.82))
        elif data.get('actual_figure_type')=='upset':_layout_upset(fig,ax,config,zh)
        else:fig.tight_layout()
        if config.figure_type=='volcano' and source['metadata'].get('plan_config',{}).get('kind')=='comparison' and source['metadata']['plan_config'].get('schema_version')==2:
            _place_small_sample_volcano_legend(fig,ax)
        for fmt in config.formats:
            if fmt=='tiff':
                buffer=io.BytesIO();fig.savefig(buffer,format='png',dpi=config.dpi)
                buffer.seek(0)
                with Image.open(buffer) as image:
                    target=io.BytesIO();image.convert('RGB').save(target,format='TIFF',compression='tiff_lzw',dpi=(config.dpi,config.dpi));content=target.getvalue()
            else:
                buffer=io.BytesIO();extra={'metadata':{'Date':None}} if fmt=='svg' else {}
                fig.savefig(buffer,format=fmt,dpi=config.dpi,**extra);content=buffer.getvalue()
            writer.add('figure_'+fmt,content,fmt,'figure')
        writer.json('plot_data',data)
        methods=dict(figure_type=config.figure_type,actual_figure_type=data.get('actual_figure_type',config.figure_type),
            config=config.model_dump(mode='json'),upstream_inference_scope=scope,upstream_provenance=source['metadata'].get('provenance'),
            upstream_inference_scopes=sorted(upstream),data_driven_grouping=driven,axes=dict(x=x,y=y),input_member=member_key,
            source_id=source['source_id'],source_sha256=source['sha256'],plot_data_key='plot_data',analysis_recomputed=False,
            zero_q_display_floor=1e-300 if config.figure_type in ('volcano','enrichment') else None,raw_values_unchanged=True,
            empty_result=bool(empty),caption_scope='Sample measurements preserve missingness and declared units; technical exploration is not biological inference or independent validation.' if upstream & {'sample_exploratory','sample_inference'} else 'Region enrichment does not establish pure cell identity, mechanism or independent validation.')
        writer.json('figure_metadata',methods)
        return dict(summary=dict(figure_type=config.figure_type,actual_figure_type=methods['actual_figure_type'],empty_result=bool(empty),formats=config.formats,
            output_language=config.output_language),methods=methods,inference_scope='visualization',provenance='system_computed')
    finally:plt.close(fig)
