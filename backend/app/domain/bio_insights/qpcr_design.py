"""qPCR long-table audit and deterministic normalization; no fitting or imputation."""
from collections import defaultdict
import hashlib
import json
import math
from statistics import mean, stdev
from pydantic import Field
from .qpcr_contracts import QpcrConfig
from .contracts import StrictModel
from .design import DesignReason, ResourceEstimate

def key(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

def cell_reference(column,row):
    letters=''
    while column:
        column,remainder=divmod(column-1,26);letters=chr(65+remainder)+letters
    return letters+str(row)

class QpcrPreview(StrictModel):
    executable: bool
    blocking_reasons: list[DesignReason] = Field(default_factory=list)
    actual_units: list[dict] = Field(default_factory=list)
    family: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    resource_estimate: ResourceEstimate

def prepare_qpcr(config,sources):
    config=QpcrConfig.model_validate(config)
    from app.adapters.bio_insights_engine.tables import iter_table, PARSER_VERSION
    selected=[s for s in sources if s['source_kind']=='original_file' and s['source_id']==config.file_source_id]
    if len(selected)!=1:raise ValueError('qpcr_original_file_required')
    source=selected[0];meta=source['metadata'];member=source['members']['original_file']
    if meta.get('parse_version_id')!=config.parse_version_id or meta.get('parser_version')!=PARSER_VERSION or source['sha256']!=member['sha256']:raise ValueError('qpcr_frozen_parse_mismatch')
    if member['format']=='xlsx' and (not config.sheet or meta.get('sheet')!=config.sheet):raise ValueError('qpcr_explicit_sheet_required')
    columns={k:v for k,v in config.columns.model_dump().items() if v}
    exclusions={(e.plate_id,e.well):e.reason for e in config.excluded_wells}
    if len(exclusions)!=len(config.excluded_wells):raise ValueError('qpcr_duplicate_exclusion')
    audit=[];groups=defaultdict(list);samples={};occupied=set();replicates=set();cells_count=0
    for number,cells in iter_table(member,format=member['format'],sheet=config.sheet,encoding=meta.get('encoding','utf-8-sig'),delimiter=meta.get('delimiter'),header_row=meta.get('header_row',1)):
        cells_count+=len(cells)
        if cells_count>1000000:raise ValueError('qpcr_million_cell_limit')
        if not set(columns.values())<=set(cells):raise ValueError('qpcr_mapped_column_missing')
        raw={k:cells[v] for k,v in columns.items()}
        explicitly_excluded=(raw['plate_id'],raw['well']) in exclusions
        for field,value in raw.items():
            if explicitly_excluded and field not in ('plate_id','well'):continue
            if field not in ('cq','time','dose','pair_id') and (not isinstance(value,str) or not value.strip() or len(value)>200):raise ValueError('qpcr_required_role_missing:'+field)
        plate,well,sample,target=(raw[f] for f in ('plate_id','well','sample_id','target_id'))
        if (plate,well) in occupied:raise ValueError('qpcr_plate_well_conflict')
        occupied.add((plate,well))
        rep=(plate,sample,target,raw['technical_replicate'])
        if not explicitly_excluded and rep in replicates:raise ValueError('qpcr_technical_replicate_conflict')
        if not explicitly_excluded:replicates.add(rep)
        identity={k:raw.get(k) for k in ('sample_id','biological_unit_id','condition','pair_id','time','dose')}
        if not explicitly_excluded:
            if sample in samples and samples[sample]!=identity:raise ValueError('qpcr_sample_role_inconsistent')
            samples[sample]=identity
            if config.design=='paired' and not identity.get('pair_id'):raise ValueError('qpcr_pair_identity_missing')
            if config.columns.time and raw.get('time') in (None,'') or config.columns.dose and raw.get('dose') in (None,''):raise ValueError('qpcr_time_or_dose_missing')
        status=raw['detection_status'];cq=None
        if not explicitly_excluded and status not in config.detected_values+config.nondetected_values:raise ValueError('qpcr_unknown_detection_status')
        if raw['cq'] not in (None,*config.na_values):
            try:cq=float(raw['cq'])
            except (TypeError,ValueError):
                if not explicitly_excluded:raise ValueError('qpcr_cq_invalid')
            if cq is not None and (not math.isfinite(cq) or cq<0):
                if not explicitly_excluded:raise ValueError('qpcr_cq_invalid')
                cq=None
        reason=exclusions.get((plate,well))
        if reason:reason='explicit_exclusion:'+reason
        elif target not in config.targets+config.references:reason='assay_not_selected'
        elif status in config.nondetected_values:reason='not_detected'
        elif cq is None:reason='cq_missing'
        row=dict(row_key=key(dict(file=source['sha256'],parse=config.parse_version_id,sheet=config.sheet,row=number)),source_row=number,
            file_source_id=source['source_id'],file_sha256=source['sha256'],parse_version_id=config.parse_version_id,sheet=config.sheet,
            source_columns=columns,source_locations={role:dict(sheet=config.sheet,row=number,column_header=header,column_index=list(cells).index(header)+1,cell=cell_reference(list(cells).index(header)+1,number)) for role,header in columns.items()},
            source_cells=cells,**raw,parsed_cq=cq,included=reason is None,reason=reason)
        audit.append(row)
        if not explicitly_excluded:groups[(plate,sample,target)].append(row)
    if not audit:raise ValueError('qpcr_empty_table')
    for row in audit:
        if str(row['reason']).startswith('explicit_exclusion:') and row['sample_id'] in samples:
            groups[(row['plate_id'],row['sample_id'],row['target_id'])].append(row)
    if set(exclusions)-occupied:raise ValueError('qpcr_excluded_well_not_found')
    missing_calibrators=set(config.calibrator_sample_ids)-set(samples)
    if missing_calibrators:raise ValueError('qpcr_calibrator_sample_ids_missing:'+','.join(sorted(missing_calibrators)))
    # Multiple aliquot/sample IDs never create extra independent biological n.
    unit_records={};pair_records={}
    for sample,record in samples.items():
        u=(record['biological_unit_id'],record['condition'])
        if u in unit_records and unit_records[u]!=sample:raise ValueError('qpcr_duplicate_biological_condition_or_time')
        unit_records[u]=sample
        if config.design=='paired':
            pair=(record['pair_id'],record['condition'])
            if pair in pair_records and pair_records[pair]!=sample:raise ValueError('qpcr_duplicate_pair_condition')
            pair_records[pair]=sample
    summaries=[];by_assay={}
    for (plate,sample,target),rows in sorted(groups.items()):
        measured=[r['parsed_cq'] for r in rows if r['included']];avg=mean(measured) if measured else None;sd=stdev(measured) if len(measured)>1 else None
        row=dict(row_key=key([plate,sample,target]),plate_id=plate,sample_id=sample,target_id=target,**{k:v for k,v in samples[sample].items() if k!='sample_id'},
            valid_wells=len(measured),total_wells=len(rows),mean_cq=avg,sd_cq=sd,
            missing_wells=sum(r['reason'] in ('cq_missing','not_detected') for r in rows),excluded_wells=sum(str(r['reason']).startswith('explicit_exclusion:') for r in rows),
            sd_warning=sd is not None and sd>config.technical_sd_warning,warning_only_no_auto_exclusion=True,biological_n=1)
        summaries.append(row);by_assay[(plate,sample,target)]=row
    plates_by_sample=defaultdict(set)
    for plate,sample,target in groups:plates_by_sample[sample].add(plate)
    normalized=[]
    for sample,plates in sorted(plates_by_sample.items()):
        for plate in sorted(plates):
            refs=[by_assay.get((plate,sample,r),{}).get('mean_cq') for r in config.references]
            for target in config.targets:
                target_cq=by_assay.get((plate,sample,target),{}).get('mean_cq');missing_refs=[r for r,cq in zip(config.references,refs) if cq is None]
                reason='target_missing' if target_cq is None else 'reference_missing:'+','.join(missing_refs) if missing_refs else None
                dcq=target_cq-mean(refs) if reason is None else None
                log_signal=(-target_cq*math.log2(config.efficiencies[target].factor)+mean(cq*math.log2(config.efficiencies[r].factor) for r,cq in zip(config.references,refs))) if reason is None and config.quantification=='efficiency' else -dcq if reason is None else None
                normalized.append(dict(row_key=key([plate,sample,target]),plate_id=plate,**samples[sample],target_id=target,feature_id=target,target_mean_cq=target_cq,
                    reference_mean_cq=mean(refs) if not missing_refs else None,reference_cq_by_assay=dict(zip(config.references,refs)),delta_cq=dcq,
                    log2_signal=log_signal,delta_delta_cq=None,log2_quantity=None,relative_quantity=None,calibrator_n=0,reason=reason,biological_n=1,
                    observation_level='sample',measurement_unit='fold',stratum=plate if config.cross_plate=='separate' else 'comparable_plates'))
    # Comparable plates first average each sample/assay Cq equally across plates.
    # A partially absent target/reference is never silently rescued from a different plate.
    if config.cross_plate=='comparable':
        collapsed=[]
        for sample in sorted(samples):
            for target in config.targets:
                records=[r for r in normalized if r['sample_id']==sample and r['target_id']==target];row=dict(records[0]);row['plate_id']='comparable_plates';row['row_key']=key(['comparable_plates',sample,target]);row['source_plates']=[r['plate_id'] for r in records]
                if any(r['reason'] for r in records):row['reason']='incomplete_assay_on_comparable_plate'
                else:
                    for field in ('target_mean_cq','reference_mean_cq','delta_cq','log2_signal'):row[field]=mean(r[field] for r in records)
                    row['reference_cq_by_assay']={a:mean(r['reference_cq_by_assay'][a] for r in records) for a in config.references}
                collapsed.append(row)
        normalized=collapsed
    calibration=[]
    for row in normalized:
        calibrators=[r for r in normalized if r['stratum']==row['stratum'] and r['target_id']==row['target_id'] and (r['condition'] in config.calibrator_conditions if config.calibrator_conditions else r['sample_id'] in config.calibrator_sample_ids)]
        row['calibrator_n']=len(calibrators)
        if not row['reason']:
            if not calibrators:row['reason']='calibrator_missing'
            elif any(r['reason'] for r in calibrators):row['reason']='calibrator_incomplete'
            else:
                row['delta_delta_cq']=row['delta_cq']-mean(r['delta_cq'] for r in calibrators)
                row['log2_quantity']=row['log2_signal']-mean(r['log2_signal'] for r in calibrators)
                try:quantity=2**row['log2_quantity']
                except OverflowError:quantity=float('inf')
                if not math.isfinite(quantity) or quantity==0:row['reason']='quantity_out_of_finite_range'
                else:row['relative_quantity']=quantity
        calibration.append(dict(row_key=row['row_key'],sample_id=row['sample_id'],target_id=row['target_id'],stratum=row['stratum'],calibrator_sample_ids=[r['sample_id'] for r in calibrators],calibrator_n=len(calibrators),calibrator_delta_cq=mean(r['delta_cq'] for r in calibrators) if calibrators and all(r['delta_cq'] is not None for r in calibrators) else None))
    checks=[]
    for check in config.original_checks:
        matches=[r for r in normalized if r['sample_id']==check.sample_id and r['target_id']==check.target_id and (r['plate_id']==check.plate_id or check.plate_id in r.get('source_plates',[]))]
        actual=matches[0][check.metric] if len(matches)==1 else None
        diff=actual-check.original_value if actual is not None else None
        checks.append(dict(row_key=key(check.model_dump()),**check.model_dump(),recomputed_value=actual,difference=diff,decision='not_computable' if diff is None else 'within_tolerance' if abs(diff)<=check.tolerance else 'difference',reason=None if diff is not None else 'sample_quantity_missing'))
    return dict(config=config,source=source,audit=audit,technical=summaries,samples=normalized,calibration=calibration,original_checks=checks,cells=cells_count)

def validate_qpcr_design(config,sources):
    config=QpcrConfig.model_validate(config);reasons=[];units=[];warnings=[];data=None
    if config.quantification=='efficiency':
        warnings.extend('效率合理性提示：'+assay+' 的扩增因子 E='+str(e.factor)+' 大于2；原测定值与来源依据均保留，不截断，需结合实验条件复核。' for assay,e in config.efficiencies.items() if e.factor>2)
    try:data=prepare_qpcr(config,sources)
    except ValueError as exc:reasons.append(DesignReason(code='qpcr_input_invalid',message=str(exc)[:4000]))
    if data:
        inference_strata=['within_plate_pairs'] if config.paired_plate_policy=='within_plate_differences' else sorted({r['stratum'] for r in data['samples']})
        for stratum in inference_strata:
            for contrast in config.contrasts:
                groups=[[r for r in data['samples'] if (stratum=='within_plate_pairs' or r['stratum']==stratum) and r['condition']==condition and r['target_id']==config.targets[0]] for condition in (contrast.numerator,contrast.denominator)]
                sets=[{r['biological_unit_id'] for r in group} for group in groups]
                pairs=[{r['pair_id'] for r in group} for group in groups] if config.design=='paired' else [set(),set()]
                if not all(groups):warnings.append('No samples for '+stratum+'/'+contrast.contrast_id+'; tests remain NA in the fixed family.')
                if config.design=='independent' and sets[0]&sets[1]:reasons.append(DesignReason(code='qpcr_nonindependent_groups',message='同一生物学单位出现在独立比较两组；请使用完整配对设计。',contrast_id=contrast.contrast_id))
                if config.design=='paired' and pairs[0]!=pairs[1]:reasons.append(DesignReason(code='qpcr_incomplete_pairs',message='预设两组缺少完整配对；必须修正设计或显式记录排除。',contrast_id=contrast.contrast_id))
                if config.paired_plate_policy=='within_plate_differences':
                    plate_maps=[defaultdict(set),defaultdict(set)]
                    for side,group in enumerate(groups):
                        for row in group:plate_maps[side][row['pair_id']].add(row['plate_id'])
                    if any(len(plate_maps[0][pair])!=1 or plate_maps[0][pair]!=plate_maps[1][pair] for pair in pairs[0]|pairs[1]):reasons.append(DesignReason(code='qpcr_pair_crosses_plate',message='合并同板配对差要求每一对的两条件均在同一板且每条件只对应一份样本。',contrast_id=contrast.contrast_id))
                units.append(dict(contrast_id=contrast.contrast_id,stratum=stratum,observation_level='sample',n_numerator=len(groups[0]),n_denominator=len(groups[1]),biological_units_numerator=len(sets[0]),biological_units_denominator=len(sets[1]),complete_pairs=len(pairs[0]&pairs[1])))
        if config.cross_plate=='separate' and len({r['stratum'] for r in data['samples']})>1:warnings.append('逐板相对定量；仅显式确认的同板配对差可合并检验，不合并 Cq 或宣称跨板校准。' if config.paired_plate_policy=='within_plate_differences' else '跨板可比依据未确认：逐板定量与检验，不生成跨板合并结论。')
        if any(r['sd_warning'] for r in data['technical']):warnings.append('技术孔 SD 超过预设阈值，仅提示；未自动删除异常孔。')
        if any(r['reason'] for r in data['samples']):warnings.append('存在内参/校准/检测缺失；受影响样本保留 NA 与原因。')
    return QpcrPreview(executable=not reasons,blocking_reasons=reasons,actual_units=units,family=config.family_contrast_ids,warnings=warnings,
        resource_estimate=ResourceEstimate(observations=len(data['audit']) if data else 0,features=len(config.targets),contrasts=len(config.contrasts),estimated_working_bytes=data['cells']*256 if data else 0))
