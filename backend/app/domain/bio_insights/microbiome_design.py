"""Source-preserving microbiome admission and audit, before inference."""
from collections import defaultdict
import csv, math, hashlib, json
from pathlib import Path
from pydantic import Field
from .contracts import StrictModel
from .design import DesignReason, ResourceEstimate
from .microbiome_contracts import MicrobiomeConfig

def key(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
def table(member):
    from app.adapters.bio_insights_engine.inputs import verify_member
    with verify_member(member).open(encoding='utf-8-sig',newline='') as stream:return list(csv.DictReader(stream,delimiter='\t'))

def prepare_microbiome(config,sources):
    config=MicrobiomeConfig.model_validate(config)
    selected=[s for s in sources if s['source_kind']=='bio_processed_dataset_version' and s['source_id']==config.processed_source_id]
    if len(selected)!=1:raise ValueError('microbiome_one_processed_source_required')
    source=selected[0];raw=source.get('raw',{});manifest=raw.get('manifest',{})
    for member_key in ('samples','features'):
        if member_key in source.get('members',{}) and any(r.get('kept') not in (None,'True','true','1') for r in table(source['members'][member_key])):raise ValueError('microbiome_requires_unfiltered_source_bridge')
    if manifest.get('schema_version')!=3 or manifest.get('assay')!='microbiome':raise ValueError('microbiome_versioned_assay_required')
    from app.adapters.bio_engine.tabular_assays import load_tabular
    values,missing,samples,features=load_tabular(raw)
    if not 1<=len(samples)<=500 or not 1<=len(features['feature_ids'])<=10000:raise ValueError('microbiome_axis_limit')
    expected_scale=('raw_counts','counts') if config.abundance_scale=='counts' else ('relative_abundance',config.abundance_scale)
    if (manifest['scale']['kind'],manifest['scale']['unit'])!=expected_scale:raise ValueError('microbiome_scale_mismatch')
    if set(samples)&{'row_key','feature_id','sample_id','taxon_path'}:raise ValueError('microbiome_reserved_sample_identifier')
    feature_rows=table(raw['members']['features']);sample_rows=table(raw['members']['samples'])
    by_sample={r['sample_id']:r for r in sample_rows};by_feature={r['feature_id']:r for r in feature_rows}
    if set(by_sample)!=set(samples) or set(by_feature)!=set(features['feature_ids']):raise ValueError('microbiome_metadata_axis_mismatch')
    for column in config.taxonomy_columns:
        if any(column not in r for r in feature_rows):raise ValueError('microbiome_taxonomy_column_missing:'+column)
    for column in (config.group_column,config.unit_column,config.pair_column):
        if column and any(column not in r for r in sample_rows):raise ValueError('microbiome_sample_column_missing:'+column)
    paths=[];taxonomy=[];end=config.taxonomy_columns.index(config.aggregate_rank)+1
    for fid in features['feature_ids']:
        row=by_feature[fid];path=[];absent=[]
        for rank in config.taxonomy_columns:
            value=row.get(rank)
            if value is None or value in config.taxonomy_na_values:absent.append(rank);value='Unclassified'
            path.append([rank,value])
        identity=json.dumps(path[:end],ensure_ascii=False,separators=(',',':'));paths.append(identity)
        taxonomy.append(dict(row_key=key(['taxonomy',fid]),feature_id=fid,taxon_path=identity,taxon_label=path[end-1][1],unclassified_ranks=absent,source_taxonomy=row))
    audit=[];relative=[];included=[];raw_matrix=[]
    for i,sample in enumerate(samples):
        vector=values[i];mask=missing[i]
        if any(float(v)<0 or not math.isfinite(float(v)) for v in vector):raise ValueError('microbiome_nonnegative_finite_required')
        if config.abundance_scale=='counts' and any(float(v)!=int(v) for v in vector):raise ValueError('microbiome_counts_integer_required')
        total=sum(map(int,vector)) if config.abundance_scale=='counts' else math.fsum(map(float,vector));reason='missing_abundance' if mask.any() else 'all_zero_sample' if total==0 else None
        expected=100. if config.abundance_scale=='percent' else 1.
        if config.abundance_scale!='counts' and any(float(v)>expected*(1+config.rounding_tolerance) for v in vector):raise ValueError('microbiome_value_exceeds_declared_scale')
        scaled_total=total/expected if config.abundance_scale!='counts' else total
        if reason is None and config.abundance_scale!='counts' and abs(scaled_total-1)>config.rounding_tolerance and not config.closure_confirmed:raise ValueError('microbiome_sample_total_requires_explicit_closure:'+sample)
        if reason is None and config.abundance_scale!='counts' and scaled_total!=1 and not config.closure_confirmed:raise ValueError('microbiome_explicit_closure_required:'+sample)
        audit.append(dict(row_key=key(['sample',sample]),sample_id=sample,included=reason is None,reason=reason,original_sum=None if mask.any() else total,observed_partial_sum=total,missing_features=int(mask.sum()),input_scale=config.abundance_scale,relative_sum_before_closure=None if mask.any() else scaled_total,closure_applied=reason is None and config.abundance_scale!='counts' and scaled_total!=1,closure_factor=1/total if reason is None else None,metadata=by_sample[sample]))
        if reason is None:
            included.append(sample);relative.append([float(v)/total for v in vector]);raw_matrix.append([float(v) for v in vector])
    return dict(config=config,source=source,samples=samples,features=features['feature_ids'],included=included,relative=relative,raw_values=raw_matrix,audit=audit,taxonomy=taxonomy,paths=paths,metadata=by_sample)

class MicrobiomePreview(StrictModel):
    executable: bool
    blocking_reasons: list[DesignReason] = Field(default_factory=list)
    actual_units: list[dict] = Field(default_factory=list)
    family: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    resource_estimate: ResourceEstimate

def validate_microbiome_design(config,sources):
    config=MicrobiomeConfig.model_validate(config);reasons=[];units=[];warnings=[];data=None
    try:
        data=prepare_microbiome(config,sources)
        meta=data['metadata'];valid=data['included']
        if len(valid)<2:raise ValueError('microbiome_two_nonempty_complete_samples_required')
        if len(valid)<len(data['samples']):warnings.append('全零或含缺测丰度的样本保留审计，从组成、alpha、距离与排序中整体排除；不填补。')
        infer=config.beta_inference or bool(config.contrasts)
        na_values=set(data['source']['raw']['manifest']['import_config']['na_values'])
        def metadata_missing(value):return value is None or value in na_values or value in ('',r'\N')
        if infer:
            for s in valid:
                if any(metadata_missing(meta[s].get(c)) for c in (config.group_column,config.unit_column) if c):raise ValueError('microbiome_inference_metadata_missing')
            records=[(meta[s][config.unit_column],meta[s][config.group_column]) for s in valid]
            if len(records)!=len(set(records)):raise ValueError('microbiome_repeated_unit_condition_not_independent')
            if config.design=='independent' and len({u for u,g in records})!=len(records):raise ValueError('microbiome_repeated_units_block_independent_inference')
        for c in config.contrasts:
            groups=[[s for s in valid if meta[s][config.group_column]==g] for g in (c.numerator,c.denominator)]
            if config.design=='paired':
                pairs=[[meta[s].get(config.pair_column) for s in group] for group in groups]
                if any(metadata_missing(p) for group in pairs for p in group) or any(len(g)!=len(set(g)) for g in pairs) or set(pairs[0])!=set(pairs[1]):raise ValueError('microbiome_complete_unique_pairs_required')
            units.append(dict(contrast_id=c.contrast_id,n_numerator=len(groups[0]),n_denominator=len(groups[1]),complete_pairs=len(groups[0]) if config.design=='paired' else 0,observation_level='sample'))
        if config.beta_inference:
            groups=defaultdict(int)
            for s in valid:groups[meta[s][config.group_column]]+=1
            if len(groups)<2 or min(groups.values())<3:raise ValueError('microbiome_beta_requires_three_samples_per_group')
        if not infer:warnings.append('仅描述性结果：不执行 alpha 比较或无限制 beta 置换；重复、分层或混杂不能据此作组间推断。')
    except (ValueError,KeyError) as exc:reasons.append(DesignReason(code='microbiome_design_invalid',message=str(exc)[:4000]))
    n=len(data['samples']) if data else 0;f=len(data['features']) if data else 0
    estimate=n*f*192+n*n*128+64*1024**2
    if estimate>=2*1024**3:reasons.append(DesignReason(code='microbiome_resource_limit',message='微生物组有限数组工作集估计超过 RSS 预算。'))
    return MicrobiomePreview(executable=not reasons,blocking_reasons=reasons,actual_units=units,family=[m+':'+c for m in config.alpha_metrics for c in config.family_contrast_ids],warnings=warnings,resource_estimate=ResourceEstimate(observations=n,features=f,contrasts=len(config.contrasts),estimated_working_bytes=estimate))
