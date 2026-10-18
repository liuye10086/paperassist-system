"""Deterministic manual exclusion → text rules → typed all-field deduplication."""
from collections import Counter, defaultdict
from decimal import Decimal
from app.core.exceptions import StorageError
from app.domain.datasets.contracts import rectangle
from app.domain.analysis_sources import source_dict
from app.domain.dataset_preparation.quality_contracts import (QualityRecipe, PreparedSheetV2,
    QualityOverview, QualitySummary, QualityManifest, QualityImpact, PreparedDatasetObjectV2)

def active_rows(sheet):
    rows=getattr(sheet,'active_source_rows',None)
    start,end=rectangle(sheet.data_range)
    return list(rows) if rows is not None else list(range(start[0],end[0]+1))

def missing(cell):
    return cell.kind=='blank' or cell.kind=='text' and not cell.value.strip()

def duplicate_groups(sheet):
    rows=defaultdict(list)
    for c in sheet.cells:
        if not missing(c):
            rows[c.row].append((c.column,c.kind,Decimal(c.value) if c.kind=='number' else c.value))
    groups=defaultdict(list)
    for row,values in rows.items():
        groups[tuple(values)].append(row)
    return sorted((sorted(g) for g in groups.values() if len(g)>1),key=lambda g:g[0])

def overview(sheet):
    from app.domain.dataset_profile.scan import numeric_profile
    active=active_rows(sheet)
    rows=Counter(c.row for c in sheet.cells if not missing(c))
    groups=duplicate_groups(sheet)
    numbers=defaultdict(list)
    for c in sheet.cells:
        if c.kind=='number': numbers[c.column].append(c)
    return QualityOverview(record_count=len(active),missing_cell_count=len(active)*len(sheet.fields)-sum(rows.values()),
        missing_row_count=sum(rows[r]<len(sheet.fields) for r in active),blank_row_count=sum(rows[r]==0 for r in active),
        duplicate_group_count=len(groups),duplicate_member_count=sum(map(len,groups)),
        duplicate_extra_row_count=sum(len(g)-1 for g in groups),
        outlier_candidate_count=sum(len(numeric_profile(cells)[1]) for cells in numbers.values()))

def validate_quality_recipe(sheet,recipe):
    try:
        recipe=QualityRecipe.model_validate(recipe.model_dump() if isinstance(recipe,QualityRecipe) else recipe)
        active=set(active_rows(sheet))
        if [f.column for f in recipe.fields] != [f.column for f in sheet.fields] or any(e.row not in active for e in recipe.manual_exclusions):
            raise ValueError('Rules differ from active parent fields or rows')
        return recipe
    except (ValueError,TypeError) as exc:
        raise StorageError('preparation_invalid','质量规则须保留全部字段，排除行须来自当前有效行且填写理由。',422) from exc

def prepare_quality(base_obj,base_source,recipe,*,manifest_factory=QualityManifest):
    recipe=validate_quality_recipe(base_obj.sheet,recipe)
    base_source=source_dict(base_source)
    if base_source['kind']!='prepared_dataset_version' or base_source['parent_dataset_id']!=base_obj.parent_source.dataset_id:
        raise StorageError('source_conflict','质量处理的直接父版本不一致。',409)
    active=active_rows(base_obj.sheet)
    excluded={e.row for e in recipe.manual_exclusions}
    fields={f.column:f for f in recipe.fields}
    impacts=[QualityImpact(row=e.row,operation='manual_exclusion',reason=e.reason,reason_origin='user',final_retained=False)
        for e in sorted(recipe.manual_exclusions,key=lambda e:e.row)]
    cells=[]; changes=[]
    for cell in base_obj.sheet.cells:
        if cell.row in excluded: continue
        effective=cell.model_copy(deep=True); operations=[]; field=fields[cell.column]
        if cell.kind=='text':
            if field.trim_text and effective.value.strip()!=effective.value:
                effective.value=effective.value.strip(); operations.append('trim_text')
            if effective.value in field.missing_markers:
                effective.kind='blank'; effective.value=None; operations.append('missing_marker')
        cells.append(effective)
        if operations:
            changes.append(QualityImpact(row=cell.row,column=cell.column,coordinate=cell.coordinate,operation='cell_change',reason_origin='rule',
                before=dict(kind=cell.kind,value=cell.value),after=dict(kind=effective.kind,value=effective.value),operations=operations,final_retained=True))
    sheet=PreparedSheetV2(**{**base_obj.sheet.model_dump(), 'cells':[c.model_dump() for c in cells],
        'active_source_rows':[r for r in active if r not in excluded]})
    duplicates=[]
    if recipe.duplicate_policy=='exact':
        for group in duplicate_groups(sheet):
            duplicates.extend(QualityImpact(row=row,operation='duplicate_exclusion',reason='exact_duplicate',reason_origin='rule',retained_row=group[0],final_retained=False) for row in group[1:])
    duplicates.sort(key=lambda e:e.row)
    duplicate_rows={e.row for e in duplicates}
    for change in changes: change.final_retained=change.row not in duplicate_rows
    sheet=PreparedSheetV2(**{**sheet.model_dump(), 'cells':[c.model_dump() for c in sheet.cells if c.row not in duplicate_rows],
        'active_source_rows':[r for r in sheet.active_source_rows if r not in duplicate_rows]})
    impacts.extend(changes); impacts.extend(duplicates)
    start,end=rectangle(sheet.data_range); root_count=end[0]-start[0]+1
    summary=QualitySummary(root_record_count=root_count,base_record_count=len(active),retained_record_count=sheet.row_count,
        inherited_excluded_row_count=root_count-len(active),manual_excluded_row_count=len(excluded),duplicate_excluded_row_count=len(duplicates),
        cumulative_excluded_row_count=root_count-sheet.row_count,changed_cell_count=len(changes),retained_changed_cell_count=sum(c.final_retained for c in changes),
        excluded_changed_cell_count=sum(not c.final_retained for c in changes),changed_row_count=len({c.row for c in changes}),
        trimmed_cell_count=sum('trim_text' in c.operations for c in changes),missing_marker_cell_count=sum('missing_marker' in c.operations for c in changes),
        impact_count=len(impacts),before_quality=overview(base_obj.sheet),after_quality=overview(sheet))
    manifest=manifest_factory(root_source=base_obj.parent_source,base_source=base_source,recipe=recipe,summary=summary,entries=impacts)
    return sheet,summary,manifest

def build_quality_object(base_obj,base_source,recipe,sheet,summary,manifest_ref):
    return PreparedDatasetObjectV2(parent_source=base_obj.parent_source,base_source=base_source,recipe=recipe,sheet=sheet,summary=summary,manifest=manifest_ref)
