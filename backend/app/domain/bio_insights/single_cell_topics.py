"""Selection and donor units shared by preview, numerical child and validation."""
from collections import Counter,defaultdict
import hashlib
import json
from .single_cell_topic_contracts import SingleCellTopicConfig


def topic_selection(config,sources,observations=None):
    config=SingleCellTopicConfig.model_validate(config)
    processed=[s for s in sources if s['source_kind']=='bio_processed_dataset_version' and s['source_id']==config.processed_source_id]
    if len(processed)!=1 or processed[0]['metadata'].get('assay')!='single_cell':raise ValueError('single_cell_processed_required')
    meta=processed[0]['metadata'];clusters=meta.get('cell_clusters',{})
    annotations={};label_names={}
    if config.annotation_source_id:
        matches=[s for s in sources if s['source_kind']=='bio_annotation_version' and s['source_id']==config.annotation_source_id]
        if len(matches)!=1:raise ValueError('topic_annotation_required')
        am=matches[0]['metadata']
        if am.get('processed_dataset_version_id')!=config.processed_source_id:raise ValueError('annotation_processed_mismatch')
        label_names={r['id']:r.get('name') or r['id'] for r in am.get('labels',[])}
        if not set(config.label_ids)<=set(label_names):raise ValueError('annotation_label_unknown')
        rows=am.get('assignments',{}).get('rows',[])
        annotations={r['barcode']:r for r in rows}
        if len(annotations)!=len(rows):raise ValueError('annotation_cell_axis_invalid')
    selected=[];excluded=Counter();all_rows=[];units=defaultdict(list)
    obs=meta.get('observations',[]) if observations is None else observations
    if len({o['barcode'] for o in obs})!=len(obs):raise ValueError('duplicate_cell_axis')
    retained={o['barcode'] for o in obs if o.get('retained',True)}
    if not set(annotations)<=retained:raise ValueError('annotation_cell_axis_invalid')
    for o in obs:
        barcode=o['barcode'];cluster=clusters.get(barcode);a=annotations.get(barcode,{})
        reason=None
        if not o.get('retained',True):reason='not_retained'
        elif config.condition_values and o.get('condition') not in config.condition_values:reason='condition_not_selected'
        elif config.cluster_ids and cluster not in config.cluster_ids:reason='cluster_not_selected'
        elif config.label_ids and a.get('status')!='assigned':reason='annotation_'+str(a.get('status') or 'unlabeled')
        elif config.label_ids and a.get('label_id') not in config.label_ids:reason='label_not_selected'
        row=dict(barcode=barcode,cluster=cluster,label_id=a.get('label_id'),annotation_status=a.get('status'),
            donor=o.get('donor'),condition=o.get('condition'),sample=o.get('sample'),batch=o.get('batch'),selected=reason is None,exclusion_reason=reason)
        all_rows.append(row)
        if reason:excluded[reason]+=1;continue
        # Missing donors remain sample-level descriptive units, never inferred donors.
        identity=(row['donor'],row['condition'],None if row['donor'] else row['sample'])
        uid='u'+hashlib.sha256(json.dumps(identity,separators=(',',':')).encode()).hexdigest()[:20]
        row['unit_id']=uid;selected.append(row);units[uid].append(row)
    unit_rows=[dict(unit_id=uid,donor=rows[0]['donor'],condition=rows[0]['condition'],cell_count=len(rows),
        samples=sorted({r['sample'] for r in rows if r['sample']}),label_counts=dict(Counter(r['label_id'] for r in rows if r['label_id'])))
        for uid,rows in sorted(units.items())]
    return dict(selected=selected,all_cells=all_rows,exclusions=dict(excluded),units=unit_rows,label_names=label_names)


def validate_topic_design(config,sources,observations=None):
    from .design import DesignPreview,DesignReason,ResourceEstimate,ActualUnits
    config=SingleCellTopicConfig.model_validate(config);reasons=[];warnings=[];actual=[]
    def block(code,message):reasons.append(DesignReason(code=code,message=message))
    try:data=topic_selection(config,sources,observations)
    except ValueError as exc:
        return DesignPreview(executable=False,blocking_reasons=[DesignReason(code=str(exc),message='专题来源、标签或细胞身份不匹配。')],resource_estimate=ResourceEstimate(observations=0,features=0,contrasts=0,estimated_working_bytes=0))
    selected=data['selected'];n=len(selected);source=next(s for s in sources if s['source_id']==config.processed_source_id)
    if n<4:block('topic_too_few_cells','选择后至少需要4个细胞。')
    if not config.labels_confirmed and config.label_ids:warnings.append('标签为候选或工程选择，不能解释为已确认的生物学身份。')
    warnings.append('该专题为模型推断；工程运行通过不等于生物学验证。')
    if config.method=='slingshot':
        clusters={r['cluster'] for r in selected}
        if None in clusters:block('trajectory_cluster_missing','选定细胞缺少固定聚类。')
        if config.root_cluster not in clusters:block('trajectory_root_missing','根节点不在选定细胞的聚类中。')
        if len(clusters)<2:block('trajectory_two_clusters_required','轨迹需要至少两个选定聚类。')
        if {'pca':'pca','pca_unadjusted':'integration_x_pca_unadjusted','pca_harmony':'integration_x_pca_harmony'}[config.representation] not in source.get('members',{}):block('trajectory_representation_missing','当前结果没有所选降维表示。')
        warnings.append('pseudotime是所选表示和根下的相对坐标，不是真实时间或因果。')
    elif config.method=='genie3':
        if n>5000:block('regulation_cell_limit','GENIE3首期最多选择5000个细胞，请明确缩小类型、聚类或条件。')
        if not set(config.gene_ids)<=set(source['metadata'].get('retained_feature_ids',[])):block('regulation_gene_axis_mismatch','基因和TF必须在当前保留特征轴中。')
        warnings.append('GENIE3权重不是P值或因果；两种子比较只衡量随机稳定性。')
    else:
        if config.species_taxon_id is not None and source['metadata'].get('species_taxon_id') not in (None,config.species_taxon_id):
            block('communication_species_declaration_conflict','声明物种与固定来源物种不一致，不能覆盖已有物种。')
        if source['metadata'].get('species_taxon_id')!=9606:block('communication_resource_species_mismatch','当前文献演示LR资源仅适用于明确的人类数据。')
        if len(data['units'])>30:block('communication_unit_limit','首期一次最多30个供者×条件单位。')
        if any(not r['donor'] and not r['sample'] for r in selected):block('communication_unit_identity_missing','通讯需要供者或实际样本身份，不能将未知来源任意合并。')
        warnings.append('LR资源为小规模文献演示集合，并非全库；细胞置换P值不代表供者层显著性。')
        if config.communication_mode!='per_donor':
            if any(not r['donor'] for r in selected):block('communication_donor_required','条件比较需要真实供者身份。')
            groups=[{r['donor'] for r in selected if r['condition']==c and r['donor']} for c in config.condition_values]
            pairs=groups[0]&groups[1]
            if config.communication_mode=='paired' and (len(pairs)<3 or groups[0]!=groups[1]):block('communication_complete_pairs_required','配对比较需要至少3个完整供者对，不能遗漏条件。')
            if config.communication_mode=='unpaired' and (min(map(len,groups))<3 or pairs):block('communication_independent_donors_required','非配对比较每组至少3个独立供者，两组不得重叠。')
            actual=[ActualUnits(contrast_id='communication',numerator=config.condition_values[1],denominator=config.condition_values[0],observation_level='donor',inference_scope='donor_inference',
                n_numerator=len(groups[1]),n_denominator=len(groups[0]),spots_numerator=sum(r['condition']==config.condition_values[1] for r in selected),spots_denominator=sum(r['condition']==config.condition_values[0] for r in selected),complete_pairs=len(pairs))]
    features=len(config.gene_ids) if config.method=='genie3' else config.n_components if config.method=='slingshot' else 0
    return DesignPreview(executable=not reasons,blocking_reasons=reasons,actual_units=actual,warnings=warnings,
        resource_estimate=ResourceEstimate(observations=n,features=features,contrasts=len(actual),estimated_working_bytes=256*1024**2+n*max(features,30)*8*4))
