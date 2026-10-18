import math
import pytest
from app.domain.figure_workbench.kernel import compute_projection, ProjectionError


def test_line_sort_mean_gaps_and_audit():
    rows=[{'row':2,'x':2.,'y':6.},{'row':3,'x':1.,'y':2.},{'row':4,'x':2.,'y':10.},{'row':5,'x':3.,'y':None},{'row':6,'x':None,'y':9.}]
    out=compute_projection('line',rows,{'aggregation':'mean','expected_x':[1.,2.,3.,4.]})
    assert out['series']==[{'group':None,'points':[{'x':1.,'y':2.,'n':1,'missing':0},{'x':2.,'y':8.,'n':2,'missing':0},{'x':3.,'y':None,'n':0,'missing':1},{'x':4.,'y':None,'n':0,'missing':0}]}]
    assert out['audit']['valid_n']==3
    assert out['audit']['excluded']==[{'row':6,'reason':'missing_x'}]
    assert out['audit']['missing_y_n']==1


def test_line_duplicate_and_bad_types_are_rejected():
    with pytest.raises(ProjectionError,match='duplicate_x'):
        compute_projection('line',[{'row':2,'x':1.,'y':2.},{'row':3,'x':1.,'y':3.}],{})
    for value in [True,'2',math.inf]:
        with pytest.raises(ProjectionError,match='invalid_numeric'):
            compute_projection('line',[{'row':2,'x':1.,'y':value}],{})


def test_bar_proportion_filter_reconfirms_denominator():
    rows=[{'row':i+2,'category':c} for i,c in enumerate(['A']*20+['B']*30+['C']*50)]
    out=compute_projection('bar',rows,{'bar_stat':'proportion','included_categories':['A','B']})
    assert out['series']==[{'group':None,'points':[{'category':'A','n':20,'denominator':50,'value':.4,'sd':None,'reason':None},{'category':'B','n':30,'denominator':50,'value':.6,'sd':None,'reason':None}]}]
    assert out['audit']['excluded_n']==50


def test_group_missing_never_silently_drops():
    rows=[{'row':2,'group':'a','category':'A'},{'row':3,'group':None,'category':'B'}]
    with pytest.raises(ProjectionError,match='missing_group'):
        compute_projection('bar',rows,{'group_column':'C'})
    out=compute_projection('bar',rows,{'group_column':'C','missing_group':'exclude'})
    assert out['audit']['excluded']==[{'row':3,'reason':'missing_group'}]


def test_bar_sample_sd_and_singleton_reason():
    out=compute_projection('bar',[{'row':2,'category':'A','y':1.},{'row':3,'category':'A','y':3.},{'row':4,'category':'B','y':4.}],{'bar_stat':'mean','error_bars':'sd'})
    a,b=out['series'][0]['points']
    assert a['value']==2. and a['sd']==pytest.approx(math.sqrt(2)) and a['n']==2
    assert b['sd'] is None and b['reason']=='insufficient_n_for_sd'


def test_violin_independent_gaussian_formula_and_scott():
    out=compute_projection('violin',[{'row':i+2,'y':v} for i,v in enumerate([0.,1.,2.])],{})
    group=out['series'][0]
    bandwidth=3**(-.2)
    expected0=sum(math.exp(-.5*(v/bandwidth)**2) for v in [0,1,2])/(3*bandwidth*math.sqrt(2*math.pi))
    assert group['bandwidth']==pytest.approx(bandwidth,rel=1e-12)
    assert len(group['grid'])==len(group['density'])==256
    assert group['grid'][0]==0. and group['grid'][-1]==2.
    assert group['density'][0]==pytest.approx(expected0,rel=1e-12)
    assert (group['q1'],group['median'],group['q3'])==(.5,1.,1.5)
    assert out['method']['width_scale']=='shared_density'
    for values in [[1.,1.,1.],[1.,2.]]:
        with pytest.raises(ProjectionError,match='violin_unsupported_group'):
            compute_projection('violin',[{'row':i+2,'y':v} for i,v in enumerate(values)],{})


def test_resources_and_datetime_order_are_explicit():
    with pytest.raises(ProjectionError,match='projection_limit'):
        compute_projection('bar',[{'row':i+2,'category':str(i)} for i in range(101)],{})
    out=compute_projection('line',[{'row':2,'x':'2024-02-01','y':2.},{'row':3,'x':'2024-01-01','y':1.}],{'x_type':'datetime'})
    assert [p['y'] for p in out['series'][0]['points']]==[1.,2.]
    with pytest.raises(ProjectionError,match='ordered_x_required'):
        compute_projection('line',[{'row':2,'x':'low','y':1.}],{'x_type':'ordered'})

def test_all_missing_mean_group_is_visible_and_violin_group_is_rejected():
    rows=[{'row':2,'category':'A','group':'one','y':1.},{'row':3,'category':'A','group':'two','y':None}]
    mean=compute_projection('bar',rows,{'bar_stat':'mean','group_column':'C'})
    assert mean['series'][1]['group']=='two'
    assert mean['series'][1]['points'][0]['value'] is None
    assert mean['series'][1]['points'][0]['reason']=='no_valid_values'
    rows=[{'row':i+2,'group':'one','y':v} for i,v in enumerate([1.,2.,3.])]+[{'row':5,'group':'two','y':None}]
    with pytest.raises(ProjectionError,match='violin_unsupported_group'):compute_projection('violin',rows,{'group_column':'C'})

def test_invalid_group_can_only_be_excluded_by_confirmed_rule():
    rows=[{'row':2,'category':'A','group':'one'},{'row':3,'category':'A','group':['invalid']}]
    with pytest.raises(ProjectionError,match='invalid_group'):compute_projection('bar',rows,{'group_column':'C'})
    out=compute_projection('bar',rows,{'group_column':'C','missing_group':'exclude'})
    assert out['audit']['excluded']==[{'row':3,'reason':'invalid_group'}]


@pytest.mark.parametrize('bad',['not-a-date','2026-01-01T00:00:00+08:00',1])
def test_expected_dates_use_same_validation_as_observed_dates(bad):
    with pytest.raises(ProjectionError,match='invalid_datetime'):
        compute_projection('line',[{'row':1,'x':'2026-01-01','y':5}],{'x_type':'datetime','expected_x':[bad]})


def test_ordered_x_uses_typed_keys_for_membership_order_and_buckets():
    out=compute_projection('line',[{'row':1,'x':1.,'y':10},{'row':2,'x':True,'y':20},{'row':3,'x':'1','y':30}],
        {'x_type':'ordered','x_order':[True,'1',1],'expected_x':[True,'1',1],'aggregation':'mean'})
    points=out['series'][0]['points']
    assert [(type(p['x']),p['x'],p['y'],p['n']) for p in points]==[(bool,True,20.,1),(str,'1',30.,1),(float,1.,10.,1)]
    with pytest.raises(ProjectionError,match='ordered_x_required'):
        compute_projection('line',[{'row':1,'x':True,'y':1}],{'x_type':'ordered','x_order':[1]})


def test_bar_number_filter_does_not_include_boolean_or_text_identity():
    rows=[{'row':1,'category':1.},{'row':2,'category':True},{'row':3,'category':'1'}]
    output=compute_projection('bar',rows,{'included_categories':[1],'bar_stat':'proportion'})
    assert output['series']==[{'group':None,'points':[{'category':1.,'n':1,'denominator':1,'value':1.,'sd':None,'reason':None}]}]
    assert output['audit']['excluded']==[{'row':2,'reason':'category_population_filter'},{'row':3,'reason':'category_population_filter'}]


def test_ordered_expected_numeric_encoding_does_not_create_a_second_bucket():
    from app.domain.figure_workbench.contracts import FigureConfig
    config=FigureConfig.model_validate({'figure_kind':'line','language':'en','projection':{
        'x_column':'A','y_column':'B','x_type':'ordered','x_order':[1,2],'expected_x':[1.,2.]}})
    output=compute_projection('line',[{'row':1,'x':1.,'y':10.}],config.projection.model_dump())
    assert output['series'][0]['points']==[{'x':1.,'y':10.,'n':1,'missing':0},{'x':2.,'y':None,'n':0,'missing':0}]


def test_ordered_x_rejects_structured_observation_as_controlled_error():
    with pytest.raises(ProjectionError,match='invalid_category'):
        compute_projection('line',[{'row':1,'x':['a'],'y':1}],{'x_type':'ordered','x_order':['a']})
