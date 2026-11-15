"""Readable labels for complete selected statistics without changing numeric values."""
import csv
import hashlib
import io
import json

from app.adapters.research_method_text import reader_internal_field, reader_label
from app.domain.research_results.statistics_projection import metric_unit

from .narrative import METHODS, clean, localized

SECTIONS = {
    'statistics': ('统计结果', 'Statistics'), 'overall': ('总体摘要', 'Overall summary'), 'groups': ('分组结果', 'Groups'),
    'check': ('质量与可用性', 'Quality checks'), 'selection': ('分析选项', 'Analysis settings'),
    'variables': ('变量和单位', 'Variables and units'),
    'row_audit': ('纳入排除明细', 'Record audit'), 'role_records': ('记录角色', 'Record roles'),
    'frozen_role_audit': ('角色纳入明细', 'Role audit'), 'frozen_plot': ('原始绘图取值', 'Saved plot data'),
}

LABELS = {
    'n': ('记录数', 'Record count'), 'original_statistical_n': ('原统计记录数', 'Original analysis count'),
    'valid_n': ('有效计数', 'Valid count'), 'excluded_n': ('排除计数', 'Excluded count'),
    'mean': ('均值', 'Mean'), 'std': ('样本标准差', 'Sample SD'), 'variance': ('方差', 'Variance'),
    'median': ('中位数', 'Median'), 'min': ('最小值', 'Minimum'), 'max': ('最大值', 'Maximum'),
    'q1': ('第一四分位数', 'First quartile'), 'q3': ('第三四分位数', 'Third quartile'), 'iqr': ('四分位距', 'Interquartile range'),
    'lower_whisker': ('下须端', 'Lower whisker'), 'upper_whisker': ('上须端', 'Upper whisker'),
    'row_count': ('来源记录数', 'Source records'), 'valid_count': ('有效计数', 'Valid count'),
    'excluded_count': ('排除计数', 'Excluded count'), 'missing_count': ('缺失计数', 'Missing count'),
    'statistic': ('检验统计量', 'Test statistic'), 'p_value': ('P 值', 'P value'), 'p_adjusted': ('校正 P 值', 'Adjusted P value'),
    'coefficient': ('相关系数', 'Correlation coefficient'), 'matrix': ('相关矩阵', 'Correlation matrix'),
    'bootstrap': ('自助抽样', 'Bootstrap'), 'confidence_interval': ('置信区间', 'Confidence interval'),
    'error_bars': ('误差线', 'Error bars'), 'r_squared': ('决定系数', 'R-squared'), 'residual_sd': ('残差标准差', 'Residual SD'),
    'sample_sizes': ('各组计数', 'Group counts'), 'effects': ('效应估计', 'Effect estimates'), 'estimate': ('估计值', 'Estimate'),
    'coefficients': ('回归项', 'Regression terms'), 'beta': ('回归系数', 'Regression coefficient'),
    'se': ('标准误', 'Standard error'), 'ci_low': ('置信下限', 'Confidence lower limit'), 'ci_high': ('置信上限', 'Confidence upper limit'),
    'ci_reason': ('区间可用性说明', 'Interval availability'), 'low': ('下限', 'Lower limit'), 'high': ('上限', 'Upper limit'),
    'or_value': ('比值比', 'Odds ratio'), 'or_ci_low': ('比值比下限', 'Odds ratio lower limit'), 'or_ci_high': ('比值比上限', 'Odds ratio upper limit'),
    'r_squared_adj': ('调整后决定系数', 'Adjusted R-squared'), 'adjusted_r_squared': ('调整后决定系数', 'Adjusted R-squared'),
    'covariance': ('协方差矩阵', 'Covariance matrix'), 'diagnostics': ('模型诊断', 'Model diagnostics'),
    'residuals': ('残差', 'Residuals'), 'fitted': ('拟合值', 'Fitted values'), 'leverage': ('杠杆值', 'Leverage'),
    'cooks_distance': ('Cook 距离', 'Cook distance'), 'df_residual': ('残差自由度', 'Residual degrees of freedom'),
    'auc': ('曲线下面积', 'Area under the curve'), 'threshold': ('阈值', 'Threshold'),
    'threshold_kind': ('阈值性质', 'Threshold type'), 'fpr': ('假阳性率', 'False positive rate'),
    'tpr': ('真阳性率', 'True positive rate'), 'sensitivity': ('灵敏度', 'Sensitivity'), 'specificity': ('特异度', 'Specificity'),
    'positive_n': ('阳性计数', 'Positive count'), 'negative_n': ('阴性计数', 'Negative count'),
    'survival': ('生存概率', 'Survival probability'), 'time': ('时间', 'Time'), 'n_at_risk': ('在险计数', 'Number at risk'),
    'event_n': ('事件计数', 'Event count'), 'n_event': ('事件计数', 'Events'), 'n_censored': ('删失计数', 'Censored'),
    'censored_n': ('删失计数', 'Censored count'), 'risk_table': ('在险表', 'Risk table'),
    'greenwood_variance': ('Greenwood 方差', 'Greenwood variance'), 'max_time': ('最大随访时间', 'Maximum follow-up'),
    'group': ('分组', 'Group'), 'group_rows': ('各组来源行', 'Source rows by group'),
    'series': ('数据系列', 'Series'), 'points': ('数据点', 'Points'), 'x': ('横轴', 'Horizontal axis'), 'y': ('纵轴', 'Vertical axis'),
    'total': ('总计', 'Total'), 'denominator': ('分母', 'Denominator'), 'proportion': ('比例', 'Proportion'),
    'row': ('原表行号', 'Original row number'), 'rows': ('原表记录', 'Source records'),
    'included_rows': ('纳入行', 'Included rows'), 'excluded_rows': ('排除行', 'Excluded rows'),
    'origin': ('明细来源', 'Audit source'),
    'warnings': ('提醒', 'Warnings'), 'issues': ('需核查事项', 'Items to check'), 'audit': ('纳入排除核对', 'Inclusion review'),
    'reason': ('原因', 'Reason'), 'method': ('方法', 'Method'), 'design': ('比较设计', 'Comparison design'),
    'missing_policy': ('缺失处理', 'Missing-data handling'), 'complete_cases': ('完整记录分析', 'Complete records'),
    'complete_pairs': ('完整配对分析', 'Complete pairs'), 'assumptions': ('方法假设', 'Method assumptions'),
    'independent': ('独立组', 'Independent groups'), 'paired': ('配对', 'Paired'), 'multiple': ('多个组', 'Multiple groups'),
    'higher_is_positive': ('较高值判为阳性', 'Higher values indicate positive'),
    'lower_is_positive': ('较低值判为阳性', 'Lower values indicate positive'),
    'above_all': ('高于所有分数', 'Above all scores'), 'below_all': ('低于所有分数', 'Below all scores'),
    'boundary_survival_interval_unavailable': ('生存概率位于边界，区间无法计算', 'Survival is at a boundary, so the interval is unavailable'),
    'evaluation_role_not_independent': ('评估资料缺少独立验证条件', 'Evaluation data do not meet independent validation conditions'),
    'insufficient_class_size': ('阳性或阴性组计数不足', 'Too few records in the positive or negative group'),
    'degenerate_delong_variance': ('DeLong 方差退化', 'Degenerate DeLong variance'),
    'not_reached': ('尚未达到中位生存', 'Median survival not reached'),
    'selected_missing': ('选用字段缺失', 'Missing selected fields'),
    'not_requested': ('未要求计算', 'Calculation not requested'),
    'none': ('无', 'None'),
    'count': ('计数', 'Count'), 'ready': ('可用于分析', 'Ready for analysis'), 'unit': ('单位', 'Unit'),
    'group_column': ('分组列', 'Grouping column'), 'numeric_column': ('测量列', 'Measurement column'),
    'sheet_name': ('工作表', 'Worksheet'), 'task_type': ('分析类型', 'Analysis type'),
    'descriptive_boxplot': ('描述统计与箱线图', 'Descriptive statistics and boxplot'),
    'group_comparison': ('组间比较', 'Group comparison'), 'correlation': ('相关分析', 'Correlation analysis'),
    'regression': ('回归分析', 'Regression'), 'roc': ('ROC 分析', 'ROC analysis'),
    'exclude_selected_missing': ('排除选用字段缺失的记录', 'Exclude records missing selected fields'),
    'question': ('研究问题', 'Research question'), 'population': ('来源人群', 'Source population'),
    'study_design': ('研究设计', 'Study design'), 'observation_unit': ('观测单位', 'Observation unit'),
    'observation_structure': ('观测关系', 'Observation structure'), 'repeated': ('重复观测', 'Repeated observations'),
    'relationship_description': ('观测关系说明', 'Relationship between observations'),
}
FIELD_VALUE_LABELS = {
    ('task_type', 'survival'): ('生存分析', 'Survival analysis'),
    ('origin', 'reconstructed_from_frozen_source_not_a_new_test'): (
        '基于固定来源重建纳入明细，未执行新检验。',
        'Inclusion details were reconstructed from the frozen source. No new test was performed.',
    ),
}
SETTING_TERMS = {'method', 'reason', 'ci_reason', 'kind', 'missing_policy', 'design', 'mode',
                 'threshold_kind', 'direction', 'policy', 'posthoc', 'observation_structure', 'task_type'}
TECHNICAL_FIELDS = {'dataset_id', 'setup_revision', 'engine', 'input_sha256', 'source_sha256', '_material'}


def label(value, language):
    names = LABELS.get(value) or METHODS.get(value)
    return localized(language, *names) if names else reader_label(value, language)


def labeled_values(data, language, path='', labels=(), field='', parent=None):
    if isinstance(data, dict):
        for key, value in sorted(data.items()):
            if key not in TECHNICAL_FIELDS and not reader_internal_field(key):
                next_path = f'{path}.{key}' if path else key
                yield from labeled_values(value, language, next_path, (*labels, label(key, language)), key, data)
    elif isinstance(data, list):
        for index, value in enumerate(data):
            item = localized(language, f'第 {index + 1} 项', f'Item {index + 1}')
            if isinstance(value, dict):
                named = next((value[key] for key in ('label', 'name', 'term', 'group') if isinstance(value.get(key), str)), None)
                item = clean(named) or item
            yield from labeled_values(value, language, f'{path}[{index}]', (*labels, item), field, data)
    else:
        yield path, ' · '.join(labels), field, parent, data


def table(name, data, language, source_id, lookup_unit):
    columns = ['Measure or item', 'Value', 'Unit', 'Availability'] if language == 'en' else ['指标或项目', '数值或内容', '单位', '可用性']
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
    writer.writerow(columns)
    count = 0
    for path, measure, field, parent, value in labeled_values(data, language):
        availability = ''
        if value is None:
            reason = (parent.get('ci_reason') or parent.get('median_reason') or parent.get('reason')) if isinstance(parent, dict) else None
            availability = label(reason, language) if isinstance(reason, str) and reason else localized(language, '未提供或不适用', 'Unavailable or not applicable')
            value = 'NA'
        elif type(value) is bool:
            value = localized(language, '是', 'Yes') if value else localized(language, '否', 'No')
        elif type(value) in (int, float):
            value = json.dumps(value, allow_nan=False)
        elif (field, value) in FIELD_VALUE_LABELS:
            value = localized(language, *FIELD_VALUE_LABELS[field, value])
        elif field in SETTING_TERMS and (value in LABELS or value in METHODS):
            value = label(value, language)
        elif value == '':
            availability = localized(language, '空文本', 'Empty text')
        writer.writerow((measure, value, lookup_unit(path), availability))
        count += 1
    raw = stream.getvalue().encode('utf-8')
    metadata = dict(key=name, columns=columns, expected_rows=count, source=dict(source_kind='analysis_run', source_id=source_id),
                    sha256=hashlib.sha256(raw).hexdigest(), provenance='system_computed')
    return metadata, raw


def reader_metric_unit(result, section, path):
    selection = result['selection']
    if section == 'statistics' and selection.get('method') == 'ols':
        if path == 'residual_sd' or path.startswith(('diagnostics.residuals[', 'diagnostics.fitted[')):
            return selection.get('outcome_unit', '')
    return metric_unit(result, section + '.' + path)


def result_tables(source, position, language):
    result = source.content['result']
    for section, names in SECTIONS.items():
        data = result.get(section, source.content.get(section))
        if data is None:
            continue
        name = localized(language, f'分析{position:02d} {names[0]}', f'Run {position:02d} {names[1]}')
        yield table(name, data, language, source.source_id, lambda path: reader_metric_unit(result, section, path))
    research = result.get('analysis_context', {}).get('plan', {}).get('research_request', {})
    if research:
        fields = ('question', 'population', 'study_design', 'observation_unit', 'observation_structure', 'relationship_description')
        declaration = {field: clean(research.get(field)) or None for field in fields}
        name = localized(language, f'分析{position:02d} 研究说明', f'Run {position:02d} Study design')
        yield table(name, declaration, language, source.source_id, lambda _: '')


def projection_table(item, position, language):
    axes = item['figure'].get('presentation', {}).get('axes') or {}
    name = localized(language, f'图{position:02d} 已确认投影', f'Fig {position:02d} Saved projection')
    return table(name, item['projection']['result'], language, item['result']['id'],
                 lambda path: axes.get(path.rsplit('.', 1)[-1], {}).get('unit', ''))
