from copy import deepcopy
from tests.domain.test_correlation_artifacts import result as research_result


def result():
    value=research_result()
    value.pop('result_type'); value.pop('variables'); value.pop('statistics')
    value.update(numeric_name='Concentration',group_name=None,groups=[],
        overall={'n':4,'mean':2.5,'std':1.2909944487358056,'min':1.,'q1':1.75,'median':2.5,'q3':3.25,'max':4.,'iqr':1.5,'warnings':[]})
    value['selection']={'task_type':'descriptive_boxplot','sheet_name':'Sheet','numeric_column':'A','group_column':None,'unit':'mg/L'}
    return value


def test_english_boxplot_fixed_text_and_ungrouped_series_are_english():
    from app.domain.boxplot import plot_data
    figure=plot_data(result(),[1.,2.,3.,4.],{})
    assert figure['language']=='en' and figure['title']=='Figure 1. Concentration boxplot'
    assert figure['series'][0]['label']=='Overall'
    assert not any('\u4e00'<=char<='\u9fff' for char in figure['caption'])


def test_english_descriptive_facts_have_english_method_labels_and_null_display():
    from app.domain.explanation_content import build_payload,render_explanation
    value=result(); value['overall']['std']=None
    figure={'id':'figure','title':'Figure 1','figure_number':1,'sha256':'c'*64,'series':[{'label':'Overall','outlier_count':0,'whislo':1.,'whishi':4.}]}
    payload=build_payload(value,figure)
    assert payload['schema_version']==2 and payload['facts']['overall.std']['value']=='Unavailable'
    assert payload['facts']['overall.mean']['label']=='Overall: Mean'
    assert 'Complete records' in payload['facts']['method.summary']['value']
    draft={key:'Based on '+', '.join('{{'+ref+'}}' for ref in refs)+'.' for key,refs in payload['required_references'].items()}
    assert render_explanation(draft,payload)[0]['title']=='Analysis purpose'


def test_legacy_chinese_result_payload_shape_stays_unversioned():
    from app.domain.explanation_content import build_payload
    value=result(); value.pop('schema_version'); value.pop('analysis_context')
    figure={'id':'figure','title':'图 1','figure_number':1,'sha256':'c'*64,'series':[]}
    payload=build_payload(value,figure)
    assert payload['language']=='zh-CN' and 'schema_version' not in payload
