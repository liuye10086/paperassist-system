from copy import deepcopy
import importlib
import pytest
from app.core.exceptions import StorageError
from app.domain.figure_workbench.contracts import FigureConfig
from app.domain.figure_workbench.material import projection_material, verify_manifest
from app.domain.figure_workbench.prompts import instructions_for, BASE, DESCRIPTIVE


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None  # Pure material/manifest tests never access PostgreSQL.


def module():
    return importlib.import_module('app.domain.figure_workbench.presentation')


def materials(stat='count', language='zh-CN'):
    config=FigureConfig(figure_kind='bar',language=language,projection={'category_column':'A','bar_stat':stat}).model_dump()
    projection={'audit':{'valid_n':2,'excluded_n':0},'series':[{'group':'treatment','points':[{'category':'yes','n':2,'denominator':2 if stat=='proportion' else None,'value':1.0 if stat=='proportion' else 2,'sd':None,'reason':None}]}]}
    payload,expected=projection_material(config,[{'category':'yes','group':'treatment'}]*2,projection,{'A':{'name':'Response'}})
    return payload,expected,dict(config=config,result={},projection=projection,fields={'A':{'name':'Response'}})


def test_versions_fail_closed():
    p=module()
    assert p.contract_version({})==1
    assert p.renderer_for({})=='openai_figure_workbench_v1'
    assert p.renderer_for({'figure_contract':2})=='openai_figure_workbench_v2'
    for invalid in (None,True,0,4,'2',2.0):
        with pytest.raises(StorageError): p.contract_version({'figure_contract':invalid})


@pytest.mark.parametrize('stat,label,unit',[('count','记录数','条记录'),('proportion','组内比例（0–1）','0–1')])
def test_bar_semantics_immutable_and_manifest_tamper(stat,label,unit):
    payload,expected,kwargs=materials(stat)
    before=deepcopy((payload,expected))
    actual,wanted=module().enrich_material(payload,expected,**kwargs)
    assert (payload,expected)==before
    assert actual['schema_version']==wanted['schema_version']==5
    assert wanted['statistics']==expected['statistics']
    assert actual['labels']['y_label']==wanted['y_label']==label
    assert wanted['presentation']['axes']['y']=={'label':label,'unit':unit}
    assert wanted['presentation']==actual['presentation']
    assert wanted['presentation']['legend']['entries']==[{'label':'treatment','color':'#0072B2'}]
    verify_manifest(deepcopy(wanted),wanted)
    changed=deepcopy(wanted);changed['presentation']['legend']['entries'][0]['color']='#ffffff'
    with pytest.raises(Exception): verify_manifest(changed,wanted)


def test_v1_prompt_and_material_unchanged():
    payload,expected,kwargs=materials()
    assert instructions_for(payload)==BASE+DESCRIPTIVE
    enriched,_=module().enrich_material(payload,expected,**kwargs)
    assert instructions_for(payload)==BASE+DESCRIPTIVE
    assert 'presentation' in instructions_for(enriched)
    assert 'colorbar' in instructions_for(enriched)


def test_heatmap_diverging_scale():
    payload={'schema_version':5,'figure_kind':'correlation_heatmap','language':'en','labels':{'title':'Correlation','x_label':'','y_label':'','caption':'Author original'},'correlation_method':'spearman','plot_config':{}}
    expected={k:deepcopy(v) for k,v in payload.items() if k!='labels'};expected.update(payload['labels'],statistics={'n':4,'matrix':[[1.,-.3],[-.3,1.]]})
    actual,wanted=module().enrich_material(payload,expected,config={'style':{}},result={'statistics':{'method':'spearman'}},projection=None,fields={})
    scale=wanted['presentation']['color_scale']
    assert (scale['min'],scale['max'],scale['center'],scale['ticks'])==(-1,1,0,[-1,0,1])
    assert len(scale['palette'])==3 and len(set(scale['palette']))==3
    assert 'Author original' in actual['labels']['caption']
    assert wanted['statistics']==expected['statistics']


def test_scatter_group_projection_retains_confirmed_axes_and_units():
    payload={'schema_version':5,'figure_kind':'scatter','language':'en','labels':{'title':'Scatter','x_label':'Age (years)','y_label':'Weight (kg)','caption':'paired rows'},'variables':[{'name':'Age','unit':'years'},{'name':'Weight','unit':'kg'}],'display_groups':['A','B','A']}
    expected={**deepcopy(payload['labels']),'schema_version':5}
    actual,_=module().enrich_material(payload,expected,config={'projection':{'group_column':'C'},'style':{}},result={},projection=None,fields={'C':{'name':'Arm'}})
    assert actual['presentation']['axes']=={'x':{'label':'Age (years)','unit':'years'},'y':{'label':'Weight (kg)','unit':'kg'}}
    assert [x['label'] for x in actual['presentation']['legend']['entries']]==['A','B']


def test_system_localization_preserves_author_original_and_no_local_answers():
    payload,expected,kwargs=materials('mean')
    author='重复值规则：unique 评估角色：unknown'
    kwargs['config']['style']['caption']=author
    kwargs['config']['projection']['error_bars']='sd'
    payload['labels']['caption']='系统说明 '+author
    expected['statistics']['series'][0]['points'][0].update(sd=987654321,reason='insufficient_n_for_sd')
    kwargs['projection']['audit']['valid_n']=123456789
    actual,_=module().enrich_material(payload,expected,**kwargs)
    assert author in actual['labels']['caption']
    assert '987654321' not in str(actual['presentation'])
    assert '123456789' not in str(actual['presentation'])


def test_roc_role_localized():
    payload={'figure_kind':'roc_curve','language':'zh-CN','labels':{'title':'ROC','x_label':'','y_label':'','caption':'评估角色：apparent_exploratory'}}
    actual,_=module().enrich_material(payload,{},config={'style':{}},result={},projection=None,fields={})
    assert 'apparent_exploratory' not in actual['labels']['caption']
    assert '表观探索性评估' in actual['labels']['caption']


@pytest.mark.parametrize('legacy',[1,2,3,4])
def test_legacy_wrapped_metadata_tampering_rejected(legacy):
    from app.domain.plot_response import PlotVerificationError
    expected={'schema_version':5,'legacy_contract':legacy,'figure_kind':'forest','presentation':{'schema_version':1,'axes':{'x':{'label':'Effect','unit':''}},'statistical_notes':['Frozen only']}}
    verify_manifest(deepcopy(expected),expected)
    actual=deepcopy(expected);actual['presentation']['axes']['x']['label']='Fabrication'
    with pytest.raises(PlotVerificationError): verify_manifest(actual,expected)


@pytest.mark.parametrize('kind,terms,note_fragment',[
    ('boxplot',{'n','Q1','Q3','IQR'},'1.5'),
    ('paired_connected',{'n'},'complete pair'),
    ('scatter',{'n','r'},'causation'),
    ('line',{'n'},'no interpolation'),
    ('bar',{'n','SD'},'not confidence intervals'),
    ('violin',{'n','KDE','Q1','Q3'},'Scott'),
    ('forest',{'n','OR','CI'},'without independent refitting'),
    ('roc_curve',{'n','ROC','AUC'},'calibration'),
    ('kaplan_meier',{'n','KM','CI'},'Greenwood'),
])
def test_nine_families_method_specific_notes(kind,terms,note_fragment):
    payload={'schema_version':5,'figure_kind':kind,'language':'en','method':'logistic','labels':{'title':'Author title','x_label':'X','y_label':'Y','caption':'Author caption'},'plot_config':{'time_unit':'days'}}
    actual,wanted=module().enrich_material(payload,{},config={'projection':{'bar_stat':'mean','error_bars':'sd'},'style':{}},result={},projection=None,fields={})
    assert {a['term'] for a in actual['presentation']['abbreviations']}==terms
    assert note_fragment in ' '.join(actual['presentation']['statistical_notes'])
    assert actual['labels']['title']=='Author title'
    assert actual['labels']['caption'].startswith('Author caption')
    if kind=='kaplan_meier': assert actual['presentation']['axes']['x']=={'label':'Time (days)','unit':'days'}


def test_km_legend_uses_confirmed_labels_in_original_index_order():
    payload={'figure_kind':'kaplan_meier','language':'en','labels':{'title':'KM','x_label':'days','y_label':'Survival','caption':''},'group_labels':['Treatment','Control'],'observations':[{'group':1,'time':2,'event':True},{'group':0,'time':3,'event':False}]}
    actual,_=module().enrich_material(payload,{},config={'style':{}},result={},projection=None,fields={})
    assert actual['presentation']['legend']['entries']==[{'label':'Treatment','color':'#0072B2'},{'label':'Control','color':'#E69F00'}]


@pytest.mark.parametrize('kind,variables,x_label,y_label,axis_name,expected_unit',[
    ('boxplot',[],'体重（kg）','分组','x','kg'),
    ('boxplot',[{'column':'B','name':'体重','unit':'kg'}],'分组','体重（kg）','y','kg'),
    ('paired_connected',[{'column':'B','name':'Weight','unit':'kg'},{'column':'C','name':'Followup','unit':'kg'}],'Measurement','Weight (kg)','y','kg'),
])
def test_legacy_real_material_axis_shapes(kind,variables,x_label,y_label,axis_name,expected_unit):
    payload={'schema_version':5,'figure_kind':kind,'language':'zh-CN','labels':{'title':'Title','x_label':x_label,'y_label':y_label,'caption':''},'groups':[{'label':'A','values':[1.,2.,3.]}],'values':[1.,2.,3.]}
    if variables: payload['variables']=variables
    actual,_=module().enrich_material(payload,{},config={'style':{}},result={},projection=None,fields={})
    assert actual['presentation']['axes'][axis_name]['unit']==expected_unit
