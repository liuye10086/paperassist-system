"""Pure bounded design preview; the isolated engine rechecks actual matrix values."""
from collections import defaultdict
from fractions import Fraction

from pydantic import Field, model_serializer

from .contracts import ComparisonConfig, Identifier, ObservationKey, StrictModel, Text


class Observation(ObservationKey):
    donor: Identifier | None = None
    condition: Identifier | None = None
    batch: Identifier | None = None
    sample: Identifier | None = None
    section: Identifier | None = None
    canonical_dataset_id: Identifier | None = None
    retained: bool = True
    library_counts: int | None = Field(default=None,ge=0)


class FeatureMetadata(StrictModel):
    processed_version_id: Identifier
    species_taxon_id: int = Field(ge=1)
    namespace: Identifier
    reference_version: Identifier
    canonical_dataset_id: Identifier
    feature_count: int = Field(ge=0,le=10000000)
    counts_nonnegative_integer: bool = False
    counts_provenance: str = Field(default='unknown',max_length=200)
    filtered_feature_count: int | None = Field(default=None,ge=0,le=10000000)
    common_feature_count: int | None = Field(default=None,ge=0,le=10000000)


class DesignReason(StrictModel):
    code: Identifier
    message: Text
    contrast_id: Identifier | None = None


class ActualUnits(StrictModel):
    contrast_id: Identifier
    numerator: Identifier
    denominator: Identifier
    observation_level: str
    inference_scope: str
    n_numerator: int = Field(ge=0)
    n_denominator: int = Field(ge=0)
    spots_numerator: int = Field(ge=0)
    spots_denominator: int = Field(ge=0)
    complete_pairs: int = Field(default=0,ge=0)
    numerator_donors: list[Identifier] = Field(default_factory=list,max_length=10000)
    denominator_donors: list[Identifier] = Field(default_factory=list,max_length=10000)
    design_columns: int = Field(default=0,ge=0)
    design_rank: int = Field(default=0,ge=0)
    residual_degrees_freedom: int = 0


class DesignExclusion(ObservationKey):
    reason: Text


class ResourceEstimate(StrictModel):
    observations: int = Field(ge=0)
    features: int = Field(ge=0)
    contrasts: int = Field(ge=0)
    estimated_working_bytes: int = Field(ge=0)
    rss_limit_bytes: int = 2147483648
    estimate_only: bool = True


class DesignPreview(StrictModel):
    executable: bool
    blocking_reasons: list[DesignReason] = Field(default_factory=list,max_length=200)
    actual_units: list[ActualUnits] = Field(default_factory=list,max_length=30)
    family: list[Identifier] = Field(default_factory=list,max_length=30)
    resource_estimate: ResourceEstimate
    warnings: list[Text] = Field(default_factory=list,max_length=100)
    exclusions: list[DesignExclusion] = Field(default_factory=list,max_length=100000)
    enrichment_compatibility: dict[str, object] | None = None

    @model_serializer(mode='wrap')
    def preserve_design_wire(self, handler):
        data = handler(self)
        if self.enrichment_compatibility is None:
            data.pop('enrichment_compatibility', None)
        return data


def _key(row):
    return row.processed_version_id,row.barcode


def _rank(rows):
    """Exact categorical-design rank, bounded before any rational elimination."""
    if not rows:return 0
    if len(rows)>5000 or len(rows[0])>100:
        raise ValueError('design_preview_capacity')
    # Duplicate categorical rows add no rank; reducing them bounds the work further.
    matrix=[list(map(Fraction,row)) for row in dict.fromkeys(map(tuple,rows))]
    rank=0
    for column in range(len(matrix[0])):
        pivot=next((i for i in range(rank,len(matrix)) if matrix[i][column]),None)
        if pivot is None:continue
        matrix[rank],matrix[pivot]=matrix[pivot],matrix[rank]
        divisor=matrix[rank][column]
        matrix[rank]=[v/divisor for v in matrix[rank]]
        for i in range(rank+1,len(matrix)):
            multiplier=matrix[i][column]
            if multiplier:
                matrix[i]=[v-multiplier*p for v,p in zip(matrix[i],matrix[rank])]
        rank+=1
        if rank==len(matrix):break
    return rank


def validate_design(config, observations, features):
    """Validate server-resolved identities and metadata, never caller-supplied totals.

    Large selections/tables are read by the service from frozen members. Metadata
    claims are not numeric proof: counts, filtering, and rank are checked again in
    the isolated computation against actual inputs before publication.
    """
    config=ComparisonConfig.model_validate(config)
    if len(observations)>100000 or len(features)>100:
        raise ValueError('Design metadata exceeds bounded preview capacity')
    observations=[Observation.model_validate(o) for o in observations]
    features=[FeatureMetadata.model_validate(f) for f in features]
    reasons=[]
    warnings=[]
    units=[]
    exclusions=[]

    def block(code,message,contrast_id=None):
        reason=DesignReason(code=code,message=message,contrast_id=contrast_id)
        if reason not in reasons and len(reasons)<200:reasons.append(reason)

    by_key={_key(o):o for o in observations}
    if len(by_key)!=len(observations):block('duplicate_observation_key','观测键重复；数据版本与 barcode 必须唯一。')
    feature_by_version={f.processed_version_id:f for f in features}
    if len(feature_by_version)!=len(features):block('duplicate_feature_metadata','同一处理版本出现多份特征元数据。')
    canonical=[f.canonical_dataset_id for f in features]
    if len(canonical)!=len(set(canonical)):
        block('duplicate_canonical_dataset','H5/MTX 或其他同源数据表示不能重复作为独立输入。')
    for feature in features:
        if (feature.species_taxon_id,feature.namespace,feature.reference_version)!=(
                config.species_taxon_id,config.namespace,config.reference_version):
            block('incompatible_feature_metadata','物种、稳定 ID 命名空间或参考版本不兼容。')
        if config.mode!='spot_exploratory':
            if not feature.counts_nonnegative_integer or feature.counts_provenance!='raw_gene_expression':
                block('counts_not_raw_integer','供体模型必须使用有来源的非负原始 Gene Expression 整数 counts。')
            if feature.filtered_feature_count is None:
                block('feature_filter_unverified','尚未核对原 counts 聚合预过滤后的特征数量。')
            elif feature.filtered_feature_count==0:
                block('no_features_after_filter','按冻结规则预过滤后无可检验特征。')
        if not feature.feature_count:block('empty_feature_axis','输入特征轴为空。')
    if not features:block('missing_feature_metadata','缺少固定处理版本特征元数据。')
    if len(features)>1 and any(f.common_feature_count is None for f in features):
        block('common_feature_axis_unverified','多个来源必须明确共同稳定 ID 特征轴及非共同特征排除表。')
    if any(f.common_feature_count==0 for f in features):block('empty_common_feature_axis','多个来源没有共同稳定 ID 特征。')
    if config.mode!='spot_exploratory':
        if not config.mapping_confirmed:block('mapping_unconfirmed','供体对应表尚未确认。')
        if not config.independence_confirmed or not config.independence_basis.strip():
            block('independence_unconfirmed','独立供体或配对依据尚未人工确认。')
        warnings.append('软件只核对对应表一致性，不能证明真实供体独立性；最低数量不等于功效保证。')
    else:
        warnings.append('spot_exploratory：spot 不是独立生物学重复，P/q 仅作探索性排序。')
        if config.data_driven_grouping:warnings.append('分组来自同一表达数据，属于数据驱动分组。')

    explicit={_key(e):e.reason for e in config.excluded_observations}
    excluded_donors={e.donor:e.reason for e in config.excluded_donors}
    if len(explicit)!=len(config.excluded_observations) or len(excluded_donors)!=len(config.excluded_donors):
        block('duplicate_exclusion','排除清单的观测或供体重复。')
    for key in explicit:
        if key not in by_key:block('unknown_exclusion','明确排除的观测不在固定观测全集。')
    for donor in excluded_donors:
        if donor not in {o.donor for o in observations}:block('unknown_excluded_donor','明确排除的供体不在固定对应表。')
    selected_all=set()
    for contrast in config.contrasts:
        cid=contrast.contrast_id
        raw_keys=[[_key(k) for k in group.observation_keys] for group in (contrast.numerator,contrast.denominator)]
        for keys in raw_keys:
            if len(keys)!=len(set(keys)):block('duplicate_group_observation','同组观测键重复。',cid)
        if set(raw_keys[0]) & set(raw_keys[1]):block('overlapping_groups','两组观测重叠，必须先明确无重叠分配。',cid)
        selected_all.update(raw_keys[0]);selected_all.update(raw_keys[1])
        groups=[]
        for keys in raw_keys:
            group=[]
            for key in keys:
                observation=by_key.get(key)
                if observation is None:
                    block('unknown_observation','分组引用未知的数据版本与 barcode。',cid)
                    continue
                if key[0] not in feature_by_version:block('missing_feature_metadata','所选观测没有对应的特征元数据。',cid)
                if key in explicit or observation.donor in excluded_donors:continue
                if not observation.retained:
                    block('observation_not_retained','分组包含未通过既有质控的观测。',cid)
                    continue
                group.append(observation)
            groups.append(group)
        donors=[sorted({o.donor for o in group if o.donor}) for group in groups]
        pairs=set(donors[0])&set(donors[1])
        rank=columns=0
        residual=0
        if config.mode=='spot_exploratory':
            ns=list(map(len,groups))
            if min(ns)<3:block('insufficient_spots','探索比较两侧至少需要 3 个保留 spot。',cid)
        else:
            ns=list(map(len,donors))
            flat=groups[0]+groups[1]
            if any(not o.donor for o in flat):block('donor_missing','选定观测缺少明确 donor。',cid)
            if any(not o.condition for o in flat):block('condition_missing','选定观测缺少明确 condition。',cid)
            for group,label in zip(groups,(contrast.numerator.label,contrast.denominator.label)):
                if any(o.condition and o.condition!=label for o in group):
                    block('condition_group_mismatch','观测 condition 必须与固定比较组标签完全一致；显示名不会重新解释条件。',cid)
            if any(o.library_counts is None for o in flat):block('library_counts_unverified','尚未核对选定观测原始 counts 文库。',cid)
            grouped=[defaultdict(list),defaultdict(list)]
            for side,group in enumerate(groups):
                for o in group:
                    if o.donor:grouped[side][o.donor].append(o)
            aggregate=[]
            for side,donor_groups in enumerate(grouped):
                for donor,rows in sorted(donor_groups.items()):
                    if len({o.condition for o in rows})!=1:
                        block('aggregate_condition_not_unique','同一聚合单元的 condition 不唯一。',cid)
                    if ((config.batch_adjustment and any(not o.batch for o in rows)) or
                            ((config.batch_adjustment or config.single_cell_selection is None) and len({o.batch for o in rows})!=1)):
                        block('aggregate_batch_not_unique','同一聚合单元的 batch 缺失或不唯一。',cid)
                    if all(o.library_counts is not None for o in rows) and sum(o.library_counts for o in rows)==0:
                        block('zero_library','原 counts 聚合出现零文库。',cid)
                    aggregate.append((donor,side,rows[0].batch))
            if config.mode=='donor_unpaired':
                if pairs:block('donor_crosses_conditions','非配对供体不能跨两个比较条件。',cid)
                if min(ns)<3:block('insufficient_donors','非配对比较每组至少需要 3 个独立供体。',cid)
            else:
                if set(donors[0])!=set(donors[1]):block('incomplete_pairs','存在不完整供体对；须新计划明确排除后重新核对。',cid)
                if len(pairs)<3:block('insufficient_pairs','配对比较至少需要 3 个完整供体对。',cid)
            levels=sorted({row[0] if config.mode=='donor_paired' else row[2] for row in aggregate},key=lambda x:str(x))
            covariate=config.mode=='donor_paired' or config.batch_adjustment
            columns=2+(len(levels)-1 if covariate and levels else 0)
            if columns>100 or len(aggregate)>5000:
                block('design_preview_capacity','纯设计预检超出 5000 聚合单元或 100 设计列的边界。',cid)
            elif aggregate:
                rows=[[1,side]+([int((donor if config.mode=='donor_paired' else batch)==level) for level in levels[1:]] if covariate else [])
                      for donor,side,batch in aggregate]
                rank=_rank(rows)
                residual=len(aggregate)-rank
                if rank<columns:block('rank_deficient_design','批次混杂或分类设计矩阵不满列秩；不能自动删除模型项。',cid)
                if residual<=0:block('no_residual_degrees_freedom','设计没有正的残差自由度。',cid)
        units.append(ActualUnits(contrast_id=cid,numerator=contrast.numerator.label,denominator=contrast.denominator.label,
                                observation_level='spot' if config.mode=='spot_exploratory' else 'donor',
                                inference_scope='spot_exploratory' if config.mode=='spot_exploratory' else 'donor_inference',
                                n_numerator=ns[0],n_denominator=ns[1],spots_numerator=len(groups[0]),spots_denominator=len(groups[1]),
                                complete_pairs=len(pairs),numerator_donors=donors[0],denominator_donors=donors[1],
                                design_columns=columns,design_rank=rank,residual_degrees_freedom=residual))
    for key,observation in by_key.items():
        reason=explicit.get(key) or excluded_donors.get(observation.donor)
        if reason or key not in selected_all or not observation.retained:
            exclusions.append(DesignExclusion(processed_version_id=key[0],barcode=key[1],
                reason=reason or ('not_retained' if not observation.retained else 'unassigned_to_any_contrast')))
    used_keys=selected_all & set(by_key)
    common_counts=[f.common_feature_count if f.common_feature_count is not None else f.feature_count for f in features]
    nfeatures=min(common_counts,default=0)
    # Conservative admission estimate; actual sparse/fit RSS is separately enforced by the engine.
    estimated=(len(used_keys)*nfeatures*32 if config.mode=='spot_exploratory' else
        10000000*32+len(used_keys)*512+max((u.n_numerator+u.n_denominator for u in units),default=0)*nfeatures*128)+nfeatures*len(config.contrasts)*512
    if estimated>2147483648:block('resource_budget_exceeded','保守工作内存估计超过科学子进程 2 GiB 限额；不能静默抽样。')
    return DesignPreview(executable=not reasons,blocking_reasons=reasons,actual_units=units,
                         family=list(config.family_contrast_ids),warnings=warnings,exclusions=exclusions,
                         resource_estimate=ResourceEstimate(observations=len(used_keys),features=nfeatures,
                             contrasts=len(config.contrasts),estimated_working_bytes=estimated))
