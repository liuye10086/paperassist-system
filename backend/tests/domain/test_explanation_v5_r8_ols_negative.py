"""Retained final2 OLS negative boundaries: pure offline validation, no DB/model."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from app.core.exceptions import PlotError
from app.domain.figure_workbench.explanation_v5 import validate_draft_v5,sentence_draft_v5

DIR=Path(__file__).parents[1]/'fixtures/figure_b07'
NEW=json.loads((DIR/'r8-actual-79916e48-5b99-4039-9215-1dd5514e5245.json').read_text(encoding='utf-8'))
OLD=json.loads((DIR/'real-v5-response-ols-zh.json').read_text(encoding='utf-8'))

@pytest.fixture(autouse=True)
def postgres_schema():yield None

def test_actual_final2_whole_draft_is_unchanged_and_accepted():
    before=deepcopy(NEW);validate_draft_v5(NEW['draft'],NEW['payload']);assert NEW==before

@pytest.mark.parametrize('text',[
    '原统计分析的有效记录数为{{data.valid}}，该记录数不等同于已经验证的独立参与者人数。',
    '原统计分析的有效记录数为{{data.valid}}。这些数值来自原统计分析记录，不是本地效应投影记录数，也不代表已经验证的独立参与者人数。',
    '原统计分析的有效记录数为{{data.valid}}，该记录数不等同于已经验证的独立参与者人数，也不应与本地效应投影记录混同。',
    '观察独立性的声明与核查状态为{{limitation.4}}。',
])
def test_complete_negative_or_exact_observation_limitation(text):
    d=sentence_draft_v5(NEW['payload']);d['data']+=' '+text;validate_draft_v5(d,NEW['payload'])

@pytest.mark.parametrize('text',[
    '原统计分析的有效记录数为{{data.valid}}，该记录数等同于已经验证的独立参与者人数。',
    '原统计分析的有效记录数为{{data.valid}}。这些数值来自原统计分析记录，不是本地效应投影记录数，也代表已经验证的独立参与者人数。',
    '原统计分析的有效记录数为{{data.valid}}，该记录数不等同于已经验证的独立参与者人数。该记录数等同于已经验证的独立参与者人数。',
    '原统计分析的有效记录数为{{data.valid}}，该记录数不等同于已经验证的独立参与者人数，也应与本地效应投影记录混同。',
    '原统计分析的有效记录数为{{data.valid}}，该记录数不等同于已经验证的独立参与者人数，也不应与本地效应投影记录混同且已经验证观察独立性。',
    '观察独立性的声明与核查状态为{{limitation.2}}。',
    '原统计分析的有效记录数为{{data.valid}}。横轴字段为{{axis.x.label}}。这些数值来自原统计分析记录，不是本地效应投影记录数，也不代表已经验证的独立参与者人数。',
    '这些数值来自原统计分析记录，不是本地效应投影记录数，也不代表已经验证的独立参与者人数。',
])
def test_affirmative_cross_sentence_wrong_limitation_and_scope_remain_rejected(text):
    d=sentence_draft_v5(NEW['payload']);d['data']+=' '+text
    with pytest.raises(PlotError):validate_draft_v5(d,NEW['payload'])

def test_new_negation_needs_actual_observation_limit():
    p=deepcopy(NEW['payload']);p['facts']['limitation.4']['value']=p['facts']['limitation.4']['raw']='不能据此推断因果'
    with pytest.raises(PlotError):validate_draft_v5(NEW['draft'],p)

def test_old_5a819c97_semantically_wrong_population_draft_still_rejected():
    assert OLD['source_task_id']=='5a819c97-6e0f-40e3-ace4-649c216b34e4'
    with pytest.raises(PlotError):validate_draft_v5(OLD['draft'],OLD['payload'])

@pytest.mark.parametrize('text',[
    '保存的截距参数推断结果为{{modeling.coefficients.1.inference}}。',
    '保存的参数推断结果为{{modeling.n}}。',
    '另一项保存的参数推断结果为{{modeling.p}}。',
    '原统计分析的有效记录数为{{data.total}}。',
    '原统计分析的有效记录数为{{modeling.p}}。',
    '投影有效记录数为{{data.valid}}。',
])
def test_new_typed_nouns_do_not_grant_other_metric_or_coefficient_identity(text):
    d=sentence_draft_v5(NEW['payload']);d['results']+=' '+text
    with pytest.raises(PlotError):validate_draft_v5(d,NEW['payload'])

def test_original_record_alias_and_negative_cannot_relabel_projection_fact():
    p=deepcopy(NEW['payload']);p['facts']['data.valid']['label']='投影有效记录数'
    d=sentence_draft_v5(p)
    d['data']+=' 原统计分析的有效记录数为{{data.valid}}，该记录数不等同于已经验证的独立参与者人数，也不应与本地效应投影记录混同。'
    with pytest.raises(PlotError):validate_draft_v5(d,p)
