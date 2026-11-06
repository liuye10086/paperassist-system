"""Display saved topic numbers without importing any scientific bridge."""
from collections import defaultdict
import copy
import numpy as np
from .inputs import document


def draw_topic(fig,ax,source,config,zh):
    method=config.figure_type.removeprefix('topic_')
    plan=source['metadata'].get('plan_config',{})
    if source['metadata'].get('kind')!='integration' or plan.get('schema_version')!=2 or plan.get('method')!=method:
        raise ValueError('topic_figure_source_mismatch')
    data=document(source['members']['topic_plot_data'])
    if data.get('method')!=method:raise ValueError('topic_figure_source_mismatch')
    local=lambda chinese,english:chinese if zh else english
    if method=='slingshot':
        coords=np.asarray(data['coordinates']);clusters=np.asarray(data['clusters'])
        for i,group in enumerate(sorted(set(clusters))):
            take=clusters==group;ax.scatter(coords[take,0],coords[take,1],s=7,alpha=.6,label=str(group),color=config.palette[i%len(config.palette)])
        for name,curve in zip(data['lineage_ids'],data['curves']):
            curve=np.asarray(curve);ax.plot(curve[:,0],curve[:,1],linewidth=2,label=name)
        ax.set(xlabel=data['representation']+local(' 维度1',' dimension 1'),ylabel=data['representation']+local(' 维度2',' dimension 2'))
        ax.legend(bbox_to_anchor=(1,1),fontsize=7)
        empty=len(coords)==0
    elif method=='genie3':
        rows=list(reversed(data['rows'][:config.top_n]));labels=[(r.get('regulator_symbol') or r['regulator'])+' → '+(r.get('target_symbol') or r['target']) for r in rows]
        y=np.arange(len(rows));ax.barh(y-.18,[r['weight'] for r in rows],height=.35,label=local('主随机种子','Primary seed'),color=config.palette[0]);ax.barh(y+.18,[r['stability_weight'] for r in rows],height=.35,label=local('第二随机种子','Second seed'),color=config.palette[1%len(config.palette)])
        ax.set_yticks(y,labels,fontsize=7);ax.set_xlabel(local('GENIE3预测重要性（不是P值）','GENIE3 predictive importance (not P)'));ax.legend(fontsize=8)
        empty=not rows
    else:
        labels=data['labels'];matrix=np.full((len(labels),len(labels)),np.nan)
        for i,sender in enumerate(labels):
            for j,receiver in enumerate(labels):
                by_unit=defaultdict(list)
                for row in data['rows']:
                    if row['sender']==sender and row['receiver']==receiver and row['probability'] is not None:
                        value=float(row['probability'])
                        if not np.isfinite(value) or value<0:raise ValueError('topic_probability_invalid')
                        by_unit[row['unit_id']].append(value)
                if by_unit:matrix[i,j]=np.mean([sum(values) for values in by_unit.values()])
        finite=matrix[np.isfinite(matrix)];maximum=float(finite.max()) if len(finite) else 0.
        # Explicit positive upper limit prevents matplotlib expanding an all-zero scale below zero.
        im=ax.imshow(np.ma.masked_invalid(matrix),cmap='viridis',vmin=0,vmax=maximum if maximum>0 else 1.)
        fig.colorbar(im,ax=ax,label=local('每单位LR概率之和的均值','Mean per-unit sum of modeled LR probabilities'))
        names=[data['label_names'].get(v,v) for v in labels];ax.set_xticks(range(len(labels)),names,rotation=35,ha='right');ax.set_yticks(range(len(labels)),names)
        ax.set(xlabel=local('接收群','Receiver'),ylabel=local('发送群','Sender'))
        for i in range(len(labels)):
            for j in range(len(labels)):
                value=matrix[i,j];valid=np.isfinite(value)
                rgb=im.cmap(im.norm(value))[:3] if valid else (1,1,1)
                linear=[c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4 for c in rgb]
                luminance=sum(c*w for c,w in zip(linear,(.2126,.7152,.0722)))
                ax.text(j,i,f'{value:.3g}' if valid else 'NA',ha='center',va='center',fontsize=8,color='black' if luminance>.179 else 'white')
        empty=not len(finite)
    result=copy.deepcopy(data)
    result.update(source_id=source['source_id'],source_sha256=source['sha256'],analysis_recomputed=False,raw_values_unchanged=True)
    return result,empty
