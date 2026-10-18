"""Cloud plotting material from locally revalidated complete observations."""
from copy import deepcopy
import math
from app.core.exceptions import StorageError
from app.domain.artifact_contracts import artifact_language, figure_kind


def build_material(result, rows, *, external=None):
    from app.domain.external_material import contract_labels
    if external is None:
        raise StorageError('task_source_conflict', '相关绘图必须先确认本次外发字段与数值范围。', 409)
    names = contract_labels(result, None, external, 'boxplot')
    variables = [{**variable, 'name':names['field:'+variable['column']],
                  'unit':names['unit:'+variable['column']]} for variable in result['variables']]
    statistics = result['statistics']
    if (not isinstance(rows, list) or len(rows) != statistics['n'] or not 3 <= len(rows) <= 10000
            or any(not isinstance(row, list) or len(row) != len(variables)
                   or any(type(value) not in (int, float) or not math.isfinite(value) for value in row) for row in rows)):
        raise StorageError('result_mismatch', '相关图所用完整记录与已保存统计结果不一致。', 409)
    language, kind = artifact_language(result), figure_kind(result)
    method, mode = statistics['method'], statistics['mode']
    method_name = 'Pearson' if method == 'pearson' else 'Spearman'
    check = result['check']
    def axis(variable):
        unit = variable['unit'] or ('单位未填写' if language == 'zh-CN' else 'unit not specified')
        return f'{variable["name"]} ({unit})'
    if language == 'en':
        title = f'Figure 1. {method_name} ' + ('correlation scatter plot' if mode == 'pair' else 'correlation matrix')
        caption = (f'Figure 1. {method_name} correlation; {check["valid_count"]} complete records; '
            f'{check["excluded_count"]} excluded records. ' +
            ('Each point retains its original row pairing. No regression line or inferential markers are displayed. '
             if mode == 'pair' else 'All variables use the same complete records. Coefficients and common n only; no P values or significance stars. ') +
            'No imputation, deduplication or outlier removal. Correlation does not establish causation.')
    else:
        title = f'图 1. {method_name}' + ('相关散点图' if mode == 'pair' else '相关矩阵热力图')
        caption = (f'图 1. {method_name}相关；纳入 {check["valid_count"]} 行完整记录，排除 {check["excluded_count"]} 行。' +
            ('各点保持原始行对应；不绘制回归拟合线或推断标记。' if mode == 'pair' else
             '全部变量使用同一批完整记录，仅展示相关系数及共同有效 n，不显示 P 值或显著性星号。') +
            '未插补、去重或剔除离群值。相关不等于因果。')
    labels = {'title':title, 'x_label':axis(variables[0]) if mode == 'pair' else '',
              'y_label':axis(variables[1]) if mode == 'pair' else '', 'caption':caption}
    config = {'regression_line':False, 'inference_displayed':False, 'complete_case_basis':'common_rows'}
    if mode == 'matrix': config['color_range'] = [-1.0, 1.0]
    base = {'schema_version':2,'figure_kind':kind,'language':language,'correlation_method':method,
            'mode':mode, **labels, 'variables':variables,'plot_config':config}
    numeric = {'n': statistics['n'], 'coefficient':statistics['coefficient']} if mode == 'pair' else {
        'n':statistics['n'], 'matrix':deepcopy(statistics['matrix'])}
    expected = {**deepcopy(base),'statistics':numeric}
    payload = {key:value for key,value in base.items() if key not in labels}
    payload.update(labels=labels, values=deepcopy(rows))
    return payload, expected
