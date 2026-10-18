"""Minimal version-four drawing materials; never send local expected curves."""
from copy import deepcopy
import math
from importlib import import_module
from app.core.exceptions import StorageError
from app.domain.artifact_contracts import artifact_language,figure_kind,modeling_artifact


def load_input(assets,project_id,file_id,result):
    if not modeling_artifact(result):
        raise StorageError('task_source_conflict','未知建模来源类型。',409)
    kind=result['result_type']
    return getattr(import_module('app.domain.'+kind+'.service'),'load_'+kind+'_input')(assets,project_id,file_id,result)


def projection(result,labels):
    stats=result['statistics']; kind=result['result_type']
    if kind=='regression':
        logistic=stats['method']=='logistic'
        rows=[]
        for i,coefficient in enumerate(stats['coefficients']):
            if coefficient['column'] is None: continue
            name=labels[f'effect:{i}']
            rows.append({'term':f'effect:{i}','label':name,'unit':labels['unit:'+coefficient['column']],
                'estimate':coefficient['or_value'] if logistic else coefficient['beta'],
                'ci_low':coefficient['or_ci_low'] if logistic else coefficient['ci_low'],
                'ci_high':coefficient['or_ci_high'] if logistic else coefficient['ci_high'],
                'interval_reason':None if coefficient['ci_low'] is not None else 'unavailable'})
        return {'n':stats['n'],'effects':rows}
    if kind=='roc':
        return {key:deepcopy(stats[key]) for key in ('n','positive_n','negative_n','auc','points')}
    return {'n':stats['n'],'groups':[{'label':labels[f'group:{i}'],**{key:deepcopy(group[key]) for key in
        ('n','event_n','censored_n','max_time','points','risk_table')}} for i,group in enumerate(stats['groups'])]}


def build_material(result,rows,*,external=None):
    from app.domain.external_material import contract_labels
    if not modeling_artifact(result) or external is None:
        raise StorageError('task_source_conflict','建模图必须确认本次必要外发范围。',409)
    labels=contract_labels(result,None,external,'boxplot')
    stats=result['statistics']; kind=result['result_type']; language=artifact_language(result)
    if not isinstance(rows,list) or len(rows)!=stats['n'] or not rows:
        raise StorageError('result_mismatch','绘图记录数与已保存结果不一致。',409)
    variables=[{'column':v['column'],'name':labels['field:'+v['column']],'unit':labels['unit:'+v['column']]} for v in result['variables'] if v['column']!=result['selection'].get('id_column')]
    scope='local_effect_projection' if kind=='regression' else 'independent_curve_calculation'
    config={'verification_scope':scope,'outliers_removed':False,'inference_displayed':kind=='regression'}
    if kind=='regression': config.update(scale='log' if stats['method']=='logistic' else 'linear',reference_line=1. if stats['method']=='logistic' else 0.)
    elif kind=='roc': config.update(direction=stats['direction'],threshold_endpoints='null_with_threshold_kind',ties='joint_threshold')
    else: config.update(time_unit=labels['unit:'+result['selection']['time_column']],ties='events_before_censoring',interval='greenwood_loglog_95',origin='survival_one_at_zero')
    zh=language=='zh-CN'
    title=('图 1. ' if zh else 'Figure 1. ')+({'regression':'本地效应森林图','roc':'ROC 曲线','survival':'Kaplan–Meier 生存曲线'} if zh else
        {'regression':'Local effect forest plot','roc':'ROC curve','survival':'Kaplan–Meier survival curve'})[kind]
    caption=(f'纳入 {stats["n"]} 条完整记录；排除 {result["check"]["excluded_count"]} 行。' if zh else
        f'{stats["n"]} complete observations; {result["check"]["excluded_count"]} excluded rows. ')
    caption+=('森林图仅核对本地效应投影与绘图，不独立重新拟合回归。' if zh else 'Forest verification covers local effect projection and rendering; regression is not independently refitted.') if kind=='regression' else (
        '云端根据匿名必要数值独立计算曲线；期望曲线仅保留本地。' if zh else 'Cloud curves are independently computed from necessary anonymous observations; expected curves remain local.')
    if kind=='roc': caption+=(' 评估角色：' if zh else ' Evaluation role: ')+stats['evaluation_role']
    text={'title':title,'x_label':('效应' if zh else 'Effect') if kind=='regression' else ('假阳性率' if zh else 'False positive rate') if kind=='roc' else config['time_unit'],
        'y_label':('变量' if zh else 'Variable') if kind=='regression' else ('真阳性率' if zh else 'True positive rate') if kind=='roc' else ('生存概率' if zh else 'Survival probability'),'caption':caption}
    base={'schema_version':4,'figure_kind':figure_kind(result),'language':language,'variables':variables,'plot_config':config}
    numeric=projection(result,labels)
    payload={**deepcopy(base),'labels':text,'method':stats['method']}
    if kind=='regression': payload.update(effects=deepcopy(numeric['effects']),sample_count=stats['n'])
    else:
        fields=('outcome','score') if kind=='roc' else ('time','event','group')
        try:
            observations=[{key:row[key] for key in fields} for row in rows]
            if kind=='roc' and any(type(r['outcome']) is not int or r['outcome'] not in (0,1) or type(r['score']) not in (int,float) or not math.isfinite(r['score']) for r in observations): raise ValueError()
            if kind=='survival' and any(type(r['event']) is not bool or type(r['group']) is not int or not 0<=r['group']<len(stats['groups']) or type(r['time']) not in (int,float) or not math.isfinite(r['time']) or r['time']<0 for r in observations): raise ValueError()
        except (KeyError,TypeError,ValueError):
            raise StorageError('result_mismatch','绘图必要数值编码无效。',409) from None
        payload['observations']=observations
        if kind=='survival': payload['group_labels']=[labels[f'group:{i}'] for i in range(len(stats['groups']))]
    return payload,{**deepcopy(base),**text,'statistics':numeric}


def validate_figure_source(assets,project_id,file_id,result,figure):
    from app.adapters.openai_plot import plot_differences
    from app.domain.artifact_contracts import figure_renderer
    try:
        data=load_input(assets,project_id,file_id,result)
        _,expected=build_material(result,data['rows'],external=figure.get('external_processing'))
        expected.update(method={'id':result['statistics']['method'],'verification_scope':expected['plot_config']['verification_scope']},
            engine={'id':figure_renderer(result),'provider':'openai_code_interpreter'},figure_number=1,
            plan_sha256=result['analysis_plan']['sha256'],verification={'status':'matched'})
        if plot_differences(figure,expected): raise ValueError('Projection changed')
    except (KeyError,TypeError,ValueError,StorageError) as exc:
        raise StorageError('source_conflict','建模图与冻结统计或已确认标签不一致。',409) from exc
