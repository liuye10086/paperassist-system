"""Offline v3 completeness and the real unbound-count failure, without providers."""
from copy import deepcopy
import json
import pytest
from app.core.exceptions import PlotError
from app.domain.figure_workbench import explanations as e
from app.domain.figure_workbench.tasks import prompt_version
from tests.domain.test_batch06_explanations import modern,draft


def historical_payload(bundle):
    return e.build_payload(bundle,version='figure_explanation_v3' if bundle['figure']['engine']['id']=='openai_figure_workbench_v3' else None)


def historical_render(bundle,*args):
    return e.render(bundle,*args,version='figure_explanation_v3')


def line(language='en',points=20):
    value=modern('line',language)
    value['figure'].update(engine={'id':'openai_figure_workbench_v3'},presentation={**value['figure']['presentation'],'schema_version':2})
    value['projection']['result']['series']=[{'group':group,'points':[
        {'x':i,'y':None if i==7 else i/3,'n':0 if i==7 else 1,'missing':1 if i==7 else 0}
        for i in range(points)]} for group in ('A','B')]
    return value


@pytest.mark.parametrize('language',['en','zh-CN'])
def test_line_complete_ordered_facts_fit_draft_without_dropping_points(language):
    bundle=line(language);original=deepcopy(bundle);payload=historical_payload(bundle)
    assert e.version_for(bundle['figure'],version='figure_explanation_v3')=='figure_explanation_v3'
    assert payload['figure_explanation_contract']==3
    assert prompt_version(payload,explanation=True)=='figure_explanation_v3'
    assert payload['required_references']['results']==['projection.0.coordinates','projection.1.coordinates']
    assert not any('.point.' in key for key in payload['facts'])
    for index,series in enumerate(bundle['projection']['result']['series']):
        fact=payload['facts'][f'projection.{index}.coordinates']
        assert fact['raw']==series and set(fact['raw'])=={'group','points'}
        separator='；' if language=='zh-CN' else '; '
        for point in series['points']:
            values=[('缺失（断线）' if language=='zh-CN' else 'missing (gap)') if point[k] is None else str(point[k]) for k in ('x','y','n','missing')]
            assert '('+separator.join(values)+')' in fact['value']
    assert bundle==original
    text=draft(payload)
    assert max(map(len,text.values()))<=4000 and len(payload['facts'])<=500
    saved=historical_render(bundle,text,{'model':'fake','model_call_id':'call','response_id':'response'})
    assert saved['engine']['id']=='figure_explanation_v3'
    e.validate_saved(bundle,saved)
    damaged=deepcopy(bundle);damaged['projection']['result']['series'][0]['points'][0]['y']=999
    from app.core.exceptions import StorageError
    with pytest.raises(StorageError):e.validate_saved(damaged,saved)


def test_line_compacts_before_the_legacy_five_hundred_fact_limit():
    payload=historical_payload(line(points=100))
    assert len(payload['facts'])<50
    assert len(payload['facts']['projection.0.coordinates']['raw']['points'])==100


def test_original_unbound_count_stays_rejected_but_neutral_complete_draft_passes():
    bundle=line('zh-CN');payload=historical_payload(bundle);text=draft(payload)
    text['results']='两组相应图示计数分别为'+text['results']
    with pytest.raises(PlotError,match='未绑定的数值'):historical_render(bundle,text,{})
    text['results']=text['results'].replace('两组','各组')
    assert len(historical_render(bundle,text,{})['sections'])==6
    text['results']=text['results'].replace('{{projection.0.coordinates}}','')
    with pytest.raises(PlotError,match='关键数据引用'):historical_render(bundle,text,{})


@pytest.mark.parametrize('prose',['two groups','first group','中位数','x'*4001])
def test_v3_retains_numeral_metric_and_length_guards(prose):
    bundle=line();payload=historical_payload(bundle);text=draft(payload);text['results']+=' '+prose
    with pytest.raises(PlotError):historical_render(bundle,text,{})


def test_v3_instructions_explain_program_labels_and_safe_complete_sections():
    instructions=e.instructions_for(historical_payload(line()))
    for word in ('两组','both','two','first','各组','these groups','fact_span','required_references','4000'):
        assert word in instructions
    legacy=historical_payload(modern())
    assert e.version_for(modern()['figure'])=='figure_explanation_v2'
    assert e.instructions_for(legacy)==e.INSTRUCTIONS_V2


@pytest.mark.parametrize('language',['en','zh-CN'])
def test_complete_coordinate_precision_note_is_v3_only(language):
    from app.domain.figure_workbench.explanation_facts import limitations
    current=limitations(line(language))
    expected='完整保存精度' if language=='zh-CN' else 'full saved precision'
    assert any(expected in note for note in current)
    legacy=limitations(modern('line',language))
    assert not any(expected in note for note in legacy)
    assert any(('8位' if language=='zh-CN' else '8 significant') in note for note in legacy)


@pytest.mark.parametrize('language',['en','zh-CN'])
def test_coordinate_display_uses_frozen_axes_units_gaps_and_typed_groups(language):
    bundle=line(language)
    bundle['figure']['presentation']['axes']={'x':{'label':'观察次序' if language=='zh-CN' else 'Observation order','unit':'day'},'y':{'label':'测量值 (mm)' if language=='zh-CN' else 'Measurement (mm)','unit':'mm'}}
    bundle['projection']['result']['series'][0]['group']=1
    bundle['projection']['result']['series'][1]['group']='1'
    original=deepcopy(bundle)
    payload=historical_payload(bundle)
    values=[payload['facts'][f'projection.{index}.coordinates']['value'] for index in range(2)]
    for value in values:
        assert ('观察次序 (day)' if language=='zh-CN' else 'Observation order (day)') in value
        assert value.count('mm')==1
        assert ('缺失（断线）' if language=='zh-CN' else 'missing (gap)') in value
        assert ('有效记录数；缺失记录数' if language=='zh-CN' else 'valid records; missing records') in value
        assert '[x,y,n,missing]' not in value and 'null' not in value
    assert ('[数值]' if language=='zh-CN' else '[number]') in values[0]
    assert ('[文本]' if language=='zh-CN' else '[text]') in values[1]
    assert bundle==original
