"""Rebuildable, versioned drawing semantics derived only from frozen materials.

This module does not change numeric outputs or authorize any external processing.
"""
from copy import deepcopy
import re
from app.core.exceptions import StorageError
from app.domain.figure_workbench.contracts import RENDERER

V2_RENDERER = 'openai_figure_workbench_v2'
LATEST_RENDERER = 'openai_figure_workbench_v3'
_PALETTES = {
    'colorblind': ['#0072B2', '#E69F00', '#009E73', '#CC79A7', '#56B4E9', '#D55E00', '#F0E442', '#000000'],
    'blue': ['#084594', '#2171B5', '#4292C6', '#6BAED6', '#9ECAE1', '#C6DBEF'],
    'gray': ['#252525', '#525252', '#737373', '#969696', '#BDBDBD', '#D9D9D9'],
}


def contract_version(source_json):
    if not isinstance(source_json, dict):
        raise StorageError('task_source_conflict', '图表来源契约无效。', 409)
    version = source_json.get('figure_contract', 1)
    if type(version) is not int or version not in (1, 2, 3):
        raise StorageError('task_source_conflict', '图表来源契约版本无效。', 409)
    return version


def renderer_for(source_json):
    return {1: RENDERER, 2: V2_RENDERER, 3: LATEST_RENDERER}[contract_version(source_json)]


def enrich_material(payload, expected, *, config, result, projection, fields, contract=2):
    """v2 remains immutable; v3 makes the full caption own all statistical notes."""
    if type(contract) is not int or contract not in (2, 3):
        raise StorageError('task_source_conflict', '图表展示契约版本无效。', 409)
    payload, expected = deepcopy(payload), deepcopy(expected)
    config = config.model_dump() if hasattr(config, 'model_dump') else config
    fields = fields or {}
    style = config.get('style') or {}
    rules = config.get('projection') or {}
    zh = payload.get('language', config.get('language')) == 'zh-CN'
    def tr(cn, en): return cn if zh else en
    kind = payload['figure_kind']
    labels = payload['labels']
    aliases = style.get('aliases', {})
    def unit(info):
        value = info.get('unit') or ''
        return (value.get('value') or '') if isinstance(value, dict) else value
    def field(column):
        info = fields.get(column, {})
        return aliases.get(column, info.get('name', column or '')), unit(info)
    def axis(name, units):
        return {'label': name + (' (' + units + ')' if units else ''), 'unit': units}
    x = {'label': labels.get('x_label', ''), 'unit': ''}
    y = {'label': labels.get('y_label', ''), 'unit': ''}
    if rules and kind in ('line', 'bar', 'violin'):
        x = axis(*field(rules.get('x_column') or rules.get('category_column') or rules.get('group_column')))
        y = axis(*field(rules.get('y_column')))
    else:
        # Public variables already contain confirmed names and units, unlike local result IDs.
        for target in (x, y):
            for variable in payload.get('variables', []):
                name = variable.get('name', '')
                units=unit(variable)
                suffix=units or tr('单位未填写','unit not specified')
                if name and target['label'] in (name, name+' ('+suffix+')', name+'（'+suffix+'）'):
                    target['unit'] = unit(variable)
                    break
            if not target['unit'] and kind == 'boxplot' and not payload.get('variables'):
                match = re.search(r'[（(]([^（）()]*)[）)]$', target['label'])
                if match and match[1] not in ('单位未填写', 'unit not specified'):
                    target['unit'] = match[1]
    notes = []
    abbreviations = []
    def abbr(term, cn, en): abbreviations.append({'term': term, 'definition': tr(cn, en)})
    def note(cn, en): notes.append(tr(cn, en))
    abbr('n', '有效记录数；独立人数须由研究设计确认', 'Valid record count; independent participant count requires the study design')
    if kind in ('line', 'bar', 'violin'):
        note('描述性投影；有效记录数不等于独立人数。研究设计未提供时，不能推断独立性或因果。', 'Descriptive projection; valid records need not be independent participants. An unspecified study design does not establish independence or causality.')
    if kind == 'bar':
        stat = rules.get('bar_stat', 'count')
        if stat == 'count': y = {'label': tr('记录数', 'Record count'), 'unit': tr('条记录', 'records')}
        elif stat == 'proportion':
            y = {'label': tr('组内比例（0–1）', 'Within-group proportion (0–1)'), 'unit': '0–1'}
            note('比例为类别记录数除以确认类别范围内的组内有效记录数；保留0–1数值。', 'Proportion is category record count divided by valid within-group records in the confirmed category range; values remain on the 0–1 scale.')
        elif rules.get('error_bars') == 'sd':
            abbr('SD', '样本标准差（分母n−1）', 'Sample standard deviation (denominator n−1)')
            note('均值误差线表示样本SD，不是置信区间。', 'Mean error bars show sample SD, not confidence intervals.')
            note('有效记录不足2条时样本SD不可计算；无有效数值时均值和SD不可计算；缺失误差线不表示SD为0。', 'Sample SD is unavailable with fewer than two valid records; mean and SD are unavailable with no valid numeric values; an absent error bar does not mean zero SD.')
    elif kind == 'line':
        duplicate = tr('同组同X保持唯一', 'Same-group X values must be unique') if rules.get('aggregation') == 'unique' else tr('同组同X取有效值算术均值', 'Same-group X values use the arithmetic mean of valid Y values')
        note(duplicate + '；已知缺失断线，不插值。', duplicate + '; known missing values break lines; no interpolation.')
    elif kind == 'violin':
        abbr('KDE', '核密度估计', 'Kernel density estimation')
        abbr('Q1', '第一四分位数', 'First quartile'); abbr('Q3', '第三四分位数', 'Third quartile')
        note('等权高斯KDE，Scott带宽；截于观测范围且不重归一，各组共用密度宽度比例；形状不是置信区间。', 'Equal-weight Gaussian KDE with Scott bandwidth; truncated to observed range without renormalization, shared density-to-width scale; shape is not a confidence interval.')
    elif kind in ('boxplot', 'group_boxplot'):
        abbr('Q1', '第一四分位数', 'First quartile'); abbr('Q3', '第三四分位数', 'Third quartile'); abbr('IQR', '四分位距（Q3−Q1）', 'Interquartile range (Q3−Q1)')
        if contract == 3 and payload.get('legacy_contract') in (1,3):
            # These fixed base captions already contain the full box/whisker algorithm.
            note('箱体和须不是置信区间。', 'Boxes and whiskers are not confidence intervals.')
        else:
            note('箱体为Q1–Q3，中线为中位数；须端为1.5×IQR范围内最远观测，范围外点仍保留；箱体和须不是置信区间。', 'Boxes show Q1–Q3 and median; whiskers reach extreme observations within 1.5×IQR fences, outside points remain; boxes and whiskers are not confidence intervals.')
    elif kind == 'paired_connected':
        note('连线仅连接已确认顺序的同一完整配对；不代表独立组，也不新增推断标记。', 'Connections link the same complete pair in confirmed order; these are not independent groups and no inference markers are added.')
    elif kind in ('scatter', 'correlation_heatmap'):
        method = payload.get('correlation_method', result.get('statistics', {}).get('method'))
        abbr('ρ' if method == 'spearman' else 'r', 'Spearman秩相关系数' if method == 'spearman' else 'Pearson线性相关系数', 'Spearman rank correlation coefficient' if method == 'spearman' else 'Pearson linear correlation coefficient')
        note('相关不等于因果；仅展示已计算的相关系数与有效记录数，不新增P值、置信区间或显著性星号。', 'Correlation does not establish causation; show only computed coefficients and valid record counts, without additional P values, confidence intervals or significance stars.')
    elif kind == 'forest':
        logistic = payload.get('method') == 'logistic'
        x = {'label': tr('比值比（对数坐标）', 'Odds ratio (log scale)') if logistic else tr('回归系数', 'Regression coefficient'), 'unit': ''}
        abbr('OR' if logistic else 'β', '比值比' if logistic else '回归系数', 'Odds ratio' if logistic else 'Regression coefficient')
        abbr('CI', '置信区间（仅展示冻结结果中已有区间）', 'Confidence interval (only intervals present in the frozen result)')
        note('仅展示本地冻结效应与已有区间，不独立重新拟合；区间缺失不表示零宽度。不同预测变量单位见各项标签。', 'Displays frozen local effects and available intervals without independent refitting; unavailable intervals are not zero-width. Predictor units are given in term labels.')
    elif kind == 'roc_curve':
        x = {'label': tr('假阳性率（0–1）', 'False positive rate (0–1)'), 'unit': '0–1'}
        y = {'label': tr('真阳性率（0–1）', 'True positive rate (0–1)'), 'unit': '0–1'}
        abbr('ROC', '受试者工作特征曲线', 'Receiver operating characteristic curve'); abbr('AUC', 'ROC曲线下面积', 'Area under the ROC curve')
        note('ROC展示已确认评估资料中的区分能力；不能据此声称外部验证或校准良好，不新增AUC区间。', 'ROC describes discrimination in the confirmed evaluation data; it does not establish external validation or calibration; no additional AUC interval is computed.')
    elif kind == 'kaplan_meier':
        time_unit = payload.get('plot_config', {}).get('time_unit', '')
        x = axis(tr('时间', 'Time'), time_unit)
        if contract == 3 and result.get('selection', {}).get('time_column') in aliases:
            x = axis(aliases[result['selection']['time_column']], time_unit)
        y = {'label': tr('生存概率（0–1）', 'Survival probability (0–1)'), 'unit': '0–1'}
        abbr('KM', 'Kaplan–Meier乘积极限估计', 'Kaplan–Meier product-limit estimate'); abbr('CI', '置信区间', 'Confidence interval')
        note('同一时刻先处理事件再处理删失；95%区间采用Greenwood方差和log–log变换，仅展示已有可计算区间；删失不等于无事件随访完成。', 'Tied events precede censoring; available 95% intervals use Greenwood variance and log–log transformation; censoring does not mean event-free completed follow-up.')
    groups = []; identities=set()
    def add(value):
        if value is None:return
        identity=('number',float(value)) if type(value) in (int,float) else (type(value).__name__,value)
        if identity not in identities:groups.append(value);identities.add(identity)
    if kind in ('line','bar','violin') and isinstance(projection,dict):
        # Only groups retained by the confirmed projection have visible marks.
        for series in projection.get('series',[]):add(series.get('group'))
    elif kind != 'kaplan_meier':
        for row in payload.get('observations', []): add(row.get('group'))
    for group in payload.get('groups', []): add(group.get('label'))
    for group in payload.get('group_labels', []): add(group)
    display = payload.get('display_groups', [])
    if isinstance(display, list):
        for group in display: add(group.get('group') if isinstance(group, dict) else group)
    palette = _PALETTES.get(style.get('palette', 'colorblind'), _PALETTES['colorblind'])
    def group_label(value):
        label=str(value)
        if sum(str(g)==label for g in groups)>1:
            kind_label=tr('布尔值','boolean') if type(value) is bool else tr('数值','number') if type(value) in (int,float) else tr('文本','text')
            label+=' ['+kind_label+']'
        return label
    legend = {'title': tr('分组', 'Group'), 'entries': [{'label': group_label(group), 'color': palette[i % len(palette)]} for i, group in enumerate(groups)]}
    if contract == 3:
        group_column = rules.get('group_column') or result.get('selection', {}).get('group_column')
        if group_column in aliases: legend['title'] = aliases[group_column]
    color_scale = None
    if kind == 'correlation_heatmap':
        color_scale = {'label': tr('相关系数', 'Correlation coefficient'), 'min': -1, 'max': 1, 'center': 0, 'ticks': [-1, 0, 1], 'palette': ['#2166AC', '#F7F7F7', '#B2182B']}
        x = {'label': tr('变量', 'Variables'), 'unit': ''}; y = deepcopy(x)
    presentation = {'schema_version': 2 if contract == 3 else 1, 'axes': {'x': x, 'y': y}, 'legend': legend, 'color_scale': color_scale, 'abbreviations': abbreviations, 'statistical_notes': notes}
    # Keep author text verbatim. Replace only known system enum wording; new notes
    # form the additional localized system caption and are independently rebuildable.
    caption = labels.get('caption', '')
    author_caption = style.get('caption', '')
    if author_caption and caption.endswith(author_caption):
        caption = caption[:-len(author_caption)].rstrip()
    else:
        author_caption = ''
    caption = caption.replace('重复值规则：unique', '重复值规则：同组同X唯一').replace('重复值规则：mean', '重复值规则：同组同X取均值')
    roles = {'apparent_exploratory': '表观探索性评估', 'held_out_validation': '留出集验证', 'unknown': '未提供', 'apparent': '表观评估', 'internal_validation': '内部验证', 'external_validation': '外部验证', 'training': '训练集评估', 'test': '测试集评估', 'validation': '验证集评估'}
    if zh:
        for code, name in roles.items(): caption = caption.replace('评估角色：' + code, '评估角色：' + name)
    caption = re.sub(r'^(?:图\s*1[.．、]?\s*|Figure\s+1[.．]?\s*)', '', caption)
    if author_caption: caption += (' ' if caption else '') + author_caption
    labels.update(x_label=x['label'], y_label=y['label'], caption=caption + (' ' if caption else '') + ' '.join(notes))
    for key in ('title', 'x_label', 'y_label', 'caption'): expected[key] = labels[key]
    payload['presentation'] = deepcopy(presentation)
    expected['presentation'] = presentation
    return payload, expected
