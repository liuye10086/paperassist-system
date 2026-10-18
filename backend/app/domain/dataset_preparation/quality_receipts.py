"""Verify frozen receipt evidence without regenerating historical profiles/receipts."""
from collections import Counter,defaultdict
from decimal import Decimal
from app.adapters.task_store import source_conflict
from app.domain.dataset_preparation.quality_transform import active_rows,missing

def verify_frozen_receipt(base,obj,manifest):
    if (manifest.root_source!=obj.parent_source or manifest.base_source!=obj.base_source or manifest.recipe!=obj.recipe or manifest.summary!=obj.summary
            or obj.sheet.data_range!=base.sheet.data_range or obj.sheet.fields!=base.sheet.fields
            or (obj.sheet.index,obj.sheet.name)!=(base.sheet.index,base.sheet.name)):
        raise source_conflict()
    entries=manifest.entries; order={'manual_exclusion':0,'cell_change':1,'duplicate_exclusion':2}
    if entries!=sorted(entries,key=lambda e:(order[e.operation],e.row,e.column or 0)):
        raise source_conflict()
    manual=[e for e in entries if e.operation=='manual_exclusion']
    changes=[e for e in entries if e.operation=='cell_change']
    duplicates=[e for e in entries if e.operation=='duplicate_exclusion']
    if {e.row:e.reason for e in manual}!={e.row:e.reason for e in obj.recipe.manual_exclusions}:
        raise source_conflict()
    active=set(active_rows(base.sheet)); manual_rows={e.row for e in manual}; duplicate_rows={e.row for e in duplicates}
    removed=manual_rows|duplicate_rows
    if (not removed.issubset(active) or manual_rows & duplicate_rows or obj.sheet.active_source_rows!=sorted(active-removed)
            or duplicates and obj.recipe.duplicate_policy!='exact'):
        raise source_conflict()
    cells={(c.row,c.column):c.model_copy(deep=True) for c in base.sheet.cells if c.row not in manual_rows}
    fields={f.column:f for f in obj.recipe.fields}
    for e in changes:
        cell=cells.get((e.row,e.column))
        if cell is None or e.before!=dict(kind=cell.kind,value=cell.value) or cell.kind!='text' or e.final_retained!=(e.row not in removed):
            raise source_conflict()
        value=cell.value; field=fields[e.column]; operations=[]; kind='text'
        if field.trim_text and value.strip()!=value: value=value.strip(); operations.append('trim_text')
        if value in field.missing_markers: kind='blank'; value=None; operations.append('missing_marker')
        if e.operations!=operations or e.after!=dict(kind=kind,value=value): raise source_conflict()
        cell.kind=kind; cell.value=value
    signatures=defaultdict(list)
    for cell in cells.values():
        if not missing(cell): signatures[cell.row].append((cell.column,cell.kind,Decimal(cell.value) if cell.kind=='number' else cell.value))
    for e in duplicates:
        if e.retained_row not in active-removed or not signatures[e.row] or signatures[e.row]!=signatures[e.retained_row]:
            raise source_conflict()
    expected=[c for c in cells.values() if c.row not in duplicate_rows]
    if expected!=obj.sheet.cells: raise source_conflict()
    summary=obj.summary
    counts=(len(manual),len(duplicates),len(changes),sum(c.final_retained for c in changes),sum(not c.final_retained for c in changes),
        len({c.row for c in changes}),sum('trim_text' in c.operations for c in changes),sum('missing_marker' in c.operations for c in changes))
    if counts!=(summary.manual_excluded_row_count,summary.duplicate_excluded_row_count,summary.changed_cell_count,
        summary.retained_changed_cell_count,summary.excluded_changed_cell_count,summary.changed_row_count,summary.trimmed_cell_count,summary.missing_marker_cell_count):
        raise source_conflict()
