"""Pure sample design admission; the numeric worker checks the actual arrays."""
from pydantic import Field
from .contracts import StrictModel
from .design import DesignReason,ResourceEstimate,_rank
from .quantitative_contracts import QuantitativeComparisonConfig,quantitative_scope


class QuantitativeDesignPreview(StrictModel):
    executable: bool
    blocking_reasons: list[DesignReason]=Field(default_factory=list)
    actual_units: list[dict]=Field(default_factory=list)
    family: list[str]
    resource_estimate: ResourceEstimate
    warnings: list[str]=Field(default_factory=list)
    exclusions: list[dict]=Field(default_factory=list)


def sample_key(row):
    return (row['processed_version_id'],row['sample_id']) if isinstance(row,dict) else (row.processed_version_id,row.sample_id)


def validate_quantitative_design(config,sources):
    config=QuantitativeComparisonConfig.model_validate(config)
    sources=[s for s in sources if s['source_kind']=='bio_processed_dataset_version']
    reasons=[];units=[];exclusions=[];selected=set();by_key={};canonical=[]
    def block(code,message,cid=None):
        reason=DesignReason(code=code,message=message,contrast_id=cid)
        if reason not in reasons:reasons.append(reason)
    if not sources:block('missing_processed_source','缺少固定处理来源。')
    scales=[];feature_axes=[];assays=[]
    for source in sources:
        meta=source['metadata'];canonical.append(meta['canonical_dataset_id']);assays.append(meta['assay'])
        if meta.get('observation_level')!='sample':block('sample_source_required','定量比较只接受真实 sample 轴。')
        if (meta.get('species_taxon_id'),meta.get('namespace'),meta.get('reference_version'))!=(config.species_taxon_id,config.namespace,config.reference_version):block('incompatible_feature_metadata','物种、命名空间或参考版本不匹配。')
        if config.mode=='bulk_counts' and meta['assay']!='bulk_rna_counts':block('raw_counts_required','计数模型必须使用原始整数 counts 来源。')
        if config.mode=='continuous':
            scale=meta.get('layers',{}).get(config.analysis_layer)
            if not scale:block('analysis_layer_missing','所选处理层不存在。')
            else:scales.append({k:v for k,v in scale.items() if k not in ('values','missing','shape')})
        feature_axes.append(set(meta.get('retained_feature_ids',meta['feature_ids']) if config.mode=='continuous' else meta['feature_ids']))
        for row in meta['observations']:
            key=sample_key(row)
            if key in by_key:block('duplicate_sample_key','样本键重复。')
            by_key[key]=row
    if len(canonical)!=len(set(canonical)):block('duplicate_canonical_dataset','同源数据不同表示不能作为独立输入。')
    if scales and any(s!=scales[0] for s in scales):block('incompatible_layer_scale','跨来源实际处理尺度和单位不兼容。')
    common=set.intersection(*feature_axes) if feature_axes else set()
    if not common:block('empty_common_features','不存在共同稳定特征。')
    excluded={sample_key(s):s.reason for s in config.excluded_samples}
    if len(excluded)!=len(config.excluded_samples):block('duplicate_exclusion','重复排除样本。')
    if set(excluded)-set(by_key):block('unknown_exclusion','排除列表引用未知样本。')
    if config.inference_unit=='technical':
        if not config.technical_exploration_confirmed or config.inference_goal!='exploratory':block('technical_exploration_unconfirmed','须明确确认技术测量层探索；不能声明生物推断。')
    elif not config.independence_confirmed or not config.independence_basis.strip():block('independence_unconfirmed','须确认独立生物学单位及其依据。')
    if not config.design_basis.strip():block('design_basis_missing','须提供明确设计依据。')
    scope=quantitative_scope(config,assays)
    for contrast in config.contrasts:
        cid=contrast.contrast_id;groups=[];seen=set()
        for group in contrast.groups:
            rows=[]
            for item in group.sample_keys:
                key=sample_key(item);selected.add(key)
                if key in seen:block('overlapping_or_duplicate_samples','同一对比中样本必须唯一且组间不重叠。',cid)
                seen.add(key);row=by_key.get(key)
                if row is None:block('unknown_sample','组别引用未知样本。',cid);continue
                if key in excluded:continue
                if not row.get('retained'):block('sample_not_retained','组别引用已被处理配方排除的样本。',cid);continue
                if config.mode=='bulk_counts' and row.get('condition')!=group.label:block('condition_group_mismatch','counts 条件必须与原元数据完全相符。',cid)
                rows.append(row)
            groups.append(rows)
        flat=[r for g in groups for r in g];minimum=5 if config.method=='kruskal_wallis' else 3
        if min(map(len,groups),default=0)<minimum:block('insufficient_samples',f'每组或完整配对至少需要 {minimum} 个样本。',cid)
        if sum(map(len,groups))>10000:block('sample_limit','比较最多 10000 个观测。',cid)
        biological=[r.get('biological_unit_id') or r.get('donor') for r in flat]
        if config.inference_unit=='biological':
            if any(r.get('sample_role')=='technical' for r in flat) or any(not b for b in biological):block('biological_units_missing','技术运行或缺少真实生物学单位不能由确认开关升级为生物推断。',cid)
            if config.design!='paired' and len(set(biological))!=len(biological):block('nonindependent_biological_units','非配对组包含重复生物学单位。',cid)
            if config.design=='paired' and any(len({r.get('biological_unit_id') or r.get('donor') for r in g})!=len(g) for g in groups):block('nonindependent_biological_units','同一配对组内存在重复生物学单位，不能以不同配对标签视作独立重复。',cid)
        pairs=0;covariate=None;rank=columns=0;residual=0
        if config.design=='paired':
            keys=[[r.get(config.pairing_field) for r in g] for g in groups]
            if any(not k for g in keys for k in g) or any(len(g)!=len(set(g)) for g in keys) or set(keys[0])!=set(keys[1]):block('incomplete_or_duplicate_pairs','配对键必须非空、组内唯一且两侧完全一致。',cid)
            pairs=len(set(keys[0])&set(keys[1])-{None,''});covariate=config.pairing_field
        elif config.batch_adjustment:
            covariate='batch'
            if any(not r.get('batch') for r in flat):block('batch_missing','批次调整要求完整批次。',cid)
        if config.mode=='bulk_counts':
            levels=sorted({str(r.get(covariate)) for r in flat}) if covariate else []
            columns=2+max(0,len(levels)-1)
            if columns>100 or len(flat)>5000:block('design_capacity','设计超过 100 列或 5000 样本。',cid)
            elif flat:
                matrix=[[1,side]+[int(str(r.get(covariate))==level) for level in levels[1:]] for side,g in enumerate(groups) for r in g]
                rank=_rank(matrix);residual=len(flat)-rank
                if rank!=columns or residual<=0:block('rank_deficient_design','设计混杂、不满列秩或没有正残差自由度。',cid)
        units.append(dict(contrast_id=cid,observation_level='sample',inference_scope=scope,numerator=contrast.groups[0].label if len(groups)==2 else None,
            denominator=contrast.groups[1].label if len(groups)==2 else None,n_numerator=len(groups[0]),n_denominator=len(groups[1]),
            group_sizes={g.label:len(rows) for g,rows in zip(contrast.groups,groups)},complete_pairs=pairs,
            biological_n=0 if config.inference_unit=='technical' else len(set(biological)-{None,''}),
            biological_units_numerator=0 if config.inference_unit=='technical' else len({r.get('biological_unit_id') or r.get('donor') for r in groups[0]}-{None,''}),
            biological_units_denominator=0 if config.inference_unit=='technical' else len({r.get('biological_unit_id') or r.get('donor') for r in groups[1]}-{None,''}),inference_unit=config.inference_unit,
            design_columns=columns,design_rank=rank,residual_degrees_freedom=residual))
    for key,row in by_key.items():
        if key in excluded or key not in selected or not row.get('retained'):
            exclusions.append(dict(processed_version_id=key[0],sample_id=key[1],reason=excluded.get(key) or ('not_retained' if not row.get('retained') else 'unassigned_to_any_contrast')))
    size=len(common)*len(selected)*64+len(common)*len(config.contrasts)*1024
    if size>2*1024**3:block('resource_budget_exceeded','估计工作内存超过 2GiB。')
    warnings=['样本标识和软件一致性检查不能证明生物学独立性或功效。','缺失按每特征完整观测/完整配对处理；不插补，LOD/非随机缺失可能影响推断。']
    if config.inference_unit=='technical':warnings.append('仅技术测量层探索；真实独立生物学 n=0。')
    if scope=='sample_exploratory':warnings.append('sample_exploratory：P/q 为探索性证据，不构成确认性或因果结论。')
    return QuantitativeDesignPreview(executable=not reasons,blocking_reasons=reasons,actual_units=units,family=config.family_contrast_ids,warnings=warnings,exclusions=exclusions,
        resource_estimate=ResourceEstimate(observations=len(selected),features=len(common),contrasts=len(config.contrasts),estimated_working_bytes=size))
