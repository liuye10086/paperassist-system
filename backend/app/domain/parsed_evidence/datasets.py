"""Bounded rows preserving original lexical values and accepted recipe units."""
from openpyxl.utils.cell import get_column_letter
from app.domain.dataset_rows import source_rows
from app.domain.parsed_evidence.contracts import Item, Location, Value, Unit, EvidenceCell, Scope, response


def project_sheet(sheet, origin, parser, page, *, prepared=None, raw_sheet=None):
    def loc(row=None, column=None, coordinate=None):
        return Location(sheet_index=sheet.index, sheet_name=sheet.name, row=row, column=column, coordinate=coordinate)
    fields = sheet.fields
    items = []
    for field in fields:
        header_row = getattr(prepared.recipe, "header_row", None) if prepared else 1
        items.append(Item(id=f'field:{field.column}', kind='field',
            location=loc(header_row, field.column, f'{get_column_letter(field.column)}{header_row}' if header_row is not None else None),
            value=Value(kind='field', typed=field.name if prepared else field.header_value,
                unit=Unit(**field.unit.model_dump()))))
    first, last = (1, sheet.row_count)
    if prepared:
        from app.domain.datasets.contracts import rectangle
        start, end = rectangle(sheet.data_range)
        first, last = start[0], end[0]
    grouped = {}
    raw = {(c.row, c.column): c for c in (raw_sheet.cells if raw_sheet else sheet.cells)}
    units = {f.column: Unit(**f.unit.model_dump()) for f in fields}
    for cell in sheet.cells:
        original = raw.get((cell.row,cell.column))
        lexical = original if prepared else cell
        value = Value(kind=cell.kind, typed=cell.value, raw_available=lexical is not None,
            original_typed=lexical.value if lexical else None,
            raw_source_version_id=prepared.parent_source.dataset_id if prepared else origin.version_id,
            raw_type=getattr(lexical,'raw_type',None), raw=getattr(lexical,'raw_value',None),
            number_format=getattr(lexical,'number_format',None), formula=getattr(lexical,'formula',None),
            unit=units[cell.column])
        grouped.setdefault(cell.row, []).append(EvidenceCell(location=loc(cell.row,cell.column,cell.coordinate), value=value))
    for row in source_rows(sheet) if prepared else range(first,last+1):
        items.append(Item(id=f'row:{row}',kind='row',location=loc(row),cells=grouped.get(row,[]),
            uncertainties=['unstored_cells_not_materialized']))
    scope = Scope(kind='sheet',sheet_index=sheet.index,sheet_name=sheet.name,
        stored_range=raw_sheet.stored_range if prepared else sheet.stored_range,
        content_range=raw_sheet.content_range if prepared else sheet.content_range,
        data_range=sheet.data_range if prepared else None)
    warnings = ['stored_counts_not_research_n', 'formula_cache_unverified']
    if prepared:
        warnings += ['prepared_raw_values_from_parent']
    else:
        warnings += list(sheet.warnings)
    return response(origin, 'prepared_xlsx' if prepared else 'xlsx', parser, scope,
        dict(rows=sheet.row_count, cells=len(sheet.cells), fields=len(fields)), items, warnings, page)
