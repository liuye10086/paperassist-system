"""Actual selected sample values and explicit missingness for quantitative plots."""
from types import SimpleNamespace
import numpy as np
from .quantitative_inputs import load_quantitative


def sample_plot_data(processed,config,features):
    data=load_quantitative(processed,SimpleNamespace(mode='continuous',analysis_layer=config.analysis_layer))
    index={key:i for i,key in enumerate(data['retained_keys'])};findex={f:i for i,f in enumerate(data['feature_ids'])}
    if not features or len(features)>100 or any(f not in findex for f in features):raise ValueError('sample_plot_feature_not_retained')
    rows=[];group_counts=[];selected=[];labels=[]
    for group in config.sample_groups:
        indices=[]
        for key in group.sample_keys:
            pair=(key.processed_version_id,key.sample_id)
            if pair not in index or pair in selected:raise ValueError('sample_plot_sample_not_retained_or_duplicate')
            selected.append(pair);labels.append(group.label);indices.append(index[pair])
        if not indices:raise ValueError('sample_plot_empty_group')
        for feature in features:
            j=findex[feature];missing=int(data['missing'][indices,j].sum())
            group_counts.append(dict(group=group.label,feature_id=feature,total_n=len(indices),measured_n=len(indices)-missing,missing_n=missing))
    if len(selected)*len(features)>1000000:raise ValueError('sample_plot_cell_limit')
    values=data['values'][[index[key] for key in selected]][:,[findex[f] for f in features]].astype(float).copy()
    mask=data['missing'][[index[key] for key in selected]][:,[findex[f] for f in features]]
    transform=[]
    if config.z_score:
        for j,feature in enumerate(features):
            valid=~mask[:,j];measured=values[valid,j]
            if len(measured)<2 or np.std(measured,ddof=1)==0:raise ValueError('sample_heatmap_zscore_not_computable:'+feature)
            mean=float(measured.mean());sd=float(np.std(measured,ddof=1));values[valid,j]=(measured-mean)/sd
            transform.append(dict(feature_id=feature,mean=mean,sample_sd=sd,n=len(measured)))
    for i,(source_id,sample) in enumerate(selected):
        for j,feature in enumerate(features):
            rows.append(dict(processed_version_id=source_id,sample_id=sample,group=labels[i],feature_id=feature,missing=bool(mask[i,j]),value=None if mask[i,j] else float(values[i,j])))
    return dict(rows=rows,groups=group_counts,feature_ids=features,sample_keys=[dict(processed_version_id=s,sample_id=k) for s,k in selected],
        layer=data['layer'],z_score=config.z_score,z_score_parameters=transform,selection='explicit samples; explicit features or frozen ranked top_n; no group averaging',
        source_id=processed['source_id'],source_sha256=processed['sha256'])


def selected_features(source,config):
    from .figure_data import rows,contrast_rows,q_column as _q_column
    from .evidence import source_numeric
    features=list(config.feature_ids)
    if not features:
        member='candidate_results' if source['metadata'].get('kind')=='candidate' else 'comparison_results'
        results=contrast_rows(rows(source,member),config.contrast_id);qcol='primary_q' if member=='candidate_results' else _q_column(source,config)
        results.sort(key=lambda r:(source_numeric(source,r.get(qcol)) is None,source_numeric(source,r.get(qcol)) or 0,r['feature_id']))
        features=list(dict.fromkeys(r['feature_id'] for r in results))[:config.top_n]
    return features


def validate_sample_plot(payload,actual):
    from app.domain.bio_insights.contracts import FigureConfig
    config=FigureConfig.model_validate(payload['config']);sources={s['source_id']:s for s in payload['sources']}
    expected=sample_plot_data(sources[config.processed_source_id],config,selected_features(sources[config.result_source_id],config))
    if actual!=expected:raise ValueError('sample_plot_data_mismatch')


def draw_sample_plot(fig,ax,source,config,sources,zh):
    features=selected_features(source,config)
    data=sample_plot_data(sources[config.processed_source_id],config,features)
    if config.figure_type=='distribution':
        for i,group in enumerate(config.sample_groups):
            selected=[r for r in data['rows'] if r['group']==group.label and r['value'] is not None];values=[r['value'] for r in selected]
            if values:
                ax.boxplot([values],positions=[i],widths=.5,showfliers=False)
                offsets=np.linspace(-.14,.14,len(values)) if len(values)>1 else [0]
                ax.scatter(i+np.asarray(offsets),values,s=16,alpha=.7,color=config.palette[i%len(config.palette)])
        counts={r['group']:r for r in data['groups']}
        missing_label='缺失' if zh else 'missing'
        ax.set_xticks(range(len(config.sample_groups)),[f"{g.label}\nn={counts[g.label]['measured_n']}, {missing_label}={counts[g.label]['missing_n']}" for g in config.sample_groups])
        ax.set_ylabel(data['layer']['unit']);ax.set_xlabel(features[0])
    else:
        values=np.array([np.nan if r['value'] is None else r['value'] for r in data['rows']]).reshape(len(data['sample_keys']),len(features)).T
        image=ax.imshow(np.ma.masked_invalid(values),aspect='auto',interpolation='nearest',cmap='viridis')
        ax.set_yticks(range(len(features)),features,fontsize=7)
        if len(data['sample_keys'])<=30:ax.set_xticks(range(len(data['sample_keys'])),[r['sample_id'] for r in data['sample_keys']],rotation=60,ha='right',fontsize=7)
        else:ax.set_xlabel('选定样本（完整顺序见 plot_data）' if zh else 'Selected samples (complete order in plot_data)')
        fig.colorbar(image,ax=ax,label=('逐特征 z-score（样本标准差）' if zh else 'Per-feature z-score (sample SD)') if config.z_score else data['layer']['unit'])
    return data,not any(r['value'] is not None for r in data['rows'])
