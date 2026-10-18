from app.domain.figure_workbench.material import projection_material,verify_manifest
from app.domain.figure_workbench.kernel import compute_projection
from app.core.exceptions import PlotError
import pytest
from copy import deepcopy


def test_cloud_projection_never_contains_local_answers_or_coordinates():
    config={'figure_kind':'line','language':'en','projection':{'x_column':'A','y_column':'B','aggregation':'mean'},'style':{}}
    rows=[{'row':88,'x':2.,'y':8.,'subject_id':'secret'}]
    projection=compute_projection('line',rows,config['projection'])
    payload,expected=projection_material(config,rows,projection)
    assert payload['observations']==[{'x':2.,'y':8.,'group':None}]
    assert not {'series','audit','expected','source','row','analysis_run_id'} & payload.keys()
    assert expected['statistics']['series'][0]['points'][0]['y']==8.
    assert 'Figure 1' not in payload['labels']['title']
    wrong={**expected,'statistics':{'series':[]}}
    with pytest.raises(PlotError):verify_manifest(wrong,expected)
    verify_manifest(expected,expected)


@pytest.mark.parametrize('statistics',[
    {'threshold':1e-14}, {'effects':[{'estimate':-1e-14}]},
    {'groups':[{'points':[{'time':1e-14,'survival':1.}]}]},
])
def test_modeling_workbench_retains_legacy_exact_numbers(statistics):
    expected={'schema_version':5,'legacy_contract':4,'statistics':statistics}
    wrong=deepcopy(expected)
    if 'threshold' in statistics:wrong['statistics']['threshold']=2e-14
    elif 'effects' in statistics:wrong['statistics']['effects'][0]['estimate']=1e-14
    else:wrong['statistics']['groups'][0]['points'][0]['time']=2e-14
    with pytest.raises(PlotError):verify_manifest(wrong,expected)


@pytest.mark.parametrize('field',['group','category','x'])
def test_projection_manifest_preserves_typed_identity(field):
    expected={'schema_version':5,'figure_kind':'line' if field=='x' else 'bar',
              'plot_config':{'rules':{'x_type':'ordered'}},
              'statistics':{'series':[{'group':1.,'points':[{'category':2.,'x':3.,'n':1,'value':1}]}]}}
    wrong=deepcopy(expected)
    if field=='group':wrong['statistics']['series'][0]['group']=1
    else:wrong['statistics']['series'][0]['points'][0][field]=int(wrong['statistics']['series'][0]['points'][0][field])
    with pytest.raises(PlotError):verify_manifest(wrong,expected)


def test_projection_derived_float_uses_relative_tolerance_without_zero_floor():
    expected={'schema_version':5,'figure_kind':'bar','plot_config':{'rules':{'bar_stat':'mean'}},
              'statistics':{'series':[{'group':None,'points':[{'category':'a','n':2,'value':1e-14,'sd':0.}]}]}}
    wrong=deepcopy(expected);wrong['statistics']['series'][0]['points'][0]['value']=-1e-14
    with pytest.raises(PlotError):verify_manifest(wrong,expected)
    close=deepcopy(expected);close['statistics']['series'][0]['points'][0]['value']*=1+1e-12
    verify_manifest(close,expected)


def test_manifest_unrepresentable_number_is_a_controlled_mismatch():
    expected={'schema_version':5,'figure_kind':'line','statistics':{'series':[{'group':None,'points':[{'x':1.,'y':2.,'n':1}]}]}}
    actual=deepcopy(expected);actual['statistics']['series'][0]['points'][0]['y']=10**400
    with pytest.raises(PlotError):verify_manifest(actual,expected)


def test_unique_line_y_is_an_observation_but_group_mean_is_derived():
    expected={'schema_version':5,'figure_kind':'line','plot_config':{'rules':{'aggregation':'unique'}},
              'statistics':{'series':[{'group':None,'points':[{'x':1.,'y':2.,'n':1}]}]}}
    wrong=deepcopy(expected);wrong['statistics']['series'][0]['points'][0]['y']=2.+1e-12
    with pytest.raises(PlotError):verify_manifest(wrong,expected)
    expected['plot_config']['rules']['aggregation']=wrong['plot_config']['rules']['aggregation']='mean'
    verify_manifest(wrong,expected)
