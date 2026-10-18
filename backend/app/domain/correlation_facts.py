"""Grounded correlation facts and localized fixed limitations."""
from app.domain.dataset_processing import analysis_stage_text, retained_fact_labels
from app.domain.artifact_contracts import artifact_language

REASONS = {
    'exploratory_matrix': ('探索矩阵不计算推断检验', 'Inference is not computed for an exploratory matrix'),
    'spearman_interval_not_implemented': ('本批未实现 Spearman 置信区间', 'Spearman confidence intervals are not implemented in this batch'),
    'insufficient_for_fisher_interval': ('有效样本不足以计算 Fisher 区间', 'Insufficient observations for a Fisher interval'),
    'degenerate_correlation': ('相关系数退化，区间无法计算', 'Degenerate correlation; interval is unavailable'),
}
P_METHODS = {
    'pearson_beta_two_sided': ('Pearson 双侧 beta 分布检验', 'Pearson two-sided beta-distribution test'),
    'spearman_pairings_exact': ('Spearman 配对相关全枚举排列检验', 'Spearman exact enumeration of correlation pairings'),
    'spearman_pairings_monte_carlo': ('Spearman 配对相关 Monte Carlo 排列检验', 'Spearman Monte Carlo permutation of correlation pairings'),
    'spearman_asymptotic': ('Spearman 大样本近似检验', 'Spearman large-sample asymptotic test'),
}


def localized_pair(values, language):
    return values[0 if language == 'zh-CN' else 1]


def reason_text(reason, language):
    if reason in REASONS:
        return localized_pair(REASONS[reason], language)
    return ('无法计算：' if language == 'zh-CN' else 'Unavailable: ') + (reason or ('原因未记录' if language == 'zh-CN' else 'reason not recorded'))


def method_summary(result, language):
    stats = result['statistics']
    method = 'Pearson' if stats['method'] == 'pearson' else 'Spearman'
    if language == 'en':
        text = f'{method} correlation uses complete observations across all selected variables, retaining original row correspondence; no imputation, deduplication or outlier removal. '
        text += ('Pearson measures linear association; its inferential assumptions are declared by the user, not proven by this program. '
                 if stats['method'] == 'pearson' else 'Spearman measures monotonic association and assigns average ranks to ties. ')
        if stats['mode'] == 'matrix':
            return analysis_stage_text(text, result) + 'This exploratory matrix reports coefficients and common n only, without P values, intervals or multiple-testing claims.'
    else:
        text = f'{method}相关采用全部所选变量共同完整记录，保持原始行对应；未插补、去重或剔除离群值。'
        text += ('Pearson度量线性关联；推断前提由用户声明，程序不能证明这些前提。' if stats['method'] == 'pearson' else
                 'Spearman度量单调关联，并列值采用平均秩。')
        if stats['mode'] == 'matrix':
            return analysis_stage_text(text, result) + '探索矩阵只报告系数及共同有效 n，不提供 P 值、区间或多重检验结论。'
    p = stats['p_value']
    text += localized_pair(P_METHODS.get(p['method'], ('未计算 P 值', 'P value not computed')), language) + '. '
    inference = stats['inference']
    if inference.get('n_resamples') is not None:
        text += (f'排列次数 {inference["n_resamples"]}；' if language == 'zh-CN' else f'Permutation count {inference["n_resamples"]}; ')
    if inference.get('seed') is not None:
        text += (f'随机种子 {inference["seed"]}。' if language == 'zh-CN' else f'Random seed {inference["seed"]}. ')
    ci = stats['confidence_interval']
    text += (('95% Fisher z 区间。' if language == 'zh-CN' else '95% Fisher z interval. ') if ci['low'] is not None else reason_text(ci['reason'],language) + '. ')
    return analysis_stage_text(text, result)


def limitations(result, language):
    if language == 'en':
        values = ['Correlation describes association and does not establish causation or treatment effectiveness.',
                  'Independent observations and the required relationship/inferential assumptions were declared by the user; the program does not prove them.',
                  'Small samples and missing-record exclusions can make conclusions unstable; only the selected complete records were analysed.',
                  'Interpretation uses saved statistics and verified figure metadata; image pixels and AI wording require human review.',
                  'Displayed numbers use at most 6 significant digits; saved results preserve full precision.']
        if result['statistics']['mode'] == 'matrix': values.insert(1,'The matrix is exploratory: no P values, confidence intervals, significance stars or multiple-testing inference.')
    else:
        values = ['相关描述关联程度，不等于因果，也不能证明疗效。',
                  '独立观察及关系形态、推断前提由用户声明，程序不能证明这些前提。',
                  '小样本及缺失记录排除可能使结论不稳定，本次只分析所选完整记录。',
                  '解释依据保存统计和已核对图表元数据，图片像素及 AI 文字仍需人工审阅。',
                  '显示数值最多采用 6 位有效数字，保存结果保留完整精度。']
        if result['statistics']['mode'] == 'matrix': values.insert(1,'矩阵仅作探索，不包含 P 值、置信区间、显著性星号或多重检验结论。')
    return values


def build_payload(result, figure):
    language = artifact_language(result)
    facts = {}
    def add(key, labels, value):
        label = localized_pair(labels,language)
        display = ('无法计算' if language == 'zh-CN' else 'Unavailable') if value is None else format(value,'.6g') if isinstance(value,float) else str(value)
        facts[key] = {'label':label,'value':display,'raw':value}
    for index,variable in enumerate(result['variables']):
        add(f'variables.{index}.name',('变量','Variable'),variable['name'])
        add(f'variables.{index}.unit',('单位','Unit'),variable['unit'] or ('单位未填写' if language == 'zh-CN' else 'unit not specified'))
    add('figure.number',('图号','Figure number'),figure['figure_number'])
    add('figure.title',('图标题','Figure title'),figure['title'])
    add('method.summary',('分析方法','Analysis method'),method_summary(result,language))
    for key,source,labels in [('total','row_count',('原始行数','Source row count')),('valid','valid_count',('完整记录数','Complete record count')),
                             ('excluded','excluded_count',('排除行数','Excluded row count'))]:
        add('data.'+key,labels,result['check'][source])
    stats=result['statistics']
    add('correlation.n',('共同有效样本数','Common effective n'),stats['n'])
    add('correlation.method',('相关方法','Correlation method'),'Pearson' if stats['method']=='pearson' else 'Spearman')
    required_results=['correlation.n']
    if stats['mode']=='pair':
        add('correlation.coefficient',('相关系数','Correlation coefficient'),stats['coefficient'])
        p=stats['p_value']
        add('correlation.p_value',('双侧 P 值','Two-sided P value'),p['value'] if p['value'] is not None else reason_text(p['reason'],language))
        ci=stats['confidence_interval']
        add('correlation.confidence_interval',('置信区间','Confidence interval'),
            (f'{format(ci["low"],".6g")} 至 {format(ci["high"],".6g")}' if language=='zh-CN' else
             f'{format(ci["low"],".6g")} to {format(ci["high"],".6g")}') if ci['low'] is not None else reason_text(ci['reason'],language))
        required_results += ['correlation.coefficient','correlation.p_value','correlation.confidence_interval']
        interpretation=['correlation.coefficient']
    else:
        for row,values in enumerate(stats['matrix']):
            for column,value in enumerate(values):
                key=f'matrix.{row}.{column}'
                add(key,(f'{result["variables"][row]["name"]} 与 {result["variables"][column]["name"]}：系数',
                         f'{result["variables"][row]["name"]} / {result["variables"][column]["name"]}: coefficient'),value)
                required_results.append(key)
        interpretation=['correlation.n']
    variable_refs=[f'variables.{index}.name' for index in range(len(result['variables']))]
    unit_refs=[f'variables.{index}.unit' for index in range(len(result['variables']))]
    retained_fact_labels(facts, result, language)
    return {'schema_version':2,'language':language,'analysis_run_id':result['id'],'figure_id':figure['id'],
        'source_sha256':result['source_sha256'],'figure_sha256':figure['sha256'],'facts':facts,
        'required_references':{'purpose':variable_refs,'data':['data.total','data.valid','data.excluded'],
            'methods':['method.summary'],'results':variable_refs+unit_refs+required_results,
            'interpretation':interpretation,'paper_text':['figure.number','correlation.method',*variable_refs,*required_results]}}
