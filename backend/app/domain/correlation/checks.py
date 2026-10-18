"""Whole selected-field checks and original-row complete-record audit."""
from decimal import Decimal
from fastapi import HTTPException
from openpyxl.utils.cell import column_index_from_string, get_column_letter
from app.core.exceptions import StorageError
from app.domain.dataset_analysis import binary64
from app.domain.dataset_profile.scan import missing
from app.domain.analysis_plan.profile import PlanProfileScan as ProfileScan
from app.domain.datasets.contracts import rectangle
from app.domain.dataset_rows import source_rows


def selected_records(sheet, selection):
    fields = {get_column_letter(f.column): f for f in sheet.fields}
    if selection.sheet_name != sheet.name:
        raise StorageError('sheet_not_found', '工作表与冻结数据不一致。', 422)
    if any(c not in fields for c in selection.columns):
        raise StorageError('invalid_column', '所选字段不存在。', 422)
    cells = {(c.row, c.column): c for c in sheet.cells}
    start, end = rectangle(sheet.data_range)
    rows, included, excluded = [], [], []
    for row in source_rows(sheet):
        values, absent = [], []
        for letter in selection.columns:
            cell = cells.get((row, column_index_from_string(letter)))
            if missing(cell):
                absent.append(f'{letter}{row}')
            elif cell.kind != 'number':
                raise StorageError('numeric_type', '相关分析字段须全部为实际数值或缺失值。', 422)
            else:
                try:
                    values.append(binary64(Decimal(cell.value), letter, row, cell.value))
                except HTTPException as exc:
                    raise StorageError('numeric_precision', '选定字段含无法可靠表示的数值。', 422) from exc
        if absent:
            excluded.append(dict(row=row, coordinates=absent, reason='selected_missing'))
        else:
            rows.append(values); included.append(row)
    variables = [dict(column=c, name=fields[c].name, unit=selection.units[c]) for c in selection.columns]
    audit = dict(included_rows=included, excluded_rows=excluded, missing_policy='complete_cases')
    return rows, variables, audit


def build_correlation_check(sheet, selection, research):
    from app.domain.analysis_plan.contracts import ModernPlanCheck
    from app.domain.analysis_plan.research import missing_research
    from app.domain.correlation.kernel import CorrelationError
    from app.domain.fixed_statistics import correlate_bounded as compute_correlation
    issues, selected = [], []
    def issue(code, field, count, message, coordinates=(), resolution=None):
        issues.append(dict(id=f'{code}:{field or "all"}', code=code, field=field, count=count,
            severity='warning' if resolution else 'blocking', message=message,
            coordinates=list(coordinates)[:5], allowed_resolutions=[resolution] if resolution else []))
    profile = ProfileScan(sheet,selected_columns=selection.columns)
    lookup = {f['letter']: f for f in profile.fields}
    for letter in selection.columns:
        field = lookup.get(letter)
        if field is None: continue
        numeric = field['numeric'] or {}; unit = field['unit']; label = selection.units[letter]
        selected.append(dict(letter=letter, name=field['name'], type_counts=field['type_counts'],
            missing_count=field['missing_count'], non_missing_count=field['non_missing_count'],
            prepared_unit=unit, declared_unit=dict(status='label' if label else 'unknown', value=label or None),
            observed_min=numeric.get('min'), observed_max=numeric.get('max')))
        if unit['status']=='confirmed' and unit['value'] != label:
            issue('unit_conflict', letter, 1, '所声明单位与整理数据不同，不会自动换算。')
        elif unit['status']=='unconfirmed':
            issue('unit_unconfirmed', letter, 1, '请确认单位仅为声明，不转换数值。', resolution='declare_label' if label else 'unknown')
        count, items = profile.issues('outlier', field['column'], 1)
        if count:
            issue('outlier', letter, count, '异常候选保持纳入；不自动删除。', [i['coordinate'] for i in items], 'retain')
    n = excluded_count = 0
    try:
        rows, _, audit = selected_records(sheet, selection)
        n = len(rows); excluded_count = len(audit['excluded_rows'])
        # Matrix computation validates numeric conditions without inferential permutations.
        compute_correlation(rows, method=selection.method, mode='matrix')
        if n < 10: issue('small_sample', None, n, '样本量较小，结果可能不稳定。', resolution='accept_partial_metrics')
        if excluded_count:
            issue('selected_missing', None, excluded_count, '缺失行按共同完整记录规则排除，原数据保留。',
                [c for item in audit['excluded_rows'] for c in item['coordinates']], 'exclude_selected_missing')
    except (StorageError, CorrelationError) as exc:
        issue(exc.code, None, n, str(getattr(exc, 'message', '相关字段检查未通过。')))
    missing_fields = missing_research(research)
    if research['observation_structure'] != 'independent' and 'observation_structure' not in missing_fields:
        missing_fields.append('observation_structure')
    assumptions = selection.assumptions
    if not assumptions.independent_observations: missing_fields.append('independent_observations')
    if assumptions.relationship_form != ('linear' if selection.method=='pearson' else 'monotonic'):
        missing_fields.append('relationship_form')
    if selection.mode=='pair' and not assumptions.inference_assumptions_confirmed:
        missing_fields.append('inference_assumptions_confirmed')
    blocking = any(i['severity']=='blocking' for i in issues)
    check = dict(ready=not blocking, row_count=sheet.row_count, valid_count=n, excluded_count=excluded_count,
        groups=[], issues=[i['message'] for i in issues if i['severity']=='blocking'],
        warnings=[i['message'] for i in issues if i['severity']=='warning'])
    return ModernPlanCheck(rules_version='analysis_plan_rules_v3', data_range=sheet.data_range,
        row_count=sheet.row_count, selected_fields=selected, selection_check=check, issues=issues,
        research_missing=missing_fields, limitations=['相关不代表因果；前提由用户声明，不是程序证明。',
        ('统计阶段采用当前整理保留行的共同完整记录，不新增填补、去重或自动剔除。' if getattr(sheet,'active_source_rows',None) is not None else '共同完整记录，不填补、不去重、不自动剔除异常值。'), '探索矩阵不做多重假设检验，不提供P值或星号。'
        if selection.mode=='matrix' else '双侧推断；小样本结果可能不稳定。']).model_dump(mode='json')
