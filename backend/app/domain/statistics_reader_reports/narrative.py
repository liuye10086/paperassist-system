"""Bilingual presentation of saved statistics and verified explanation sections."""
import re

from app.domain.artifact_contracts import figure_kind
from app.domain.explanation_content import limitations_for
from app.domain.reader_reports.content import _science, validate_output

ADAPTER_VERSION = 'statistics_saved_explanation_v1'
ORIGIN = 'saved_explanation_reuse'

METHODS = {
    'descriptive_statistics': ('描述统计', 'Descriptive statistics'),
    'pearson': ('Pearson 线性相关', 'Pearson linear correlation'),
    'spearman': ('Spearman 秩相关', 'Spearman rank correlation'),
    'welch_t': ('Welch 双样本 t 检验', 'Welch two-sample t test'),
    'mann_whitney_u': ('Mann–Whitney U 检验', 'Mann–Whitney U test'),
    'paired_t': ('配对 t 检验', 'Paired t test'),
    'wilcoxon': ('Wilcoxon 符号秩检验', 'Wilcoxon signed-rank test'),
    'welch_anova': ('Welch 方差分析', 'Welch analysis of variance'),
    'kruskal_wallis': ('Kruskal–Wallis 检验', 'Kruskal–Wallis test'),
    'ols': ('普通最小二乘回归', 'Ordinary least-squares regression'),
    'logistic': ('二项 Logistic 回归', 'Binary logistic regression'),
    'roc_auc': ('ROC 曲线及曲线下面积', 'ROC curve and area under the curve'),
    'kaplan_meier': ('Kaplan–Meier 生存估计', 'Kaplan–Meier survival estimation'),
}

FIGURE_READING = {
    'boxplot': (
        '箱体边界对应第一和第三四分位数，中线为中位数。须端为距箱缘不超过 1.5 倍四分位距的最远观测，范围外的点仍是观测记录。',
        'The box spans the first to third quartiles and the line marks the median. Whiskers reach the farthest observations within 1.5 interquartile ranges of the box. Points beyond the whiskers are observed values.'),
    'group_boxplot': (
        '按组读取结局的中位数、四分位范围和散布。箱体和须描述观测分布，原检验的效应和置信区间见结果表。',
        'Compare medians, interquartile ranges and spread by group. The boxes and whiskers describe observed distributions. Effect estimates and confidence intervals are in the result tables.'),
    'paired_connected': (
        '每条连线连接一对完整观测。沿原图的前后顺序读同一配对，再结合结果表中按前减后计算的差值。',
        'Each connection links a complete pair. Read within pairs in the displayed before-to-after order and consult the saved before-minus-after differences.'),
    'scatter': (
        '横轴和纵轴为所选的两个测量，每个点为一条完整记录。结合原相关系数读取关联方向与程度。',
        'The axes represent the two selected measurements and each point is a complete record. Use the saved correlation coefficient to interpret the direction and degree of association.'),
    'correlation_heatmap': (
        '横纵轴为纳入变量，单元格对应一对变量的相关系数。结合图上的尺度读取正负方向和大小。',
        'Rows and columns identify the included variables. Each cell shows the correlation for a pair of variables. Read its sign and magnitude against the scale shown in the figure.'),
    'forest': (
        '每行对应一个回归项，标记为保存的效应估计，横线为可用的置信区间。各项单位和区间缺失状态见结果表。',
        'Each row corresponds to a regression term. Markers show the saved effect estimate and lines show available confidence intervals. Consult the workbook for term-specific units and missing intervals.'),
    'roc_curve': (
        '横轴为假阳性率，纵轴为真阳性率。沿不同阈值读取两者的取舍，曲线下面积概括当前资料的区分能力。',
        'The horizontal axis shows the false positive rate and the vertical axis the true positive rate. Follow their trade-off across thresholds. The area summarizes discrimination in the evaluation data.'),
    'kaplan_meier': (
        '沿横轴的随访时间读取纵轴的估计生存概率。结合风险集中人数、事件和删失数解释曲线变化与尾部不确定性。',
        'Read estimated survival probability over follow-up time. Use the numbers at risk, events and censoring to interpret changes and uncertainty toward the end of follow-up.'),
    'line': (
        '沿横轴顺序读取各序列的纵轴数值，仅在投影规则规定的范围内比较走势。',
        'Read the vertical measurements in horizontal-axis order for each series. Compare trends within the scope of the saved projection.'),
    'bar': (
        '按横轴类别和图例对比柱高。使用纵轴所示计量及固定的分母或汇总规则解释大小。',
        'Compare bar heights across horizontal categories and the legend. Interpret the heights using the recorded vertical measure and its denominator or aggregation rule.'),
    'violin': (
        '按组阅读纵轴的测量值及提琴宽度。宽度用于展示平滑后的分布形状，组内计数见结果表。',
        'Read measurement values on the vertical axis and compare violin widths within each group. Width shows a smoothed distribution. Group counts are in the results.'),
}

COLOR_NAMES = {
    '#0072B2': ('蓝色', 'blue'), '#E69F00': ('橙色', 'orange'), '#009E73': ('蓝绿色', 'green'),
    '#CC79A7': ('紫红色', 'purple'), '#D55E00': ('橙红色', 'vermilion'), '#56B4E9': ('浅蓝色', 'light blue'),
    '#F0E442': ('黄色', 'yellow'), '#000000': ('黑色', 'black'), '#333333': ('深灰色', 'dark gray'),
    '#666666': ('灰色', 'gray'), '#999999': ('中灰色', 'medium gray'), '#BBBBBB': ('浅灰色', 'light gray'),
}


def clean(value):
    return _science(str(value or '')).strip()


def localized(language, zh, en):
    return en if language == 'en' else zh


def method_name(result, language):
    method = result['selection'].get('method', 'descriptive_statistics')
    return localized(language, *METHODS.get(method, ('已保存的统计方法', 'Saved statistical method')))


def number(value, language):
    # Narrative values are rounded for reading; the workbook keeps original precision.
    if type(value) is int:
        return str(value)
    if type(value) is float:
        return format(value, '.6g')
    return localized(language, '未提供', 'unavailable')


def observations(result, language):
    stats = result.get('statistics', {})
    kind = result.get('result_type', 'descriptive')
    measure = lambda value: number(value, language)
    if kind == 'correlation':
        n = measure(stats.get('n'))
        if stats.get('mode') == 'pair':
            coefficient = measure(stats.get('coefficient'))
            return localized(language, f'相关系数为 {coefficient}，来自 {n} 条完整记录。',
                             f'The correlation coefficient was {coefficient} across {n} complete records.')
        return localized(language, f'相关矩阵使用 {n} 条完整记录。各变量对的系数和方向按所选顺序收录于结果表。',
                         f'The correlation matrix uses {n} complete records. Coefficients for each variable pair are in the workbook in selection order.')
    if kind == 'group_comparison':
        ns = ', '.join(measure(n) for n in stats.get('sample_sizes', []))
        p = measure(stats.get('p_value', {}).get('value'))
        design = result['selection'].get('design')
        groups = localized(language, f'各组计数（保存顺序）为 {ns}。', f'Group counts in saved order were {ns}.')
        if design == 'paired':
            pairs = measure(result.get('check', {}).get('valid_count'))
            groups = localized(language, f'共有 {pairs} 个完整配对，差值按前减后计算。',
                               f'There were {pairs} complete pairs. Differences use before minus after.')
        return groups + localized(language, f' 原检验的 P 值为 {p}。效应方向和适用的区间、校正规则以结果表为准。',
                                  f' The saved test P value was {p}. The workbook records the effect direction and applicable intervals and adjustments.')
    if kind == 'regression':
        n = measure(stats.get('n'))
        fit = stats.get('r_squared')
        if fit is not None:
            return localized(language, f'模型纳入 {n} 条记录，决定系数为 {measure(fit)}。效应估计、单位和区间按回归项列在工作簿中。',
                             f'The model used {n} records and had an R-squared of {measure(fit)}. The workbook lists estimates, units and intervals by term.')
        terms = [term for term in stats.get('coefficients', []) if term.get('column') is not None and term.get('or_value') is not None]
        if terms:
            name = clean(terms[0]['term'])[:60]
            odds = measure(terms[0]['or_value'])
            return localized(language, f'模型纳入 {n} 条记录。首个非截距项 {name} 的比值比为 {odds}，各项区间见工作簿。',
                             f'The model used {n} records. The reported odds ratio for its first non-intercept term, {name}, was {odds}. Term-specific intervals are in the workbook.')
        return localized(language, f'模型纳入 {n} 条记录。工作簿列出效应估计、单位和诊断。',
                         f'The model used {n} records. The workbook lists effect estimates, units and diagnostics.')
    if kind == 'roc':
        n, auc = measure(stats.get('n')), measure(stats.get('auc'))
        direction = result['selection'].get('direction')
        directions = {
            'higher_is_positive': ('较高分数判为阳性。', ' Higher scores indicate the positive class.'),
            'lower_is_positive': ('较低分数判为阳性。', ' Lower scores indicate the positive class.'),
        }
        return localized(language, f'曲线下面积为 {auc}，评估纳入 {n} 条记录。',
                         f'The area under the curve was {auc} across {n} evaluation records.') + localized(
                             language, *directions.get(direction, ('阳性方向见结果表。', ' Consult the results for the positive-score direction.')))
    if kind == 'survival':
        n = measure(stats.get('n'))
        groups = stats.get('groups', [])
        event_counts = ', '.join(measure(group.get('event_n')) for group in groups)
        censored_counts = ', '.join(measure(group.get('censored_n')) for group in groups)
        return localized(language, f'生存估计纳入 {n} 条记录。按保存的分组顺序，事件计数为 {event_counts}，删失计数为 {censored_counts}。',
                         f'Survival was estimated from {n} records. In saved group order, the event counts were {event_counts} and the censoring counts were {censored_counts}.')
    overall = result.get('overall', {})
    n, median, mean = (measure(overall.get(key)) for key in ('n', 'median', 'mean'))
    unit = clean(result['selection'].get('unit'))
    suffix = f' {unit}' if unit else ''
    return localized(language, f'总体纳入 {n} 条记录。中位数为 {median}{suffix}，均值为 {mean}{suffix}。',
                     f'There were {n} included records. The median was {median}{suffix} and the mean was {mean}{suffix}.')


def quality(result, language):
    check = result.get('check', {})
    valid = number(check.get('valid_count'), language)
    total = number(check.get('row_count'), language)
    excluded = number(check.get('excluded_count'), language)
    return localized(language, f'来源记录数为 {total}，有效记录或配对数为 {valid}，排除数为 {excluded}。',
                     f'The recorded total was {total}, the valid record or pair count was {valid} and the excluded count was {excluded}.')


def unit_text(result, language):
    selection = result['selection']
    variables = result.get('variables', [])
    units = [clean(v.get('unit')) for v in variables]
    units.extend(clean(selection.get(key)) for key in ('unit', 'outcome_unit', 'time_unit', 'score_unit'))
    unit = ', '.join(dict.fromkeys(value for value in units if value))
    return localized(language, f'已声明的单位为 {unit}。', f'Recorded units were {unit}.') if unit else localized(
        language, '当前来源未声明测量单位。', 'The source does not specify measurement units.')


def design(result, language, limit=240):
    declaration = result.get('analysis_context', {}).get('plan', {}).get('research_request', {})
    structure = {
        'independent': ('声明为独立观测。', 'Observations were declared independent.'),
        'paired': ('声明为配对观测。', 'Observations were declared paired.'),
        'repeated': ('声明为重复观测。', 'Observations were declared repeated.'),
    }
    if not declaration:
        return localized(language, '当前来源未提供研究设计说明。', 'The source does not provide a study design statement.')
    relationship = localized(language, *structure.get(declaration.get('observation_structure'), (
        '观测关系未明确。', 'The relationship between observations is unspecified.')))
    items = [('question', ('问题', 'Question')), ('study_design', ('设计', 'Design')), ('observation_unit', ('观测单位', 'Unit'))]
    displayed = []
    for key, titles in items:
        text = clean(declaration.get(key))
        if len(text) > limit:
            text = text[:limit] + '…'
        displayed.append(localized(language, *titles) + ' ' + (text or localized(language, '未提供', 'not supplied')))
    return ' · '.join(displayed) + '。 ' + relationship if language == 'zh-CN' else ' · '.join(displayed) + '. ' + relationship


def projection_quality(item, language):
    projection = item.get('projection') or {}
    audit = projection.get('result', {}).get('audit', {})
    if not audit:
        return ''
    count = number(audit.get('valid_n'), language)
    return localized(language, f'此图的已确认投影纳入 {count} 条记录，投影范围与原统计分析可能不同。',
                     f'This figure projection used {count} valid records. Its inclusion scope can differ from the original analysis.')


def figure_output(item, position, language):
    figure, explanation, result = (item[key] for key in ('figure', 'explanation', 'result'))
    sections = {section['key']: clean(section['text']) for section in explanation['sections']}
    kind = figure.get('figure_kind') or figure_kind(result)
    presentation = figure.get('presentation', {})
    axes = presentation.get('axes') or {axis: {'label': figure.get(axis + '_label')} for axis in ('x', 'y')}
    parts = [localized(language, *FIGURE_READING[kind])]
    shown_axes = []
    for axis, name in (('x', localized(language, '横轴', 'Horizontal axis')),
                       ('y', localized(language, '纵轴', 'Vertical axis'))):
        label = clean(axes.get(axis, {}).get('label'))
        unit = clean(axes.get(axis, {}).get('unit'))
        if label:
            shown_axes.append(axis)
            display = f'{label} ({unit})' if unit and unit not in label else label
            parts.append(localized(language, f'{name}为 {display}。', f'{name} shows {display}.'))
    legend = []
    for entry in presentation.get('legend', {}).get('entries', []):
        label = clean(entry.get('label'))
        color = COLOR_NAMES.get(str(entry.get('color', '')).upper())
        if label:
            legend.append(f'{label} ({localized(language, *color)})' if color else label)
    if legend:
        groups = ', '.join(legend)
        parts.append(localized(language, f'已保存的图例包括 {groups}。', f'The saved legend identifies {groups}.'))
    scale = presentation.get('color_scale')
    if scale:
        low, high = number(scale.get('min'), language), number(scale.get('max'), language)
        parts.append(localized(language, f'已保存的色标从 {low} 到 {high}。', f'The saved color scale spans {low} to {high}.'))
    if len(shown_axes) < 2:
        parts.append(localized(language, '固定图件资料未记录全部轴标签，请结合原图标注和结果表阅读。',
                               'Some axis labels are unavailable in the saved figure metadata. Consult the original image and result tables.'))
    title = clean(figure.get('title')) or method_name(result, language)
    if figure.get('figure_number') is not None:
        title = re.sub(r'^(?:图|Figure)\s*\d+\s*[.．:：]?\s*', '', title) or method_name(result, language)
    saved_caption = clean(item.get('user_caption'))
    reading = ' '.join(parts)
    if sections['methods']:
        reading += localized(language, '\n原图解记录的方法为 ', '\nThe saved explanation describes the method as follows. ') + sections['methods']
    observed = localized(language, '已保存且核对引用的图解记录如下。', 'The reference-checked saved explanation records the following.')
    observed += ' ' + sections['results'] + ' ' + projection_quality(item, language)
    interpreted = localized(language, '原图解对来源结果的解释为 ', 'The saved explanation interprets the recorded results as follows. ')
    interpreted += sections['interpretation']
    if saved_caption:
        interpreted += localized(language, '\n作者补充图注为 ', '\nThe author supplied this additional caption. ') + saved_caption
    limitations = [clean(value) for value in explanation.get('limitations', [])]
    limitations += [clean(value) for value in presentation.get('statistical_notes', [])]
    limitations.append(localized(language, '本地报告沿用已保存图解和图件信息。图像细节需要结合原图人工核对。',
                                 'This report reuses the saved explanation and figure metadata. Review the original figure to verify visual details.'))
    return dict(number=position, title=title, reading=reading, observations=observed, interpretation=interpreted,
                limitations=' '.join(dict.fromkeys(value for value in limitations if value)))


def build_reader_output(language, sources, items):
    """Validate the deterministic seven sections and four parts for each selected figure."""
    if any(item.get('explanation') is None for item in items):
        return None
    results = [source.content['result'] for source in sources]
    methods = list(dict.fromkeys(method_name(result, language) for result in results))
    figure_sections = [figure_output(item, index, language) for index, item in enumerate(items, 1)]
    scopes = [localized(language, f'分析 {index}。', f'Analysis {index}.') for index in range(1, len(results) + 1)]
    def per_result(function):
        return '\n\n'.join(f'{prefix} {function(result, language)}' for prefix, result in zip(scopes, results, strict=True))

    method_text = []
    for prefix, result in zip(scopes, results, strict=True):
        item = next(item for item in items if item['result']['id'] == result['id'])
        explanation_methods = next(section['text'] for section in item['explanation']['sections'] if section['key'] == 'methods')
        method_text.append((prefix, result, clean(explanation_methods)))
    use_full_methods = sum(len(text) + 120 for _, _, text in method_text) < 12000
    shown_methods = []
    for prefix, result, reported in method_text:
        if not use_full_methods:
            reported = observations(result, language) + ' ' + unit_text(result, language)
        name = method_name(result, language)
        shown_methods.append(localized(language, f'{prefix} {name}。 {reported}', f'{prefix} {name}. {reported}'))
    limits = []
    for result in results:
        limits.extend(clean(value) for value in limitations_for(result, language))
    if any(source.content['execution_verification'] == 'legacy_unverified' for source in sources):
        limits.append(localized(language, '所选历史结果中含缺少现行执行核对记录的结果，按原保存状态呈现。',
                                'At least one historical result has no current execution-verification receipt. Its saved status is retained.'))
    method_summary = ', '.join(methods)
    key = per_result(observations)
    design_limit = min(240, 2100 // len(results))
    narrative = dict(
        abstract=localized(language,
            f'本报告汇总 {len(results)} 项已保存分析和 {len(figure_sections)} 张原图，涉及 {method_summary}。数值与图件保留原保存版本，解释复用已核对引用的历史图解。',
            f'This report presents {len(results)} saved analyses and {len(figure_sections)} original figures, using {method_summary}. Results and figures retain their saved versions. The narrative reuses saved explanations with checked references.'),
        design_and_data=per_result(lambda result, lang: f'{design(result, lang, design_limit)} {unit_text(result, lang)}'),
        quality_control=per_result(quality) + '\n\n' + localized(language,
            '工作簿保留本次选材记录的缺失、排除及可用性信息。证据范围以原结果和各图的选材为准。',
            'The workbook retains recorded missingness, exclusions and usability. Interpret each estimate and figure within its own inclusion scope.'),
        methods_summary='\n\n'.join(shown_methods),
        key_findings=key,
        limitations='\n\n'.join(dict.fromkeys(value for value in limits if value)),
        reader_cautions=localized(language,
            '阅读原图时同时核对对应表格的单位、有效计数和比较方向。结合采集设计确认参与者独立性、重复观测关系及资料缺失机制。需要推广结果时，按同一变量定义和分析范围使用独立资料验证。',
            'Review the original figures alongside their result tables. Confirm units, available counts and comparison directions. Check the data collection design for participant independence, repeated measurements and missingness. To assess generalizability, use independent data with the same variable definitions and analysis scope.'),
    )
    return validate_output(dict(narrative=narrative, figures=figure_sections),
                           dict(language=language, figures=figure_sections))
