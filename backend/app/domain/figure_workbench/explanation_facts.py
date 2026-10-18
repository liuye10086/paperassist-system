"""Allowlisted, frozen facts for the v2 figure explanation contract."""
from copy import deepcopy
import re
from app.core.exceptions import StorageError, PlotError

# All text in this module is program-owned. User research prose stays local.
LABELS = {
 'group':('分组','Group label'),'category':('类别','Category label'),
 'x':('横坐标值','Horizontal coordinate'),'y':('纵坐标值','Vertical coordinate'),
 'n':('投影记录数','Projection records'),'missing':('缺失记录数','Missing records'),
 'value':('绘图统计值','Plotted statistic'),'denominator':('比例分母记录数','Proportion denominator records'),
 'sd':('样本标准差','Sample standard deviation'),'reason':('不可计算原因','Reason unavailable'),
 'bandwidth':('核密度带宽','Density bandwidth'),'min':('观察最小值','Observed minimum'),
 'max':('观察最大值','Observed maximum'),'q1':('下四分位数','Lower quartile'),
 'median':('中位数','Median value'),'q3':('上四分位数','Upper quartile')}
REASONS={
 'insufficient_n_for_sd':('有效记录不足两条，无法计算样本标准差。','Fewer than two valid records; sample standard deviation cannot be computed.'),
 'no_valid_values':('无有效数值，无法计算统计值。','No valid values; the statistic cannot be computed.')}
STRUCTURES={
 'unknown':('观察结构未提供','Observation structure not provided'),
 'independent':('用户声明独立观察；程序未验证独立性','User-declared independent observations; independence was not verified'),
 'paired':('用户声明配对观察；配对有效性仍需研究者核查','User-declared paired observations; pairing requires researcher review'),
 'repeated':('用户声明重复观察；绘图投影未建模重复测量依赖','User-declared repeated observations; projection does not model repeated-measure dependence')}


def build_payload(bundle, legacy, *, contract=2):
    f=bundle['figure'];r=bundle['result'];zh=f['language']=='zh-CN';i=0 if zh else 1
    p=deepcopy(legacy);p['figure_explanation_contract']=contract
    facts=p['facts'];req=p['required_references']
    _readable_legacy(facts,zh)
    if contract==4:
        declared='用户声明的评估角色（未经程序核验）' if zh else 'User-declared evaluation role (not programmatically verified)'
        if 'modeling.evaluation_role' in facts: facts['modeling.evaluation_role']['label']=declared
        coding=facts.get('modeling.coding')
        if coding and isinstance(coding['raw'],dict) and 'evaluation_role' in coding['raw']:
            coding['value']=coding['value'].replace(('评估角色' if zh else 'Evaluation role')+': ',declared+': ')
    def add(key,zhlabel,enlabel,value,display=None):
        facts[key]={'label':zhlabel if zh else enlabel,'raw':value,'value':display if display is not None else ('未提供' if zh else 'Not provided') if value is None else format(value,'.8g') if type(value) is float else str(value)}
    for axis in ('x','y'):
        for field in ('label','unit'):
            add(f'axis.{axis}.{field}',('横轴' if axis=='x' else '纵轴')+('字段' if field=='label' else '单位'),('Horizontal' if axis=='x' else 'Vertical')+(' field' if field=='label' else ' unit'),f['presentation']['axes'][axis].get(field),('单位未提供' if zh else 'Unit not specified') if field=='unit' and not f['presentation']['axes'][axis].get(field) else None)
            req['data'].append(f'axis.{axis}.{field}')
    projection=bundle.get('projection',{}).get('result',{})
    if f['figure_kind'] in ('line','bar','violin'):
        method=projection['method'];kind=f['figure_kind']
        if kind=='line':
            summary=('按确认横轴顺序绘制；重复横坐标采用算术均值聚合。' if method.get('aggregation')=='mean' else '按确认横轴顺序绘制；每个分组横坐标要求唯一。') if zh else ('Confirmed horizontal order; duplicate coordinates use arithmetic mean aggregation.' if method.get('aggregation')=='mean' else 'Confirmed horizontal order; each group coordinate must be unique.')
            summary+=('缺失值保留断线；不进行重复测量推断。' if zh else ' Missing values break lines; no repeated-measures inference is performed.')
        elif kind=='bar':
            stat=method.get('bar_stat','count')
            summary={'count':('按纳入记录计数，不代表唯一受试者人数。','Counts included records, which need not be unique participants.'),'proportion':('按确认类别范围内同组有效记录为分母计算比例。','Proportions use valid records within confirmed categories and the same group as denominator.'),'mean':('按类别计算算术均值；适用误差线为样本标准差，分母为n−1，不是置信区间。','Arithmetic means by category; applicable error bars are sample standard deviations using n−1, not confidence intervals.')}[stat][i]
        else:
            summary=('等权Gaussian核密度，Scott带宽，256点网格，在观察范围截断，采用共用密度宽度；叠加线性插值四分位数，密度不是发生概率。','Equal-weight Gaussian density, Scott bandwidth, 256-point grid, observed-range truncation and shared density width; linear-interpolated quartiles; density is not event probability.')[i]
        summary+=('绘图投影为描述性结果，不增加统计检验或因果证据。' if zh else ' Projection is descriptive and adds no statistical tests or causal evidence.')
        add('method.summary','投影计算方法与限制','Projection method and restrictions',summary)
        for key,fact in list(facts.items()):
            if not key.startswith('projection.'):continue
            name=key.rsplit('.',1)[-1]
            if name in LABELS:fact['label']=LABELS[name][i]
            if name=='reason':fact['value']=REASONS.get(fact['raw'],('未记录不可计算原因','No unavailable reason recorded'))[i]
        # Only a closed vocabulary of rules is forwarded; no source coordinates or paths.
        for name,labels in {'aggregation':('横坐标聚合规则','Coordinate aggregation rule'),'bar_stat':('柱状统计规则','Bar statistic rule'),'error_bars':('误差线规则','Error bar rule'),'missing_group':('缺组处理规则','Missing group rule'),'x_type':('横坐标类型','Horizontal coordinate type')}.items():
            if name in ('bar_stat','error_bars') and kind!='bar':continue
            if name in ('aggregation','x_type') and kind!='line':continue
            value=method.get(name)
            displays={'unique':('每组横坐标唯一','Unique coordinates within group'),'mean':('算术均值','Arithmetic mean'),'count':('纳入记录计数','Included record count'),'proportion':('确认范围内同组比例','Within-group proportion in confirmed scope'),'none':('无误差线','No error bars'),'sd':('样本标准差','Sample standard deviation'),'block':('缺组时阻断','Block on missing group'),'exclude':('排除缺组记录','Exclude missing-group records'),'numeric':('数值坐标','Numeric coordinates'),'datetime':('日期时间坐标','Date-time coordinates'),'ordered':('确认有序坐标','Confirmed ordered coordinates')}
            if value in displays:
                add('method.rule.'+name,*labels,value,displays[value][i]);req['methods'].append('method.rule.'+name)
    request=r.get('analysis_context',{}).get('plan',{}).get('research_request',{})
    structure=request.get('observation_structure','unknown')
    if structure not in STRUCTURES:structure='unknown'
    add('design.structure','观察结构及核查限制','Observation structure and verification limits',structure,STRUCTURES[structure][i])
    # Presence is safe to forward, arbitrary study_design/question text is not.
    design_provided=bool(str(request.get('study_design','')).strip())
    add('design.status','研究设计资料状态','Research design information status',design_provided,('用户提供研究设计文字，尚未经程序验证；未外发该原文。','Research design text was supplied but was not programmatically verified or forwarded.')[i] if design_provided else ('研究设计未提供，不推断随机化、因果或受试者独立性。','Research design not provided; randomization, causation and participant independence cannot be assumed.')[i])
    for key in ('design.structure','design.status'):
        req['methods'].append(key);req['interpretation'].append(key)
    for index,note in enumerate(limitations_v4(bundle) if contract==4 else limitations(bundle)):
        key=f'limitation.{index}';add(key,'适用限制','Applicable limitation',note);req['interpretation'].append(key)
    if len(facts)>500:raise StorageError('explanation_input_limit','图表事实过多，请缩小图表范围再生成解释。',422)
    return p


def limitations(bundle):
    from app.domain.explanation_content import limitations_for
    from app.domain.artifact_contracts import verification_note
    f=bundle['figure'];zh=f['language']=='zh-CN'
    if f['figure_kind'] in ('line','bar','violin'):
        limits=[('绘图投影仅为描述统计，不提供新增P值、置信区间或因果证据。' if zh else 'Projection is descriptive; it supplies no additional P values, confidence intervals or causal evidence.'),('原统计有效记录数与投影有效记录数属于不同人群口径；记录数不等于独立受试者人数。' if zh else 'Original statistical records and projection records use different population definitions; record counts need not equal independent participant counts.')]
        if f['figure_kind']=='line':limits.append('折线不提供重复测量模型，连线不证明时间效应。' if zh else 'Lines do not fit repeated-measures models or establish temporal effects.')
        if f['figure_kind']=='bar':limits.append('比例分母限于确认类别内同组有效记录；标准差不等于置信区间，记录不足时不绘制标准差。' if zh else 'Proportion denominators use same-group valid records in confirmed categories; standard deviation is not a confidence interval and is unavailable with insufficient records.')
        if f['figure_kind']=='violin':limits.append('核密度受带宽与观察范围截断影响，不是推断检验或发生概率。' if zh else 'Density depends on bandwidth and observed-range truncation; it is not an inferential test or event probability.')
        if bundle['result'].get('result_type') in ('regression','roc','survival','group_comparison','correlation'):
            limits.extend(limitations_for(bundle['result'],f['language']))
        limits=[text for text in limits if not re.search(r'(?:[Dd]isplay.*(?:six|6).*significant digits|显示.*(?:六|6).*有效数字)',text)]
        if f['figure_kind']=='line' and (f.get('engine',{}).get('id'),f.get('presentation',{}).get('schema_version'))==('openai_figure_workbench_v3',2):
            limits.append('完整有序坐标保留完整保存精度；其它投影摘要最多显示8位有效数字，原统计结果说明最多显示6位有效数字。' if zh else 'Complete ordered coordinates retain full saved precision; other projection summaries display at most 8 significant digits and original statistical summaries at most 6 significant digits.')
        else:
            limits.append('投影事实最多显示8位有效数字；原统计结果说明最多显示6位有效数字，完整数值以保存结果为准。' if zh else 'Projection facts display at most 8 significant digits; original statistical result summaries display at most 6 significant digits. Saved results retain full precision.')
    else:limits=limitations_for(bundle['result'],f['language'])
    limits=list(limits)+[('研究设计及观察独立性未由程序验证；设计缺失时不作假设，不能据此推断因果。' if zh else 'Research design and observation independence were not programmatically verified; absent design is not assumed and causation cannot be inferred.'),verification_note(f['language'],explanation=True)]
    structure=bundle['result'].get('analysis_context',{}).get('plan',{}).get('research_request',{}).get('observation_structure','unknown')
    limits.append(STRUCTURES.get(structure,STRUCTURES['unknown'])[0 if zh else 1])
    limits.append('本解释仅核对冻结统计与元数据，未验证图片像素、图中文字或视觉正确性；AI初稿仍需人工审阅。' if zh else 'This explanation checks frozen statistics and metadata only; image pixels, in-image text and visual correctness were not verified. The AI draft requires human review.')
    return list(dict.fromkeys(limits))


def limitations_v4(bundle):
    """Only new facts distinguish supplied declarations from verification."""
    notes=limitations(bundle)
    request=bundle['result'].get('analysis_context',{}).get('plan',{}).get('research_request',{})
    provided=bool(str(request.get('study_design','')).strip())
    zh=bundle['figure']['language']=='zh-CN'
    old=('研究设计、样本来源、实验步骤及测量背景尚未提供，具体研究目的与方法细节待补充。' if zh else
         'Research design and measurement details require researcher review; no unconfirmed research text was sent automatically.')
    if zh:
        note=('用户已提供研究设计文字，程序未验证该声明；样本来源、实验步骤和测量背景仍需研究者核查，未外发研究设计原文。' if provided else
              '研究设计文字未提供；样本来源、实验步骤和测量背景仍需研究者核查，不据此推断设计或观察独立性。')
    else:
        note=('Research design text was supplied but was not verified or forwarded; researchers must review sample provenance, procedures and measurement context.' if provided else
              'Research design text was not supplied; sample provenance, procedures and measurement context require researcher review. Design and observation independence cannot be assumed.')
    return [note if value==old else value for value in notes]


def validate_draft(draft,payload):
    from app.domain.explanation_content import TOKEN
    # Methods and citations must come from bound facts, just like numerical assertions.
    forbidden=re.compile(r'\b(?:according to|et\s+al\b|doi\b|https?://|randomi[sz]\w*|observational|prospective|retrospective|cross.sectional|cohort|independen(?:t|ce)|clinical[ -]trial|trial|(?:single|double|triple)[ -]blind(?:ed)?|blind(?:ed|ing)?|interventional|t.test|anova|regression|bootstrap|imput\w*|causes?|caused|leads?\s+to)\b|前瞻性|回顾性|观察性|独立|临床试验|干预研究|单盲|双盲|三盲|盲法|随机(?:对照|分配|试验)|队列研究|横断面|回归分析|文献|参考文献|插补|导致|引起',re.I)
    if isinstance(draft,dict):
        for text in draft.values():
            if isinstance(text,str) and forbidden.search(TOKEN.sub('',text)):
                raise PlotError('explanation_invalid','解释含未绑定的研究设计、方法、因果或引用断言。解释未保存，请重新生成。')

# Additional v2 display vocabulary for frozen modeling facts. Numeric raw values remain intact.
_MODEL_LABELS={
 'n':('有效记录数','Valid records'),'positive_n':('阳性记录数','Positive records'),'negative_n':('阴性记录数','Negative records'),
 'auc':('曲线下面积','AUC'),'p':('模型参数数','Model parameter count'),'df_residual':('残差自由度','Residual degrees of freedom'),
 'r_squared':('决定系数','R squared'),'adjusted_r_squared':('调整决定系数','Adjusted R squared'),'residual_sd':('残差标准差','Residual standard deviation'),
 'log_likelihood':('对数似然','Log likelihood'),'deviance':('偏差','Deviance'),'aic':('Akaike信息准则','Akaike information criterion'),
 'diagnostics':('模型诊断','Model diagnostics'),'direction':('分数方向','Score direction'),'evaluation_role':('评估角色','Evaluation role'),
 'task_type':('分析任务类型','Analysis task type'),'independence_confirmed':('独立性已声明确认','Independence confirmed'),
 'independent_units':('独立观察单位声明','Independent-unit declaration'),'inference_confirmed':('推断前提已声明确认','Inference-assumption declaration'),
 'noninformative_censoring':('非信息删失声明','Noninformative-censoring declaration'),'score_kind':('分数类型','Score type'),
 'covariate_types':('协变量类型','Covariate types'),'beta':('回归系数','Regression coefficient'),'se':('标准误','Standard error'),
 'statistic':('检验统计量','Test statistic'),'ci_low':('置信下限','Confidence lower bound'),'ci_high':('置信上限','Confidence upper bound'),
 'or_value':('比值比','Odds ratio'),'or_ci_low':('比值比置信下限','Odds-ratio confidence lower bound'),'or_ci_high':('比值比置信上限','Odds-ratio confidence upper bound'),
 'rank':('矩阵秩','Matrix rank'),'centers':('中心化常数','Centering constants'),'scales':('缩放常数','Scaling constants'),
 'condition_number':('条件数','Condition number'),'converged':('已收敛','Converged'),'gradient_max':('最大梯度','Maximum gradient'),
 'event_n':('事件记录数','Event records'),'censored_n':('删失记录数','Censored records'),'max_time':('最长观察时间','Maximum observed time'),
 'median_reason':('中位生存时间缺失原因','Median survival time unavailable reason'),'time_unit':('时间单位','Time unit'),
 'coding':('确认的角色、编码及声明','Confirmed roles, coding and declarations')}
_MODEL_VALUES={
 'roc':('ROC分析','ROC analysis'),'regression':('回归分析','Regression analysis'),'survival':('生存分析','Survival analysis'),
 'roc_auc':('ROC曲线下面积','ROC area under the curve'),'external_validation':('外部验证','External validation'),
 'held_out_validation':('留出验证','Held-out validation'),'apparent_exploratory':('表观探索评估','Apparent exploratory evaluation'),
 'higher_is_positive':('较高分数为阳性','Higher scores indicate positive outcomes'),'lower_is_positive':('较低分数为阳性','Lower scores indicate positive outcomes'),
 'probability':('概率分数','Probability score'),'general':('一般分数','General score'),
 'continuous':('连续变量','Continuous variable'),'categorical':('分类变量','Categorical variable'),
 'delong_normal_clipped':('DeLong正态区间并裁剪至零一范围','DeLong normal interval clipped to the unit range'),
 'evaluation_role_not_independent':('评估角色不支持独立验证区间','Evaluation role does not support an independent-validation interval'),
 'insufficient_class_size':('类别记录不足，无法计算区间','Insufficient records per class for an interval'),
 'degenerate_delong_variance':('DeLong方差退化，无法计算区间','Degenerate DeLong variance; interval unavailable'),
 'not_reached':('未达到中位生存时间','Median survival time not reached'),
 'auc_not_clinical_utility':('AUC不等于临床实用性','AUC does not establish clinical utility'),
 'complete_case_selection_bias':('完整记录分析可能存在选择偏倚','Complete-case analysis may introduce selection bias'),
 'association_not_causation':('关联不证明因果','Association does not establish causation'),
 'unadjusted_coefficient_inference':('系数推断未作多重比较校正','Coefficient inference has no multiple-comparison adjustment'),
 'small_residual_df':('残差自由度较少','Few residual degrees of freedom'),'influence_screening':('存在需审阅的影响诊断候选','Influence diagnostics identify observations requiring review'),
 'sparse_data':('数据稀疏，估计需谨慎','Sparse data; interpret estimates cautiously'),
 'pointwise_intervals':('区间为逐时点区间，不是同时置信带','Intervals are pointwise, not simultaneous confidence bands'),
 'no_between_group_test':('未进行组间生存检验','No between-group survival test was performed'),'zero_time':('包含零时点记录','Records include zero follow-up times')}


def _readable_legacy(facts,zh):
    from app.adapters.collection_labels import LABELS,VALUES
    i=0 if zh else 1;labels={**LABELS,**_MODEL_LABELS};values={**VALUES,**_MODEL_VALUES}
    def label(key):return labels.get(key,(key.replace('_',' '),key.replace('_',' ').capitalize()))[i]
    def scalar(value):
        if value is None:return '未提供或无法计算' if zh else 'Unavailable or not supplied'
        if isinstance(value,bool):return ('是' if value else '否') if zh else ('Yes' if value else 'No')
        if isinstance(value,str):return values.get(value,(value,value))[i]
        return format(value,'.6g') if type(value) is float else str(value)
    def flatten(value,path=''):
        if isinstance(value,dict):
            for key,entry in value.items():yield from flatten(entry,(path+' / ' if path else '')+label(key))
        elif isinstance(value,list):
            for index,entry in enumerate(value,1):yield from flatten(entry,path+' '+str(index))
        else:yield (path+': ' if path else '')+scalar(value)
    for key,fact in facts.items():
        if not key.startswith('modeling.'):continue
        name=key.rsplit('.',1)[-1]
        if name in labels:fact['label']=label(name)
        if key.startswith('modeling.groups.'):
            prefix=('组 ' if zh else 'Group ')+str(int(key.split('.')[2])+1)+': '
            fact['label']=prefix+label(name)
        if isinstance(fact['raw'],(dict,list)):
            fact['value']='; '.join(flatten(fact['raw'])) or ('无' if zh else 'None')
        elif name in ('direction','evaluation_role','median_reason'):
            fact['value']=scalar(fact['raw'])
        elif name=='warnings':
            fact['value']='; '.join(scalar(part.strip()) for part in str(fact['raw']).split(';'))
        if key in ('data.total','data.valid','data.excluded'):fact['label']=label(key.split('.')[-1])
