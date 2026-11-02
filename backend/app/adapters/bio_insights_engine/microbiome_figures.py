"""Immutable microbiome composition, alpha sample and PCoA views."""
import json
from collections import defaultdict
from .figure_data import rows

def draw_microbiome(fig,ax,source,config,zh):
    plan=source['metadata'].get('plan_config',{})
    if plan.get('schema_version')!=4:raise ValueError('microbiome_figure_requires_result')
    kind=config.figure_type;data=[]
    if kind=='microbiome_composition':
        data=rows(source,'microbiome_composition');samples=list(dict.fromkeys(r['sample_id'] for r in data));paths=list(dict.fromkeys(r['taxon_path'] for r in data));bottom=[0.]*len(samples)
        by={(r['sample_id'],r['taxon_path']):float(r['relative_abundance']) for r in data}
        for j,path in enumerate(paths):
            values=[by.get((s,path),0.) for s in samples];label=next(r['taxon_label'] for r in data if r['taxon_path']==path)
            ax.bar(range(len(samples)),values,bottom=bottom,color=config.palette[j%len(config.palette)],label=label);bottom=[a+b for a,b in zip(bottom,values)]
        ax.set_ylim(0,1);ax.set_ylabel('相对丰度' if zh else 'Relative abundance');ax.set_xlabel('样本' if zh else 'Sample')
        if len(samples)<=30:ax.set_xticks(range(len(samples)),samples,rotation=90,fontsize=6)
        else:ax.set_xticks([])
        ax.legend(fontsize=6,loc='upper left',bbox_to_anchor=(1,1))
    elif kind=='microbiome_alpha':
        metric=config.feature_ids[0] if config.feature_ids else 'shannon'
        if metric not in ('shannon','simpson','observed_features'):raise ValueError('microbiome_alpha_metric_invalid')
        data=rows(source,'microbiome_alpha');audit=rows(source,'microbiome_input_audit');meta={r['sample_id']:json.loads(r['metadata']) for r in audit};group=plan.get('group_column');groups=list(dict.fromkeys(meta[r['sample_id']].get(group,'所有样本') if group else '所有样本' for r in data))
        for i,g in enumerate(groups):
            selected=[r for r in data if (meta[r['sample_id']].get(group,'所有样本') if group else '所有样本')==g];ax.scatter([i]*len(selected),[float(r[metric]) for r in selected],s=20,color=config.palette[i%len(config.palette)])
        if plan.get('design')=='paired' and plan.get('pair_column') and len(groups)==2:
            pairs=defaultdict(dict)
            for r in data:pairs[meta[r['sample_id']].get(plan['pair_column'])][meta[r['sample_id']].get(group)]=r
            for pair,record in pairs.items():
                if pair and set(record)==set(groups):ax.plot([0,1],[float(record[g][metric]) for g in groups],c='#94a3b8',lw=.7,zorder=0)
        ax.set_xticks(range(len(groups)),groups);ax.set_ylabel(metric);ax.set_xlabel('样本；每点为一份样本' if zh else 'Sample; one point per sample')
    else:
        data=rows(source,'microbiome_pcoa');eigen=rows(source,'microbiome_eigenvalues');positive=[r for r in eigen if r['positive_coordinate_axis']=='True'];ys=[float(r.get('PCoA2') or 0) for r in data]
        ax.scatter([float(r.get('PCoA1') or 0) for r in data],ys,s=22,color=config.palette[0])
        ax.set_xlabel('PCoA1'+(' ('+format(float(positive[0]['explained_positive_ratio']),'.1%')+')' if positive else ' (0%)'))
        ax.set_ylabel('PCoA2'+(' ('+format(float(positive[1]['explained_positive_ratio']),'.1%')+')' if len(positive)>1 else ' (0%)'))
        if any(r['negative_warning']=='True' for r in eigen):ax.set_title('负特征值：仅显示正轴' if zh else 'Negative eigenvalues: positive axes only',fontsize=9)
    return dict(actual_figure_type=kind,rows=data,analysis_recomputed=False,source_recipe=plan['recipe']),not data
