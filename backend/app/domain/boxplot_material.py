"""Build bounded plotting material from verified local bytes, without cloud I/O."""
from fastapi import HTTPException

from app.adapters.excel import parse_workbook
from app.core.exceptions import StorageError
from app.domain.analysis import AnalysisSelection, SheetScan
from app.domain.boxplot import plot_data
from app.domain.descriptive import summarize


def build_material(result, file_record, content, settings, *, external=None):
    try:
        selection = AnalysisSelection(**result['selection'])
        scan = SheetScan(selection.sheet_name, selection, collect_values=True)
        preview = parse_workbook(content, file_record['filename'], settings, observe_row=scan.observe)
        sheet = next((item for item in preview.sheets if item.name == selection.sheet_name), None)
        if sheet is None:
            raise StorageError('sheet_not_found', '工作表不存在，请重新选择。', 422)
        check = scan.check(scan.profile(sheet))
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        raise StorageError(detail.get('code', 'task_source_conflict'), '绘图输入材料无法通过检查。',
                           exc.status_code) from None
    if not check.ready:
        raise StorageError('invalid_analysis_selection', '绘图所用字段未通过完整记录检查。', 422)
    groups = [{'label': ('TRUE' if label else 'FALSE') if isinstance(label, bool) else str(label),
               'statistics': summarize(data)} for label, data in scan.grouped_values.items()]
    if (check.model_dump() != result['check'] or summarize(scan.values) != result['overall']
            or groups != result['groups']):
        raise StorageError('result_mismatch', '原始数据复算与已保存统计结果不一致。', 409)
    figure = plot_data(result, scan.values, scan.grouped_values)
    if external is None and any(len(value) > 160 for value in [result['numeric_name'], result['group_name'] or '',
                                         *[group['label'] for group in groups]]):
        raise StorageError('plot_label_too_long', '绘图字段或分组名称超过上限。', 422)
    labels = {key: figure[key] for key in ('title', 'x_label', 'y_label', 'caption')}
    metrics = ('n', 'mean', 'std', 'min', 'q1', 'median', 'q3', 'max', 'iqr')
    expected = {'analysis_run_id': result['id'], 'source_sha256': result['source_sha256'], **labels,
        'overall': {key: result['overall'][key] for key in metrics},
        'groups': [{'label': group['label'], 'statistics': {key: group['statistics'][key] for key in metrics}}
                   for group in groups], 'series': figure['series']}
    payload = {'analysis_run_id': result['id'], 'source_sha256': result['source_sha256'], 'labels': labels,
        'values': scan.values, 'groups': [{'label': group['label'], 'values': values}
                                        for group, values in zip(groups, scan.grouped_values.values())]}
    from app.domain.external_material import plot_material
    return plot_material(result, payload, expected, external)
