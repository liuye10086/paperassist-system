"""Independent readable expectations for actual legacy fact-builder shapes."""
from copy import deepcopy
import pytest
from app.domain.figure_workbench import explanations as e


def frozen(kind,lang):
    b={'figure':{'figure_kind':kind,'language':lang,'engine':{'id':'openai_figure_workbench_v2'},'presentation':{'schema_version':1,'axes':{'x':{'label':'Exposure','unit':''},'y':{'label':'Outcome','unit':''}}},'id':'f','sha256':'a'*64,'title':'Frozen figure'},'result':{'id':'r','source_sha256':'b'*64,'schema_version':5,'check':{'row_count':14,'valid_count':12,'excluded_count':2},'analysis_context':{'plan':{'research_request':{'output_language':lang}}},'variables':[{'name':'Outcome','unit':'kg'}]}}
    r=b['result'];r['selection']={'task_type':'roc','method':'roc_auc','missing_policy':'complete_cases','assumptions':{'independent_units':True,'inference_confirmed':True},'direction':'higher_is_positive','score_kind':'probability','evaluation_role':'external_validation','independence_confirmed':True}
    if kind=='roc_curve':
        r['result_type']='roc';r['statistics']={'method':'roc_auc','n':12,'positive_n':6,'negative_n':6,'auc':0.75,'direction':'higher_is_positive','evaluation_role':'external_validation','confidence_interval':{'low':0.5,'high':1.,'level':.95,'method':'delong_normal_clipped','reason':None},'warnings':['auc_not_clinical_utility','small_sample']}
    elif kind=='forest':
        r['result_type']='regression';r['selection'].update(task_type='regression',method='ols',covariates=[{'type':'continuous'}])
        r['statistics']={'method':'ols','coefficients':[{'term':'Exposure','beta':2.,'se':.2,'statistic':10.,'p_value':.001,'ci_low':1.6,'ci_high':2.4,'or_value':None,'or_ci_low':None,'or_ci_high':None}], 'n':12,'p':2,'df_residual':10,'r_squared':.8,'adjusted_r_squared':.78,'residual_sd':.5,'log_likelihood':None,'deviance':None,'aic':None,'diagnostics':{'rank':2,'centers':[0.],'scales':[1.],'condition_number':1.,'converged':True,'gradient_max':None},'warnings':['association_not_causation']}
    elif kind=='kaplan_meier':
        r['result_type']='survival';r['selection'].update(task_type='survival',method='kaplan_meier',noninformative_censoring=True)
        r['statistics']={'method':'kaplan_meier','time_unit':'day','groups':[{'label':'Control','n':12,'event_n':3,'censored_n':9,'max_time':10.,'median':None,'median_reason':'not_reached'}],'warnings':['no_between_group_test']}
    elif kind in ('scatter','correlation_heatmap'):
        r.update(result_type='correlation',schema_version=3)
        r['statistics']={'method':'pearson','mode':'matrix' if kind=='correlation_heatmap' else 'pair','n':12,'matrix':[[1.]],'coefficient':.5,'p_value':{'method':'pearson_beta_two_sided','value':.1,'reason':None},'inference':{},'confidence_interval':{'low':.1,'high':.8,'reason':None}}
    else:
        r.pop('result_type',None);r.update(schema_version=3,numeric_name='Outcome',group_name=None,overall={'n':12,'mean':4.,'std':1.,'min':1.,'q1':3.,'median':4.,'q3':5.,'max':7.,'iqr':2.},groups=[])
        r['selection'].update(unit='kg',sheet_name='Synthetic');b['figure']['series']=[]
    return b


@pytest.mark.parametrize('lang',['en','zh-CN'])
@pytest.mark.parametrize('kind',['boxplot','scatter','correlation_heatmap','forest','roc_curve','kaplan_meier'])
def test_six_original_kinds_have_readable_facts_and_preserve_raw(kind,lang):
    b=frozen(kind,lang);old=e._legacy_payload(b);p=e.build_payload(b)
    for key,fact in old['facts'].items():assert p['facts'][key]['raw']==fact['raw']
    assert p['facts']['axis.x.unit']['value']==('Unit not specified' if lang=='en' else '单位未提供')
    if kind in ('forest','roc_curve'):
        assert p['facts']['modeling.n']['label']==('Valid records' if lang=='en' else '有效记录数')
    if kind=='roc_curve':
        assert p['facts']['modeling.auc']['label']==('AUC' if lang=='en' else '曲线下面积')
        assert p['facts']['modeling.positive_n']['label']==('Positive records' if lang=='en' else '阳性记录数')
        text=p['facts']['modeling.coding']['value']
        assert ('Evaluation role: External validation' if lang=='en' else '评估角色: 外部验证') in text
        assert ('Independence confirmed: Yes' if lang=='en' else '独立性已声明确认: 是') in text
    for fact in p['facts'].values():
        assert not any(token in fact['label']+' '+fact['value'] for token in ('task_type','evaluation_role','independence_confirmed','positive_n','df_residual','ci_low','or_ci_high'))
        if isinstance(fact['raw'],(dict,list)):
            assert not any(c in fact['value'] for c in '{}[]')


def test_line_omits_default_bar_rule_and_missing_unit_preserves_dimensionless_scale():
    from app.domain.figure_workbench.explanation_facts import build_payload
    b=frozen('line','en');b['projection']={'result':{'method':{'kind':'line','aggregation':'unique','bar_stat':'count','error_bars':'none','missing_group':'block','x_type':'numeric'}}}
    base={'schema_version':2,'language':'en','facts':{},'required_references':{k:[] for k in ('purpose','data','methods','results','interpretation','paper_text')}}
    p=build_payload(b,base)
    assert 'method.rule.bar_stat' not in p['facts']
    assert 'method.rule.error_bars' not in p['facts']
    b['figure']['presentation']['axes']['y']['unit']='0–1'
    assert build_payload(b,base)['facts']['axis.y.unit']['value']=='0–1'

def test_projection_precision_limit_matches_eight_digit_display():
    from app.domain.figure_workbench.explanation_facts import limitations
    b=frozen('line','en');b['result']['result_type']='regression'
    assert any('8 significant digits' in text and '6 significant digits' in text for text in limitations(b))
    assert not any(text.startswith('Display uses at most six') for text in limitations(b))
