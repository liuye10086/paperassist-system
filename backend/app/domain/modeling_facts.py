"""Program-owned typed facts for fixed OLS/logistic, ROC and KM results."""
from app.domain.dataset_processing import analysis_stage_text, retained_fact_labels
import json
from app.domain.artifact_contracts import artifact_language,modeling_artifact


def limitations(result,language):
    zh=language=='zh-CN';kind=result['result_type']
    common=['研究声明为用户提供；程序不证明研究设计或样本真实性。','完整记录分析可能产生选择偏倚；未插补、去重或删除离群值。','数值显示最多六位有效数字；完整值以保存统计为准。','解释为初稿；图片像素与语义须人工审阅。'] if zh else [
        'Research declarations are supplied by the user; the program does not establish design or sample authenticity.',
        'Complete-case analysis may introduce selection bias; no imputation, deduplication or outlier removal.',
        'Display uses at most six significant digits; saved statistics retain full precision.',
        'Interpretation is a draft; image pixels and wording require review.']
    common.append(({'regression':'森林图核对仅为本地效应投影与渲染，并未云端独立重拟合；关联不能证明因果。',
        'roc':'ROC 仅评估已冻结分数；区间和评估声明不证明独立外部验证，未优化阈值。',
        'survival':'右删失 KM 依赖非信息删失声明；未进行 log-rank、Cox 或竞争风险分析。'} if zh else {
        'regression':'Forest verification covers local effects and rendering, without an independent cloud model refit; association does not establish causation.',
        'roc':'ROC evaluates frozen scores only; intervals and evaluation declarations do not establish independent external validation. No threshold optimization.',
        'survival':'Right-censored KM relies on the noninformative censoring declaration; no log-rank, Cox or competing-risk analysis.'})[kind])
    return [analysis_stage_text(line, result) for line in common]


def method_summary(result,language):
    zh=language=='zh-CN';stats=result['statistics'];method=stats['method']
    if method=='roc_auc' and stats['confidence_interval']['low'] is None:
        return ('冻结分数 ROC；并列分数共同跨阈值，梯形 AUC；本次不提供AUC区间，原因见统计结果。未优化阈值或训练模型。' if zh else
            'Frozen-score ROC with tied scores crossing thresholds together and trapezoidal AUC. No AUC interval is supplied; the reason is recorded with the result. No threshold optimization or model training.')
    summaries={
      'ols':('含截距普通最小二乘；连续变量按原尺度、分类变量按已确认参照水平编码；双侧 t 推断和普通协方差。','Ordinary least squares with intercept, original continuous scales and confirmed categorical references; two-sided t inference and ordinary covariance.'),
      'logistic':('含截距二元 Logistic；按已确认阳性结局编码；最大似然、普通协方差与双侧 Wald 推断；优势比为系数指数变换。','Binary logistic regression with intercept and confirmed positive outcome coding; maximum likelihood, ordinary covariance and two-sided Wald inference; odds ratios exponentiate coefficients.'),
      'roc_auc':('冻结分数 ROC；并列分数共同跨阈值，梯形 AUC；DeLong 正态区间裁剪至零一范围，未优化阈值或训练模型。','Frozen-score ROC with tied scores crossing thresholds together, trapezoidal AUC and DeLong normal interval clipped to the unit range; no threshold optimization or model training.'),
      'kaplan_meier':('右删失 Kaplan–Meier；同一时点先处理事件再撤出删失；Greenwood 方差及对数对数区间；不进行组间检验。','Right-censored Kaplan-Meier; events precede censor withdrawal at tied times; Greenwood variance and log-log intervals; no between-group test.')}
    return summaries[method][0 if zh else 1]


def build_payload(result,figure):
    modeling_artifact(result);language=artifact_language(result);zh=language=='zh-CN';stats=result['statistics'];kind=result['result_type'];facts={}
    def add(key,zh_label,en_label,value):
        display=('无法计算或未提供' if zh else 'Unavailable or not supplied') if value is None else format(value,'.6g') if type(value) is float else str(value)
        def readable(item):
            if type(item) is float:return format(item,'.6g')
            if isinstance(item,dict):return {k:readable(v) for k,v in item.items()}
            if isinstance(item,list):return [readable(v) for v in item]
            return item
        if isinstance(value,(dict,list)):
            display=json.dumps(readable(value),ensure_ascii=False,allow_nan=False,sort_keys=True)
        facts[key]={'label':zh_label if zh else en_label,'value':display,'raw':value}
    add('method.summary','分析方法','Analysis method',method_summary(result,language))
    add('figure.number','图号','Figure number',figure['figure_number']);add('figure.title','图标题','Figure title',figure['title'])
    add('modeling.variables','变量与单位','Variables and units','; '.join(v['name']+' ('+v['unit']+')' for v in result['variables']))
    # Coding is represented by program-owned statements, never free AI inference.
    selection={k:v for k,v in result['selection'].items() if k in ('task_type','method','missing_policy','assumptions','direction','score_kind','evaluation_role','independence_confirmed','noninformative_censoring')}
    if kind=='regression': selection['covariate_types']=[c['type'] for c in result['selection'].get('covariates',[])]
    add('modeling.coding','确认的角色、编码及声明','Confirmed roles, coding and declarations',selection)
    for key,source in [('total','row_count'),('valid','valid_count'),('excluded','excluded_count')]: add('data.'+key,'数据记录 '+key,'Data records '+key,result['check'][source])
    results=[]
    def metric(key,label,value):
        full='modeling.'+key;add(full,label,label,value);results.append(full)
    if kind=='regression':
        for i,c in enumerate(stats['coefficients']):
            prefix=f'coefficients.{i}.'
            inference={k:c[k] for k in ('beta','se','statistic','p_value','ci_low','ci_high','or_value','or_ci_low','or_ci_high')}
            metric(prefix+'inference',c['term'],inference)
        for key in ('n','p','df_residual','r_squared','adjusted_r_squared','residual_sd','log_likelihood','deviance','aic'): metric(key,key,stats[key])
        metric('diagnostics','诊断' if zh else 'Diagnostics',{k:v for k,v in stats['diagnostics'].items() if k not in ('residuals','fitted','leverage','cooks_distance')})
    elif kind=='roc':
        for key in ('n','positive_n','negative_n','auc','direction','evaluation_role'): metric(key,key,stats[key])
        metric('confidence_interval','AUC 区间及原因' if zh else 'AUC interval and reason',stats['confidence_interval'])
    else:
        metric('time_unit','时间单位' if zh else 'Time unit',stats['time_unit'])
        for i,g in enumerate(stats['groups']):
            for key in ('label','n','event_n','censored_n','max_time','median','median_reason'): metric(f'groups.{i}.'+key,key,g[key])
    metric('warnings','计算警告' if zh else 'Computation warnings','; '.join(stats['warnings']) or ('无' if zh else 'None'))
    retained_fact_labels(facts, result, language)
    return {'schema_version':4,'language':language,'analysis_run_id':result['id'],'figure_id':figure['id'],
        'source_sha256':result['source_sha256'],'figure_sha256':figure['sha256'],'facts':facts,
        'required_references':{'purpose':['modeling.variables'],'data':['data.total','data.valid','data.excluded'],
            'methods':['method.summary','modeling.coding'],'results':results,'interpretation':['modeling.warnings'],
            'paper_text':['figure.number','figure.title','method.summary','data.valid']}}
