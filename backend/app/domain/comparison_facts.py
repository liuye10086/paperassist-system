"""Program-owned comparison facts; inference never comes from model prose."""
from app.domain.dataset_processing import analysis_stage_text, retained_fact_labels
from collections import Counter
from app.domain.artifact_contracts import artifact_language

METHODS={
    'welch_t':('Welch 独立样本 t 检验','Welch independent-samples t test'),
    'mann_whitney_u':('Mann–Whitney U 检验','Mann–Whitney U test'),
    'paired_t':('配对 t 检验','Paired t test'),
    'wilcoxon':('Wilcoxon 符号秩检验','Wilcoxon signed-rank test'),
    'welch_anova':('Welch 单因素 ANOVA','Welch one-way ANOVA'),
    'kruskal_wallis':('Kruskal–Wallis 检验','Kruskal–Wallis test')}
P_METHODS={
    'welch_t_two_sided':('Welch 双侧 t 分布解析检验（Satterthwaite 自由度）','Welch two-sided analytical t test with Satterthwaite degrees of freedom'),
    'paired_t_two_sided':('配对双侧 t 分布解析检验','Paired two-sided analytical t test'),
    'mann_whitney_exact_two_sided':('Mann–Whitney U 双侧精确分布检验','Mann–Whitney U two-sided exact distribution test'),
    'mann_whitney_asymptotic_two_sided':('Mann–Whitney U 双侧正态近似检验，校正并列秩','Mann–Whitney U two-sided normal-approximation test with tie correction'),
    'wilcoxon_sign_exact_two_sided':('Wilcoxon 双侧符号精确枚举检验，保留并列秩重数','Wilcoxon two-sided exact sign-enumeration test retaining tied-rank multiplicities'),
    'wilcoxon_asymptotic_two_sided':('Wilcoxon 双侧正态近似检验，校正并列秩','Wilcoxon two-sided normal-approximation test with tie correction'),
    'welch_anova_f':('Welch ANOVA 的 F 分布上尾检验','Welch ANOVA upper-tail F test'),
    'kruskal_chi_square':('Kruskal–Wallis 卡方分布上尾近似检验','Kruskal–Wallis upper-tail chi-square approximation')}
EFFECTS={'mean_difference':('均值差','Mean difference'),
         'rank_biserial':('秩双列相关','Rank-biserial correlation'), None:('单一效应量','Single effect')}
REASONS={
    'omnibus_no_single_effect':('总体检验没有单一均值差或效应量','An omnibus test has no single mean difference or effect'),
    'omnibus_no_interval':('总体检验没有单一效应区间','An omnibus test has no single effect interval'),
    'rank_interval_not_implemented':('本批未实现秩效应的置信区间','Rank-effect confidence intervals are not implemented in this batch')}
EXCLUSIONS={
    'selected_missing':('所选字段缺失，按完整记录或完整对排除','selected-field missingness, exclusion by complete record or complete pair'),
    'missing_measurement':('测量缺失','missing measurement'),
    'missing_numeric':('结局缺失','missing outcome'),
    'missing_group':('分组缺失','missing group'),
    'unselected_group':('未选择的分组','unselected group'),
    'group_not_selected':('未选择的分组','unselected group'),
    'missing_pair_measurement':('配对测量缺失，整对排除','missing paired measurement, complete pair excluded')}
WARNINGS={
    'small_sample':('小样本结果可能不稳定','Small-sample results may be unstable'),
    'asymptotic_p_value':('P 值采用明确记录的大样本近似','P values use the recorded large-sample approximation'),
    'rank_interval_unavailable':REASONS['rank_interval_not_implemented'],
    'pairwise_intervals_unadjusted':('逐比较区间未作同时校正','Individual pair intervals have no simultaneous correction'),
    'observational_not_causal':('比较结果不能单独证明因果或疗效','Comparison findings alone do not establish causation or effectiveness'),
    'zero_differences_excluded':('零差值仅从符号秩计算中排除，仍计入完整对','Zero differences are excluded only from signed ranks and remain included pairs')}


def local(values,language): return values[0 if language=='zh-CN' else 1]


def algorithm_name(method,language):
    return local(P_METHODS.get(method,('未识别的推断算法，须复核保存结果','Unrecognized inference algorithm; review the saved result')),language)


def yes_no(value,language):
    return local(('是','yes') if value else ('否','no'),language)


def reason_text(reason,language):
    return local(REASONS.get(reason,('无法计算：'+str(reason),'Unavailable: '+str(reason))),language)


def assumptions_summary(result,language):
    value=result['selection']['assumptions']
    distributions={'normal':('正态分布（配对路径指差值正态）','normal distribution (paired tests refer to normal differences)'),
        'symmetric_differences':('差值分布对称','symmetric differences'), 'rank':('采用秩方法前提','rank-method assumptions'),
        'unknown':('分布未明确','distribution not specified')}
    declared=local(('已确认','confirmed'),language)
    unconfirmed=local(('未确认','not confirmed'),language)
    return local(('独立观察单位声明：','Independent-unit declaration: '),language)+(declared if value['independent_units'] else unconfirmed)+'; '+local(('分布前提：','Distribution assumption: '),language)+local(distributions[value['distribution']],language)+'; '+local(('推断前提：','Inference assumptions: '),language)+(declared if value['inference_confirmed'] else unconfirmed)+'. '+local(('前提由用户声明，程序不证明其成立。','These assumptions are user declarations; the program does not prove them.'),language)


def method_summary(result,language):
    stats=result['statistics']; inference=stats['inference']; design=stats['design']
    text=local(METHODS[stats['method']],language)+'. '
    text+=local(('使用已确认参与组的完整记录，保持组顺序；未插补、去重或剔除离群值。','Complete observations from confirmed participating groups retain group order; no imputation, deduplication or outlier removal.'),language)+' '
    if design=='paired': text+=local(('宽表按唯一且非缺失的配对 ID 确认同一观察单位，单侧测量缺失时整对排除。差值为第一测量减第二测量；有效 n 为完整对数。','Wide-format pairs are verified by unique nonmissing local IDs. A missing measurement excludes its entire pair. Difference is the first measurement minus the second; effective n counts complete pairs.'),language)+' '
    text+=local(('总体检验采用对应 F/H 分布上尾。','The omnibus test uses the corresponding F/H upper tail.'),language) if inference['alternative']=='omnibus' else local(('检验固定双侧。','Tests are fixed two-sided.'),language)
    if stats['method']=='mann_whitney_u': text+=' '+local(('秩双列相关为 2U/(n第一组×n第二组)−1；方向为第一组相对第二组，不是均值或中位数差。','Rank-biserial effect is 2U/(n first group × n second group)−1, oriented first versus second; it is not a mean or median difference.'),language)
    elif stats['method']=='wilcoxon': text+=' '+local(('绝对差值并列采用平均秩；零差值仅从符号秩中排除，仍计入完整对。秩双列相关为 (R正−R负)/(R正+R负)，方向为第一测量减第二测量。','Absolute-difference ties use average ranks; zero differences are excluded only from signed ranks and remain included pairs. Rank-biserial effect is (Rplus−Rminus)/(Rplus+Rminus), oriented first minus second measurement.'),language)
    if stats['estimate']['name']=='mean_difference': text+=' '+local(('均值差为第一组或测量减第二组或测量，区间为普通 95% t 区间。','Mean difference is the first group or measurement minus the second, with an ordinary 95% t interval.'),language)
    text+=' '+local(('P 值算法：','P-value algorithm: '),language)+algorithm_name(stats['p_value']['method'],language)+'. '
    if stats['method'] in ('mann_whitney_u','wilcoxon'):
        text+=local(('精确枚举；','Exact enumeration; '),language) if inference['exact'] else local(('并列秩校正的大样本近似；','Tie-corrected large-sample approximation; '),language)
        text+=local(('连续性校正：','continuity correction: '),language)+yes_no(inference['continuity_correction'],language)+'. '
    if stats['family']['policy']=='all_pairs_holm': text+=local(('比较族为全部预声明组对，使用两两 Welch t 或两两 Mann–Whitney U 加 Holm；不按总体 P 值筛选，不称 Dunn 检验。逐比较普通 95% 区间未作同时校正。','The family contains all predeclared pairs, using pairwise Welch t or pairwise Mann–Whitney U plus Holm. Omnibus P does not gate the family; this is not Dunn testing. Ordinary individual 95% intervals have no simultaneous correction.'),language)
    return analysis_stage_text(text, result)


def interval_text(ci,language):
    if ci['low'] is None: return reason_text(ci['reason'],language)
    return f'{ci["low"]:.6g} '+local(('至','to'),language)+f' {ci["high"]:.6g}'+local(('；普通 95% 区间，未作同时校正','; ordinary 95% interval, no simultaneous correction'),language)


def inference_text(test,language):
    value=test['inference']
    rank=local(('平均秩','average ranks'),language) if value['rank_method']=='average' else local(('不适用','not applicable'),language)
    zero=local(('从符号秩中排除零差值','exclude zero differences from signed ranks'),language) if value['zero_method']=='wilcox' else local(('不适用','not applicable'),language)
    return local(('P 值算法：','P-value algorithm: '),language)+algorithm_name(test['p_value']['method'],language)+'; '+local(('秩策略：','rank method: '),language)+rank+'; '+local(('零差值处理：','zero-difference handling: '),language)+zero+'; '+local(('精确枚举：','exact enumeration: '),language)+yes_no(value['exact'],language)+'; '+local(('连续性校正：','continuity correction: '),language)+yes_no(value['continuity_correction'],language)+'.'


def decision(p,language,*,holm=False):
    prefix=local(('Holm 校正后','After Holm adjustment, '),language) if holm else ''
    return prefix+local(('P < 0.05，达到预设统计学阈值；不代表因果或疗效。','P < 0.05 meets the prespecified statistical threshold; this does not establish causation or effectiveness.'),language) if p<.05 else prefix+local(('P ≥ 0.05，未达到预设统计学阈值；不等于证明无差异。','P ≥ 0.05 does not meet the prespecified statistical threshold; this does not prove absence of a difference.'),language)


def limitations(result,language):
    values=[local(('统计比较不能单独证明因果或疗效；研究设计与样本来源须由研究者审核。','Statistical comparisons alone do not establish causation or effectiveness; researchers must review study design and sample provenance.'),language),
        assumptions_summary(result,language),
        local(('仅分析所选完整记录；排除及小样本可能影响结论，不自动证明总体适用性。','Only selected complete observations were analysed; exclusions and small samples can affect conclusions and do not establish population applicability.'),language),
        local(('云端核对仅限绘图 n 和描述摘要，未独立复现本地推断算法；图片像素与 AI 文字仍需人工审阅。','Cloud verification covers drawing n and descriptive summaries only, without independently reproducing local inference algorithms; image pixels and AI wording require review.'),language),
        local(('显示数值最多采用 6 位有效数字，保存结果保留完整精度。','Displayed values use at most 6 significant digits; saved results retain full precision.'),language)]
    if result['statistics']['family']['policy']=='all_pairs_holm': values.append(local(('Holm 仅校正完整预声明比较族的 P 值；逐比较普通 95% 区间未作同时校正。','Holm adjusts P values for the complete predeclared family only; ordinary individual 95% intervals have no simultaneous correction.'),language))
    if result['statistics']['confidence_interval']['reason']=='rank_interval_not_implemented': values.append(reason_text('rank_interval_not_implemented',language))
    return values


def build_payload(result,figure):
    language=artifact_language(result); stats=result['statistics']; facts={}
    def add(key,labels,value):
        display=local(('无法计算','Unavailable'),language) if value is None else format(value,'.6g') if isinstance(value,float) else str(value)
        facts[key]={'label':local(labels,language),'value':display,'raw':value}
    for index,variable in enumerate(result['variables']):
        add(f'variables.{index}.name',('变量','Variable'),variable['name'])
        add(f'variables.{index}.unit',('单位','Unit'),variable['unit'] or local(('单位未填写','unit not specified'),language))
    add('figure.number',('图号','Figure number'),figure['figure_number']); add('figure.title',('图标题','Figure title'),figure['title'])
    add('method.summary',('分析方法','Analysis method'),method_summary(result,language))
    add('comparison.assumptions',('用户声明的前提','User-declared assumptions'),assumptions_summary(result,language))
    for key,source,labels in [('total','row_count',('原始行数','Source rows')),('valid','valid_count',('完整对数','Complete pairs') if stats['design']=='paired' else ('纳入观察数','Included observations')),('excluded','excluded_count',('排除原始行数','Excluded source rows'))]: add('data.'+key,labels,result['check'][source])
    reasons=Counter(row['reason'] for row in result.get('row_audit',{}).get('excluded_rows',[]))
    exclusion='; '.join(local(EXCLUSIONS.get(reason,('排除原因：'+reason,'Exclusion reason: '+reason)),language)+f': {count}' for reason,count in sorted(reasons.items())) or local(('无排除记录','No excluded records'),language)
    add('data.exclusions',('排除口径','Exclusion basis'),exclusion)
    names=[group['label'] for group in result['groups']]
    direction=f'{names[0]} - {names[1]}' if stats['design']!='multiple' else local(('总体比较没有单一差值方向；组对方向为左组减右组','Omnibus comparison has no single difference direction; each pair is left minus right'),language)
    add('comparison.direction',('差值或秩效应方向','Difference or rank-effect direction'),direction)
    add('comparison.method',('检验方法','Test method'),local(METHODS[stats['method']],language))
    add('comparison.statistic',('检验统计量 '+stats['statistic']['name'],'Test statistic '+stats['statistic']['name']),stats['statistic']['value'])
    for key,labels in [('df_numerator',('分子自由度','Numerator degrees of freedom')),('df_denominator',('分母或 t 自由度','Denominator or t degrees of freedom'))]:
        add('comparison.'+key,labels,stats['statistic'][key] if stats['statistic'][key] is not None else local(('不适用','Not applicable'),language))
    add('comparison.p_value',('总体上尾 P 值','Omnibus upper-tail P value') if stats['inference']['alternative']=='omnibus' else ('双侧 P 值','Two-sided P value'),stats['p_value']['value'])
    add('comparison.estimate',EFFECTS[stats['estimate']['name']],stats['estimate']['value'] if stats['estimate']['value'] is not None else reason_text(stats['estimate']['reason'],language))
    effect_unit=result['variables'][0]['unit'] or local(('单位未填写','unit not specified'),language) if stats['estimate']['unit']=='outcome' else local(('无量纲','dimensionless'),language) if stats['estimate']['unit']=='dimensionless' else local(('不适用','not applicable'),language)
    add('comparison.estimate_unit',('效应量单位','Effect unit'),effect_unit)
    add('comparison.inference_summary',('推断算法配置','Inferential algorithm configuration'),inference_text(stats,language))
    add('comparison.confidence_interval',('置信区间','Confidence interval'),interval_text(stats['confidence_interval'],language))
    add('comparison.decision',('预设阈值判断','Prespecified threshold decision'),decision(stats['p_value']['value'],language))
    add('comparison.zero_count',('零差值完整对数','Complete pairs with zero difference'),stats['inference']['zero_count'])
    add('comparison.family.policy',('比较族校正','Comparison-family adjustment'),'Holm' if stats['family']['policy']=='all_pairs_holm' else local(('仅主要检验，无组对比较族','Primary test only, no pairwise family'),language))
    add('comparison.family.size',('预声明组对比较数','Predeclared pair comparisons'),stats['family']['size'])
    add('comparison.family.alpha',('显著性阈值','Significance threshold'),stats['family']['alpha'])
    add('comparison.interval_caveat',('区间校正说明','Interval adjustment caveat'),local(('逐比较普通 95% 区间未作同时校正；Holm 仅校正 P 值。','Ordinary individual 95% intervals have no simultaneous correction; Holm adjusts P values only.'),language) if stats['family']['policy']=='all_pairs_holm' else local(('适用区间为普通 95% 区间；没有同时置信覆盖声明。','Available intervals are ordinary 95% intervals; no simultaneous confidence coverage is claimed.'),language))
    add('comparison.warnings',('统计提示','Statistical notes'),'; '.join(local(WARNINGS.get(item,(item,item)),language) for item in stats.get('warnings',[])) or local(('无额外统计提示','No additional statistical notes'),language))
    required=['comparison.statistic','comparison.df_numerator','comparison.df_denominator','comparison.p_value','comparison.estimate','comparison.estimate_unit','comparison.confidence_interval','comparison.family.policy','comparison.family.size','comparison.family.alpha','comparison.interval_caveat','comparison.warnings']
    from app.domain.explanation_content import METRICS as ZH_METRICS
    from app.domain.descriptive_facts import METRICS as EN_METRICS
    for index,group in enumerate(result['groups']):
        add(f'groups.{index}.label',('分组或测量','Group or measurement'),group['label'])
        for key in ZH_METRICS: add(f'groups.{index}.{key}',(group['label']+'：'+ZH_METRICS[key],group['label']+': '+EN_METRICS[key]),group['statistics'][key])
        required.extend(f'groups.{index}.{key}' for key in ('label','n','mean','std','median'))
    if stats['design']=='paired': required.extend(['data.valid','comparison.zero_count','comparison.direction'])
    for index,pair in enumerate(stats['pairwise']):
        prefix=f'pairwise.{index}.'
        add(prefix+'label',('组对（左组减右组）','Pair (left minus right)'),names[pair['left_index']]+' - '+names[pair['right_index']])
        add(prefix+'method',('组对检验','Pair test'),local(METHODS[pair['method']],language))
        add(prefix+'statistic',('组对统计量 '+pair['statistic']['name'],'Pair statistic '+pair['statistic']['name']),pair['statistic']['value'])
        add(prefix+'df',('组对自由度','Pair degrees of freedom'),pair['statistic']['df_denominator'] if pair['statistic']['df_denominator'] is not None else local(('不适用','Not applicable'),language))
        effect=EFFECTS[pair['estimate']['name']]
        add(prefix+'estimate',('组对'+effect[0],'Pair '+effect[1].lower()),pair['estimate']['value'])
        add(prefix+'p_value',('组对原始 P 值','Raw pair P value'),pair['p_value']['value'])
        add(prefix+'adjusted_p_value',('Holm 校正 P 值','Holm-adjusted P value'),pair['adjusted_p_value'])
        add(prefix+'confidence_interval',('组对普通置信区间','Ordinary pair confidence interval'),interval_text(pair['confidence_interval'],language))
        add(prefix+'decision',('Holm 阈值判断','Holm threshold decision'),decision(pair['adjusted_p_value'],language,holm=True))
        add(prefix+'inference_summary',('组对推断算法','Pair inferential algorithm'),inference_text(pair,language))
        # Fixed compound facts keep all fifteen pairs within the frozen draft cap.
        # Separate raw/adjusted P references still have independent evidence keys.
        summary='; '.join(facts[prefix+key]['label']+': '+facts[prefix+key]['value'] for key in ('label','method','statistic','df','estimate','confidence_interval','decision','inference_summary'))
        add(prefix+'summary',('组对完整事实','Complete pair facts'),summary)
        required.extend(prefix+key for key in ('summary','p_value','adjusted_p_value'))
    variables=[f'variables.{index}.name' for index in range(len(result['variables']))]
    retained_fact_labels(facts, result, language)
    return {'schema_version':3,'language':language,'analysis_run_id':result['id'],'figure_id':figure['id'],
        'source_sha256':result['source_sha256'],'figure_sha256':figure['sha256'],'facts':facts,
        'required_references':{'purpose':variables,'data':['data.total','data.valid','data.excluded','data.exclusions'],
            'methods':['method.summary','comparison.assumptions','comparison.direction','comparison.inference_summary'], 'results':required,
            'interpretation':['comparison.decision','comparison.interval_caveat','comparison.warnings'],
            'paper_text':['figure.number','data.valid','comparison.method','comparison.direction','comparison.p_value','comparison.estimate','comparison.estimate_unit','comparison.confidence_interval','comparison.family.policy','comparison.family.size','comparison.interval_caveat']}}
