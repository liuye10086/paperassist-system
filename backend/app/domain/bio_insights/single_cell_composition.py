"""Pure fixed-label counting and donor-design checks; no scientific imports."""
from collections import Counter,defaultdict
import hashlib
import json
from .single_cell_composition_contracts import SingleCellCompositionConfig,SingleCellSelection

CATEGORIES=('unknown','uncertain','conflict','unlabeled','other')


def annotation_cells(selection,sources,observations=None):
    selection=SingleCellSelection.model_validate({k:v for k,v in (selection.model_dump() if hasattr(selection,'model_dump') else selection).items() if k in SingleCellSelection.model_fields})
    def require(kind,sid):
        matches=[s for s in sources if s['source_kind']==kind and s['source_id']==sid]
        if len(matches)!=1:raise ValueError('single_cell_source_missing_or_duplicate')
        return matches[0]
    processed=require('bio_processed_dataset_version',selection.processed_source_id)
    annotation=require('bio_annotation_version',selection.annotation_source_id)
    if processed['metadata'].get('assay')!='single_cell':raise ValueError('single_cell_processed_required')
    meta=annotation['metadata']
    if meta.get('processed_dataset_version_id')!=selection.processed_source_id:raise ValueError('annotation_processed_mismatch')
    labels={r['id']:r for r in meta.get('labels',[])}
    if not set(selection.label_ids)<=set(labels):raise ValueError('annotation_label_unknown')
    observations=processed['metadata']['observations'] if observations is None else observations
    retained={o['barcode']:o for o in observations if o.get('retained',True)}
    if len(retained)!=sum(bool(o.get('retained',True)) for o in observations):raise ValueError('duplicate_cell_axis')
    rows=meta.get('assignments',{}).get('rows',[])
    by_barcode={r['barcode']:r for r in rows}
    if len(rows)!=len(by_barcode) or not set(by_barcode)<=set(retained):raise ValueError('annotation_cell_axis_invalid')
    for r in rows:
        if r.get('label_id') is not None and r['label_id'] not in labels:raise ValueError('annotation_label_unknown')
    return selection,retained,by_barcode


def selected_cell_keys(selection,sources,observations=None):
    selection,retained,rows=annotation_cells(selection,sources,observations)
    if not selection.labels_confirmed or not selection.label_basis.strip():raise ValueError('manual_labels_unconfirmed')
    return {(selection.processed_source_id,b) for b,r in rows.items() if r.get('status')=='assigned' and r.get('label_id') in selection.label_ids}


def validate_de_selection(config,sources,observations=None):
    if config.single_cell_selection is None:return
    selected=selected_cell_keys(config.single_cell_selection,sources,observations)
    if config.mode=='spot_exploratory':raise ValueError('single_cell_selection_requires_donor_model')
    for contrast in config.contrasts:
        for group in (contrast.numerator,contrast.denominator):
            if any((k.processed_version_id,k.barcode) not in selected for k in group.observation_keys):
                raise ValueError('single_cell_selection_membership_mismatch')


def composition_data(config,sources,observations=None):
    config=SingleCellCompositionConfig.model_validate(config)
    _,retained,rows=annotation_cells(config,sources,observations)
    units=defaultdict(list);assignments=[]
    categories=[('label',label) for label in config.label_ids]+[(c,None) for c in CATEGORIES]
    for barcode,o in retained.items():
        if o.get('condition') not in (config.denominator,config.numerator):continue
        # Known donors always merge all technical samples in donor x condition.
        donor=o.get('donor');sample=o.get('sample')
        identity=(donor,o['condition'],None if donor else sample)
        unit_id='u'+hashlib.sha256(json.dumps(identity,separators=(',',':')).encode()).hexdigest()[:24]
        r=rows.get(barcode);status=r.get('status') if r else 'unlabeled'
        category=('label' if r.get('label_id') in config.label_ids else 'other') if status=='assigned' else ('conflict' if status in ('ambiguous','conflict') else status if status in ('unknown','uncertain') else 'unlabeled')
        label=r.get('label_id') if category=='label' else None
        assignments.append(dict(processed_version_id=config.processed_source_id,barcode=barcode,unit_id=unit_id,
            donor=donor,condition=o['condition'],sample=sample,batch=o.get('batch'),category=category,label_id=label,
            annotation_status=status,annotation_label_id=r.get('label_id') if r else None))
        units[unit_id].append(assignments[-1])
    counts=[];unit_rows=[]
    for uid,members in sorted(units.items(),key=lambda item:(item[1][0]['condition']!=config.denominator,item[0])):
        first=members[0];counter=Counter((r['category'],r['label_id']) for r in members)
        batch=sorted({r['batch'] for r in members if r['batch'] is not None})
        unit_rows.append(dict(unit_id=uid,donor=first['donor'],condition=first['condition'],
            batch=batch[0] if len(batch)==1 and all(r['batch'] for r in members) else None,
            batches=batch,samples=sorted({r['sample'] for r in members if r['sample']}),cell_count=len(members),
            batch_complete=all(bool(r['batch']) for r in members)))
        for category,label in categories:
            n=counter[category,label]
            counts.append(dict(unit_id=uid,donor=first['donor'],condition=first['condition'],category=category,label_id=label,
                cell_count=n,denominator_cells=len(members),proportion=n/len(members)))
    return dict(units=unit_rows,counts=counts,assignments=assignments,categories=categories)


def validate_composition_design(config,sources,observations=None):
    from .design import DesignPreview,DesignReason,ResourceEstimate,ActualUnits,_rank
    config=SingleCellCompositionConfig.model_validate(config)
    reasons=[];warnings=['技术样本按 donor × condition 合并；最低供者数不是统计功效保证。',
        '分母为选定条件内全部保留细胞；unknown、uncertain、conflict、unlabeled 和其他标签均计入。']
    def block(code,message):
        if code not in {r.code for r in reasons}:reasons.append(DesignReason(code=code,message=message))
    try:data=composition_data(config,sources,observations)
    except ValueError as exc:
        return DesignPreview(executable=False,blocking_reasons=[DesignReason(code=str(exc),message='固定单细胞与人工标签来源不一致。')],resource_estimate=ResourceEstimate(observations=0,features=0,contrasts=1,estimated_working_bytes=0))
    units=data['units'];groups=[[u for u in units if u['condition']==c] for c in (config.numerator,config.denominator)]
    single_condition=config.mode=='descriptive' and config.numerator==config.denominator
    if single_condition:groups[0]=[]
    donors=[sorted({u['donor'] for u in g if u['donor']}) for g in groups];pairs=set(donors[0])&set(donors[1])
    if not units or config.mode!='descriptive' and any(not g for g in groups):block('empty_composition_condition','选定条件没有保留细胞。')
    elif single_condition:warnings.append('单条件组成描述；不构造第二组，不计算组间差值、比值或P值。')
    elif any(not g for g in groups):warnings.append('一个选定条件没有细胞；仅展示现有条件的组成，缺失条件的比例与差值为空。')
    if not config.labels_confirmed or not config.label_basis.strip():
        if config.mode!='descriptive':block('manual_labels_unconfirmed','推断需要研究者确认标签及人工依据。')
        else:warnings.append('标签尚未人工确认；仅描述候选标签，不能解释为已确认细胞身份。')
    columns=rank=residual=0
    if config.mode!='descriptive':
        if not config.mapping_confirmed:block('mapping_unconfirmed','供者映射尚未确认。')
        if not config.independence_confirmed or not config.independence_basis.strip():block('independence_unconfirmed','需要明确供者独立性或配对依据。')
        if any(not u['donor'] for u in units):block('donor_missing','推断不能用缺少 donor 的细胞。')
        if config.mode=='donor_unpaired':
            if pairs:block('donor_crosses_conditions','非配对供者不能跨条件。')
            if min(map(len,donors))<3:block('insufficient_donors','非配对每组至少三名独立供者。')
        else:
            if set(donors[0])!=set(donors[1]):block('incomplete_pairs','配对设计存在不完整供者对。')
            if len(pairs)<3:block('insufficient_pairs','至少需要三个完整供者对。')
        if config.batch_adjustment and any(not u['batch'] for u in units):block('aggregate_batch_not_unique','模型中的供者条件单元必须有唯一完整 batch。')
        if config.batch_adjustment and len({u['batch'] for u in units if u['batch']})<2:block('single_batch_adjustment','启用batch模型项需要至少两个真实批次。')
        levels=sorted({u['donor'] if config.mode=='donor_paired' else u['batch'] for u in units},key=str)
        covariate=config.mode=='donor_paired' or config.batch_adjustment
        columns=2+(max(len(levels)-1,0) if covariate else 0)
        if columns>100 or len(units)>200:block('design_preview_capacity','超出200供者条件单元或100模型列。')
        elif units:
            matrix=[[1,int(u['condition']==config.numerator)]+([int((u['donor'] if config.mode=='donor_paired' else u['batch'])==level) for level in levels[1:]] if covariate else []) for u in units]
            rank=_rank(matrix);residual=len(units)-rank
            if rank<columns:block('rank_deficient_design','batch与condition混杂或模型矩阵秩不足。')
            if residual<=0:block('no_residual_degrees_freedom','模型没有正残差自由度。')
    actual=ActualUnits(contrast_id='composition',numerator=config.numerator,denominator=config.denominator,
        observation_level='donor',inference_scope='donor_inference' if config.mode!='descriptive' else 'sample_exploratory',
        n_numerator=len(donors[0]),n_denominator=len(donors[1]),spots_numerator=sum(u['cell_count'] for u in groups[0]),
        spots_denominator=sum(u['cell_count'] for u in groups[1]),complete_pairs=len(pairs),numerator_donors=donors[0],denominator_donors=donors[1],
        design_columns=columns,design_rank=rank,residual_degrees_freedom=residual)
    return DesignPreview(executable=not reasons,blocking_reasons=reasons,actual_units=[actual],warnings=warnings,
        resource_estimate=ResourceEstimate(observations=len(data['assignments']),features=len(config.label_ids)+len(CATEGORIES),contrasts=1,
            estimated_working_bytes=128*1024**2+len(data['assignments'])*2048+len(units)*(len(config.label_ids)+len(CATEGORIES))*256))
