"""Finite predicates over parent active source rows; FALSE wins over UNKNOWN."""
from decimal import Decimal
from openpyxl.utils.cell import get_column_letter
from app.core.exceptions import StorageError
from app.domain.datasets.contracts import rectangle
from app.domain.dataset_preparation.quality_transform import active_rows, missing
from app.domain.dataset_preparation.quality_contracts import PreparedSheetV2
from app.domain.dataset_preparation.filter_contracts import FilterRecipe, FilterSummary, FilterImpact, FilterEvaluation, ConditionCounts

def validate_filter_recipe(sheet,recipe):
    try:
        recipe=FilterRecipe.model_validate(recipe.model_dump() if isinstance(recipe,FilterRecipe) else recipe)
        fields={f.column:f for f in sheet.fields}
        for condition in recipe.conditions:
            if condition.column not in fields:raise ValueError('Unknown field')
            if condition.kind=='number' and fields[condition.column].unit.status=='unconfirmed' and not recipe.unit_acknowledged:
                raise ValueError('Unknown units require explicit acknowledgement; no conversion is performed')
            for cell in sheet.cells:
                if cell.column!=condition.column:continue
                if cell.kind in ('formula','error'):raise ValueError('Formula/error field must be resolved')
                if not missing(cell) and condition.kind!='missing' and cell.kind!=condition.kind:
                    raise ValueError('Nonmissing field type does not match predicate')
        return recipe
    except (ValueError,TypeError) as exc:
        raise StorageError('preparation_invalid','筛选字段、类型或单位尚未明确；请先处理公式、错误及不兼容值。',422) from exc

def evaluate(cell,condition):
    absent=cell is None or missing(cell)
    op=condition.operator
    if op=='is_missing':return 'true' if absent else 'false'
    if op=='is_not_missing':return 'false' if absent else 'true'
    if absent:return 'unknown'
    value=Decimal(cell.value) if condition.kind=='number' else cell.value
    operand=Decimal(condition.value) if condition.kind=='number' and condition.value is not None else condition.value
    if op=='between':result=Decimal(condition.lower)<=value<=Decimal(condition.upper)
    elif op=='in':result=value in condition.values
    elif op=='eq':result=value==operand
    elif op=='ne':result=value!=operand
    elif op=='gt':result=value>operand
    elif op=='ge':result=value>=operand
    elif op=='lt':result=value<operand
    else:result=value<=operand
    return 'true' if result else 'false'

def prepare_filter(base_obj,base_source,recipe):
    from app.domain.dataset_preparation.derivation_contracts import DerivationManifest
    from app.domain.analysis_sources import source_dict
    recipe=validate_filter_recipe(base_obj.sheet,recipe)
    source=source_dict(base_source)
    if source['kind']!='prepared_dataset_version' or source['parent_dataset_id']!=base_obj.parent_source.dataset_id:
        raise StorageError('source_conflict','筛选直接父版本不一致。',409)
    active=active_rows(base_obj.sheet); cells={(c.row,c.column):c for c in base_obj.sheet.cells}
    entries=[];retained=[];counts=[dict(true_count=0,false_count=0,unknown_count=0) for _ in recipe.conditions]
    for row in active:
        evaluations=[]
        for index,condition in enumerate(recipe.conditions):
            status=evaluate(cells.get((row,condition.column)),condition)
            counts[index][status+'_count']+=1
            evaluations.append(FilterEvaluation(condition_index=index,coordinate=f'{get_column_letter(condition.column)}{row}',status=status))
        failed=[e.condition_index for e in evaluations if e.status=='false'];unknown=[e.condition_index for e in evaluations if e.status=='unknown']
        classification='mismatch' if failed else 'unknown' if unknown else 'retained'
        if classification=='retained':retained.append(row)
        entries.append(FilterImpact(row=row,classification=classification,failed_conditions=failed,unknown_conditions=unknown,evaluations=evaluations))
    retained_set=set(retained)
    sheet=PreparedSheetV2.model_validate({**base_obj.sheet.model_dump(),'active_source_rows':retained,'cells':[c.model_dump() for c in base_obj.sheet.cells if c.row in retained_set]})
    start,end=rectangle(sheet.data_range);root=end[0]-start[0]+1
    summary=FilterSummary(root_record_count=root,base_record_count=len(active),retained_record_count=len(retained),
        inherited_excluded_row_count=root-len(active),mismatch_excluded_row_count=sum(e.classification=='mismatch' for e in entries),
        unknown_excluded_row_count=sum(e.classification=='unknown' for e in entries),cumulative_excluded_row_count=root-len(retained),impact_count=len(entries),
        condition_counts=[ConditionCounts(condition_index=i,**c) for i,c in enumerate(counts)])
    manifest=DerivationManifest(operation='population_filter',root_source=base_obj.parent_source,base_source=source,recipe=recipe,summary=summary,entries=entries)
    return sheet,summary,manifest
