"""R5 retained Chinese output and exact scope identities; offline only."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from app.core.exceptions import PlotError
from app.domain.figure_workbench import explanations as e
from app.domain.figure_workbench.explanation_v5 import sentence_draft_v5, validate_draft_v5

F = json.loads((Path(__file__).parents[1] / 'fixtures/figure_b07/real-v5-response-logistic-zh.json').read_text(encoding='utf8'))
OLS = json.loads((Path(__file__).parents[1] / 'fixtures/figure_b07/real-v5-response-ols-zh.json').read_text(encoding='utf8'))
CATALOG = json.loads((Path(__file__).parents[1] / 'fixtures/figure_b07/v5-cn-frozen-prose-catalog.json').read_text(encoding='utf8'))

@pytest.fixture(autouse=True)
def postgres_schema():
    yield None

def check(text, payload=None):
    payload = payload or F['payload']
    draft = sentence_draft_v5(payload)
    draft['results'] += ' ' + text
    validate_draft_v5(draft, payload)

@pytest.mark.parametrize('section', F['draft'])
def test_retained_each_complete_section(section):
    draft = sentence_draft_v5(F['payload'])
    draft[section] = F['draft'][section]
    validate_draft_v5(draft, F['payload'])

def test_retained_render_saved_and_exact_input():
    from app.domain.model_usage.gateway import input_digest
    payload = e.build_payload(F['bundle'])
    assert payload == F['payload']
    assert e.instructions_for(payload) == F['instructions']
    assert input_digest(instructions=F['instructions'], payload=payload) == F['model_input_digest']
    value = e.render(F['bundle'], F['draft'], {'model_call_id':'offline-r5','response_id':F['source_response_id']})
    assert e.validate_saved(F['bundle'], value) == value
    assert value['draft'] == F['draft']
    for section in value['sections']:
        for evidence in section['evidence']:
            fact=payload['facts'][evidence['key']]
            assert evidence == {'key':evidence['key'],'label':fact['label'],'value':fact['value']}
            assert fact['label']+': '+fact['value'] in section['text']

@pytest.mark.parametrize('text', [
    '保存的参数及推断结果为{{modeling.coefficients.0.inference}}。',
    '保存的参数估计及推断结果为{{modeling.coefficients.1.inference}}。',
    '保存的信息准则为{{modeling.aic}}。',
    '原统计数据的总记录数为{{data.total}}。',
    '原统计数据的有效记录数为{{data.valid}}。',
    '原统计数据中的有效记录数为{{data.valid}}。',
    '原统计数据的排除记录数为{{data.excluded}}。',
    '原统计分析的有效记录数为{{modeling.n}}。',
    '保存的模型有效记录数为{{modeling.n}}。',
    '这些统计记录数不应直接解释为独立参与者数或投影记录数。',
    '该记录数不应直接解释为独立参与者数或投影记录数。',
    '不应将其直接视为独立参与者数或投影记录数。',
    '这些统计记录数不应直接解释为投影记录数或独立参与者数。',
])
def test_complete_typed_scope_or_cautious_negative(text):
    if '投影记录数' in text:text='保存结果显示{{modeling.n}}。'+text
    check(text)

@pytest.mark.parametrize('text', [
    '保存的信息准则为{{modeling.log_likelihood}}。',
    '保存的贝叶斯信息准则为{{modeling.aic}}。',
    '保存的调整后信息准则为{{modeling.aic}}。',
    '保存的参数及推断结果为{{modeling.p}}。',
    '原统计数据的总记录数为{{data.valid}}。',
    '原统计数据的有效记录数为{{data.total}}。',
    '原统计数据的排除记录数为{{data.valid}}。',
    '投影数据的有效记录数为{{modeling.n}}。',
    '共同统计的有效记录数为{{data.valid}}。',
    '原统计数据的有效记录数为{{modeling.p}}。',
    '保存的模型有效记录数为{{data.valid}}。',
    '这些统计记录数应直接解释为独立参与者数或投影记录数。',
    '这些统计记录数不应直接解释为独立参与者数，且已证实观察独立性。',
    '这些统计记录数不应直接解释为独立参与者数或投影记录数且已证明因果。',
    '这些统计记录数不应直接解释为独立参与者数或投影记录数，为40人。',
    '独立参与者数为{{modeling.n}}。',
    '参数及推断结果：{{modeling.coefficients.0.inference}}。',
])
def test_wrong_identity_or_affirmative_boundary_remains_rejected(text):
    with pytest.raises(PlotError):
        check(text)

def test_negative_requires_nonempty_observation_limit():
    payload=deepcopy(F['payload'])
    for ref,fact in payload['facts'].items():
        if ref.startswith('limitation.') and ('独立观察' in fact['value'] or '观察独立性' in fact['value']):
            fact['value']=fact['raw']=''
    with pytest.raises(PlotError):
        check('这些统计记录数不应直接解释为独立参与者数或投影记录数。',payload)

@pytest.mark.parametrize('section', ['purpose','results','paper_text','methods','interpretation'])
def test_ols_retained_sections_with_supported_claims(section):
    draft=sentence_draft_v5(OLS['payload'])
    draft[section]=OLS['draft'][section]
    validate_draft_v5(draft,OLS['payload'])

@pytest.mark.parametrize('text', [
    '保存的截距参数及推断为{{modeling.coefficients.0.inference}}。',
    '保存的暴露参数及推断为{{modeling.coefficients.1.inference}}。',
    '本地投影核对与因果解释的边界为{{limitation.2}}。',
    '观察独立性的核查限制为{{limitation.4}}。',
    '不据此认定独立性已经验证。',
    '该记录数不应直接解释为经验证的独立参与者数或投影记录数。',
    '不将其直接解释为经验证的独立参与者数。',
    '原统计分析的有效记录数为{{modeling.n}}，应与投影记录数区分。',
    '数据口径中的有效记录数为{{data.valid}}。',
    '本图数据口径中的总记录数为{{data.total}}，有效记录数为{{data.valid}}，排除记录数为{{data.excluded}}。',
])
def test_ols_exact_identity_and_cautious_meta(text):
    if '投影记录数' in text:text='保存结果显示{{modeling.n}}。'+text
    check(text,OLS['payload'])

@pytest.mark.parametrize('text', [
    '保存的截距参数及推断为{{modeling.coefficients.1.inference}}。',
    '保存的暴露参数及推断为{{modeling.coefficients.0.inference}}。',
    '保存的治疗参数及推断为{{modeling.coefficients.1.inference}}。',
    '已证实的观察独立性的核查限制为{{limitation.4}}。',
    '观察独立性的核查限制为{{limitation.2}}。',
    '本地投影核对与因果解释的边界为{{limitation.5}}。',
    '本地投影核对证明因果解释的边界为{{limitation.2}}。',
    '不据此认定独立性已经验证，且独立性已经验证。',
    '数据口径中的总记录数为{{data.valid}}。',
])
def test_ols_wrong_parameter_or_meta_identity_remains_rejected(text):
    with pytest.raises(PlotError):check(text,OLS['payload'])

def test_original_ols_data_statement_is_not_silently_rewritten_or_approved():
    # Frozen counts are original statistical records. The actual tail also
    # disclaims that identity; retain it as evidence, never bless or rewrite it.
    with pytest.raises(PlotError):validate_draft_v5(OLS['draft'],OLS['payload'])

@pytest.mark.parametrize('proposal', CATALOG)
def test_each_cn_type_keeps_cautious_independence_boundary(proposal):
    payload=CATALOG[proposal]['payload']
    key='data.original_n' if 'data.original_n' in payload['facts'] else 'data.valid'
    check('保存结果显示{{'+key+'}}，这些统计记录数不应直接解释为独立参与者数或投影记录数。',payload)

@pytest.mark.parametrize('proposal', CATALOG)
def test_each_cn_type_rejects_unbound_number_and_affirmative_conjunct(proposal):
    for text in ('这些统计记录数不应直接解释为独立参与者数或投影记录数，独立性已验证。',
                 '这些统计记录数不应直接解释为独立参与者数或投影记录数，值为42。'):
        with pytest.raises(PlotError):check(text,CATALOG[proposal]['payload'])

@pytest.mark.parametrize('expired', [False, True])
def test_known_completed_logit_receipt_uses_existing_get_only_worker_path(monkeypatch,expired):
    from tests.domain import test_explanation_v5_receipt_recovery as recovery
    monkeypatch.setattr(recovery,'FIXTURE',F)
    recovery.test_existing_worker_retrieves_same_receipt_without_reserving_or_posting(monkeypatch,expired)

@pytest.mark.parametrize('kind,ref', [('bar','projection.0.point.0.n'),('violin','projection.0.n')])
@pytest.mark.parametrize('caveat', ['应与投影记录数区分',
    '这些统计记录数不应直接解释为独立参与者数或投影记录数',
    '不应将其直接视为投影记录数或独立参与者数'])
@pytest.mark.parametrize('separator',['，','。'])
def test_projection_count_cannot_disclaim_its_own_population(kind,ref,caveat,separator):
    payload=CATALOG['explanation:'+kind+':zh-CN']['payload']
    with pytest.raises(PlotError):check('投影记录数为{{'+ref+'}}'+separator+caveat+'。',payload)

@pytest.mark.parametrize('kind,ref',[('bar','projection.0.point.0.n'),('violin','projection.0.n')])
def test_explicit_count_scope_switch_is_respected(kind,ref):
    payload=CATALOG['explanation:'+kind+':zh-CN']['payload']
    check('投影记录数为{{'+ref+'}}，保存结果显示{{data.original_n}}，应与投影记录数区分。',payload)

def test_projection_scope_caveat_requires_a_bound_count_source():
    payload=deepcopy(F['payload']);draft=sentence_draft_v5(payload)
    draft['purpose']='本图用于描述{{scope.variables}}。本图用于描述{{purpose.kind}}。应与投影记录数区分。'
    with pytest.raises(PlotError):validate_draft_v5(draft,payload)

@pytest.mark.parametrize('new_topic',['{{scope.variables}}','{{modeling.p}}','{{modeling.coefficients.0.inference}}'])
def test_prior_count_cannot_grant_a_caveat_after_new_fact_topic(new_topic):
    with pytest.raises(PlotError):check('保存结果显示{{modeling.n}}。本图描述'+new_topic+'。应与投影记录数区分。')

@pytest.mark.parametrize('topic',['这些数量描述投影记录','投影结果描述这些记录','这些数量描述另一组记录'])
def test_literal_population_topic_cannot_inherit_a_prior_original_count(topic):
    payload=CATALOG['explanation:violin:zh-CN']['payload']
    with pytest.raises(PlotError):check('保存结果显示{{data.original_n}}。'+topic+'，应与投影记录数区分。',payload)
