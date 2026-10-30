"""Retained Chinese model output and typed multilingual prose; no live calls."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.core.exceptions import PlotError
from app.domain.figure_workbench import explanations as e
from app.domain.figure_workbench.explanation_v5 import sentence_draft_v5, validate_draft_v5, render_sections_v5
from tests.domain.test_explanation_v5 import find

FIXTURES = Path(__file__).parents[1] / 'fixtures/figure_b07'
HEAT = json.loads((FIXTURES / 'real-v5-response-correlation-zh.json').read_text(encoding='utf-8'))
CATALOG = json.loads((FIXTURES / 'v5-cn-frozen-prose-catalog.json').read_text(encoding='utf-8'))
_box = find('boxplot', 'en')
_box['figure']['language'] = 'zh-CN'
_box['result']['analysis_context']['plan']['research_request']['output_language'] = 'zh-CN'
BOX = e.build_payload(_box)


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def draft_with(text, payload=None, section='results'):
    payload = payload or HEAT['payload']
    draft = sentence_draft_v5(payload)
    draft[section] += ' ' + text
    return draft


@pytest.mark.parametrize('section', HEAT['draft'])
def test_each_retained_chinese_section_accepts_complete_bound_scientific_prose(section):
    draft = sentence_draft_v5(HEAT['payload'])
    draft[section] = HEAT['draft'][section]
    validate_draft_v5(draft, HEAT['payload'])


def test_actual_cn_response_round_trips_with_all_original_canonical_spans():
    original = deepcopy(HEAT)
    value = e.render(HEAT['bundle'], HEAT['draft'], {'model_call_id': 'offline-cn-retained', 'response_id': HEAT['source_response_id']})
    assert e.validate_saved(HEAT['bundle'], value) == value
    assert value['draft'] == HEAT['draft']
    for section in value['sections']:
        for evidence in section['evidence']:
            fact = HEAT['payload']['facts'][evidence['key']]
            assert evidence == {'key': evidence['key'], 'label': fact['label'], 'value': fact['value']}
            assert fact['label'] + ': ' + fact['value'] in section['text']
    assert HEAT == original


def test_cn_frozen_payload_instructions_and_digest_remain_identical():
    from app.domain.model_usage.gateway import input_digest
    payload = e.build_payload(HEAT['bundle'])
    assert payload == HEAT['payload']
    assert e.instructions_for(payload) == HEAT['instructions']
    assert input_digest(instructions=e.instructions_for(payload), payload=payload) == HEAT['model_input_digest']


@pytest.mark.parametrize('i,j', [(i, j) for i in range(3) for j in range(3)])
@pytest.mark.parametrize('noun', ['系数', '相关系数'])
def test_cn_direct_matrix_pair_is_bound_to_exact_row_and_column(i, j, noun):
    text = '{{variables.' + str(i) + '.name}}与{{variables.' + str(j) + '.name}}的' + noun + '为{{matrix.' + str(i) + '.' + str(j) + '}}。'
    validate_draft_v5(draft_with(text), HEAT['payload'])


@pytest.mark.parametrize('row', range(3))
@pytest.mark.parametrize('mode', ['shared_left', 'respectively', 'permuted_list'])
def test_cn_matrix_rows_keep_shared_left_identity_and_zipped_list_order(row, mode):
    if mode == 'shared_left':
        text = '{{variables.' + str(row) + '.name}}与{{variables.0.name}}的系数为{{matrix.' + str(row) + '.0}}，与{{variables.1.name}}的系数为{{matrix.' + str(row) + '.1}}，与{{variables.2.name}}的系数为{{matrix.' + str(row) + '.2}}。'
    else:
        order = [0, 1, 2] if mode == 'respectively' else [2, 0, 1]
        names = '、'.join('{{variables.' + str(j) + '.name}}' for j in order)
        values = '、'.join('{{matrix.' + str(row) + '.' + str(j) + '}}' for j in order)
        text = '{{variables.' + str(row) + '.name}}与' + names + '的系数分别为' + values + '。'
    validate_draft_v5(draft_with(text), HEAT['payload'])


@pytest.mark.parametrize('text', [
    '{{variables.0.name}}与{{variables.1.name}}的系数为{{matrix.0.2}}。',
    '{{variables.0.name}}与{{variables.1.name}}的系数为{{matrix.1.0}}。',
    '{{variables.1.name}}与{{variables.2.name}}的系数为{{matrix.0.2}}。',
    '{{variables.0.name}}与{{variables.0.name}}的系数为{{matrix.0.0}}，与{{variables.1.name}}的系数为{{matrix.1.1}}。',
    '与{{variables.1.name}}的系数为{{matrix.0.1}}。',
    '{{variables.0.name}}与{{variables.0.name}}的系数为{{matrix.0.0}}。与{{variables.1.name}}的系数为{{matrix.0.1}}。',
    '{{variables.0.name}}与{{variables.0.name}}的系数为{{matrix.0.0}}，这里显示{{scope.variables}}，与{{variables.1.name}}的系数为{{matrix.0.1}}。',
    '{{variables.0.name}}与{{variables.0.name}}、{{variables.1.name}}和{{variables.2.name}}的系数分别为{{matrix.0.0}}、{{matrix.0.2}}和{{matrix.0.1}}。',
    '{{variables.0.name}}与{{variables.0.name}}、{{variables.1.name}}的系数分别为{{matrix.0.0}}、{{matrix.0.1}}和{{matrix.0.2}}。',
    '{{variables.0.name}}与{{variables.0.name}}、{{variables.1.name}}和{{variables.2.name}}的系数分别为{{matrix.1.0}}、{{matrix.1.1}}和{{matrix.1.2}}。',
    'X与Y的系数为{{matrix.0.1}}。',
    '{{variables.0.name}}与{{variables.1.name}}的Pearson系数为{{matrix.0.1}}。',
    '保存结果显示系数为{{matrix.0.1}}。',
])
def test_cn_matrix_pair_and_list_identity_cannot_be_guessed_from_equal_values(text):
    with pytest.raises(PlotError):
        validate_draft_v5(draft_with(text), HEAT['payload'])


@pytest.mark.parametrize('noun,ref', [
    ('原始数据行数', 'data.total'), ('完整记录数', 'data.valid'), ('排除行数', 'data.excluded'),
    ('共同完整记录数', 'correlation.n'), ('共同有效记录数', 'correlation.n'), ('共同有效样本数', 'correlation.n'),
])
def test_cn_record_count_population_is_bound_by_identity_not_same_numeric_value(noun, ref):
    validate_draft_v5(draft_with('保存的' + noun + '为{{' + ref + '}}。'), HEAT['payload'])


@pytest.mark.parametrize('noun,ref', [
    ('共同完整记录数', 'data.valid'), ('共同有效记录数', 'data.valid'),
    ('共同有效样本数', 'data.total'), ('完整记录数', 'correlation.n'),
    ('原始数据行数', 'correlation.n'), ('投影记录数', 'data.valid'),
    ('排除行数', 'data.valid'),
])
def test_cn_common_statistical_and_projection_populations_cannot_be_interchanged(noun, ref):
    with pytest.raises(PlotError):
        validate_draft_v5(draft_with('保存的' + noun + '为{{' + ref + '}}。'), HEAT['payload'])


@pytest.mark.parametrize('noun,ref', [
    ('均值', 'overall.mean'), ('中位数', 'overall.median'), ('样本标准差', 'overall.std'),
    ('下四分位数', 'overall.q1'), ('上四分位数', 'overall.q3'), ('四分位距', 'overall.iqr'),
])
def test_cn_descriptive_metric_nouns_use_exact_scalar_keys(noun, ref):
    draft = draft_with('保存的' + noun + '为{{' + ref + '}}。', BOX)
    sections = render_sections_v5(draft, BOX)
    assert BOX['facts'][ref]['label'] + ': ' + BOX['facts'][ref]['value'] in sections[3]['text']


@pytest.mark.parametrize('noun,ref', [
    ('均值', 'overall.median'), ('标准差', 'overall.mean'),
    ('下四分位数', 'overall.q3'), ('加权均值', 'overall.mean'),
])
def test_cn_metric_name_mismatch_or_unbound_transformation_is_rejected(noun, ref):
    with pytest.raises(PlotError):
        validate_draft_v5(draft_with('保存的' + noun + '为{{' + ref + '}}。', BOX), BOX)


TYPED_CN = [
    ('scatter', '共同有效记录数', 'correlation.n'), ('scatter', '相关系数', 'correlation.coefficient'),
    ('scatter', '双侧P值', 'correlation.p_value'), ('scatter', '置信区间', 'correlation.confidence_interval'),
    ('forest:ols', '残差自由度', 'modeling.df_residual'), ('forest:ols', '决定系数', 'modeling.r_squared'),
    ('forest:ols', '调整决定系数', 'modeling.adjusted_r_squared'), ('forest:ols', '残差标准差', 'modeling.residual_sd'),
    ('forest:ols', '参数及推断', 'modeling.coefficients.1.inference'),
    ('forest:logistic', '参数及推断', 'modeling.coefficients.1.inference'),
    ('forest:logistic', '对数似然', 'modeling.log_likelihood'), ('forest:logistic', 'Akaike信息准则', 'modeling.aic'),
    ('forest:logistic', '模型参数数', 'modeling.p'),
    ('roc_curve', '曲线下面积', 'modeling.auc'), ('roc_curve', 'AUC置信区间', 'modeling.confidence_interval'),
    ('roc_curve', '阳性记录数', 'modeling.positive_n'), ('roc_curve', '阴性记录数', 'modeling.negative_n'),
    ('kaplan_meier', '删失记录数', 'modeling.groups.0.censored_n'),
    ('kaplan_meier', '事件记录数', 'modeling.groups.0.event_n'),
    ('kaplan_meier', '中位生存时间', 'modeling.groups.0.median'),
    ('violin', '投影记录数', 'projection.0.n'), ('violin', '下四分位数', 'projection.0.q1'),
    ('violin', '核密度带宽', 'projection.0.bandwidth'),
    ('line', '完整分组坐标事实', 'projection.0.coordinates'),
    ('bar', '绘图统计值', 'projection.0.point.0.value'), ('bar', '投影记录数', 'projection.0.point.0.n'),
]


@pytest.mark.parametrize('kind,noun,ref', TYPED_CN)
def test_other_frozen_cn_kinds_use_their_actual_typed_metric_or_whole_fact(kind, noun, ref):
    payload = CATALOG['explanation:' + kind + ':zh-CN']['payload']
    draft = draft_with('保存的' + noun + '为{{' + ref + '}}。', payload)
    sections = render_sections_v5(draft, payload)
    fact = payload['facts'][ref]
    assert fact['label'] + ': ' + fact['value'] in sections[3]['text']


@pytest.mark.parametrize('kind,noun,ref', [
    ('scatter', 'P值', 'correlation.coefficient'), ('scatter', '相关系数', 'correlation.p_value'),
    ('scatter', '置信区间', 'correlation.coefficient'),
    ('forest:logistic', '优势比', 'modeling.coefficients.1.inference'),
    ('forest:logistic', 'P值', 'modeling.p'), ('forest:logistic', '系数', 'modeling.coefficients.1.inference'),
    ('forest:logistic', '参数及推断', 'modeling.n'),
    ('roc_curve', '曲线下面积', 'modeling.n'), ('roc_curve', '置信区间', 'modeling.auc'),
    ('kaplan_meier', '删失记录数', 'modeling.groups.0.event_n'),
    ('kaplan_meier', '中位生存时间', 'modeling.groups.0.max_time'),
    ('violin', '下四分位数', 'projection.0.q3'),
    ('line', '均值', 'projection.0.coordinates'), ('line', '完整分组坐标事实', 'data.valid'),
    ('bar', '投影记录数', 'projection.0.point.0.value'), ('bar', '绘图统计值', 'projection.0.point.0.n'),
])
def test_other_cn_typed_objects_do_not_authorize_wrong_submetrics_or_units(kind, noun, ref):
    payload = CATALOG['explanation:' + kind + ':zh-CN']['payload']
    with pytest.raises(PlotError):
        validate_draft_v5(draft_with('保存的' + noun + '为{{' + ref + '}}。', payload), payload)


@pytest.mark.parametrize('text', [
    '此记录数不作为已验证的独立参与者人数。',
    '这些数量描述原始统计记录，不代表投影记录数或已验证的独立参与者人数。',
    '不将该记录数视为已验证的独立参与者人数。',
    '记录数不等于已验证的独立受试者人数。',
    '不能把这些记录数视为已验证的独立参与者人数。',
    '不能据此认定观察独立性。',
    '核查观察独立性时应考虑{{limitation.2}}。',
    '解释因果边界时应考虑{{limitation.0}}。',
])
def test_cn_cautious_boundary_language_has_scoped_and_relevant_limit_semantics(text):
    validate_draft_v5(draft_with(text, section='interpretation'), HEAT['payload'])


@pytest.mark.parametrize('text', [
    '此记录数不作为已验证的独立参与者人数，但观察独立性已经确认。',
    '不将该记录数视为已验证的独立参与者人数，且已经证实所有观察独立。',
    '这些数量描述原始统计记录，不代表投影记录数或已验证的独立参与者人数，因此证明因果。',
    '保存结果显示观察独立性已经得到验证。',
    '保存结果显示已验证的独立参与者人数。',
    '核查已确认的观察独立性时应考虑{{limitation.2}}。',
    '核查观察独立性时应考虑{{limitation.5}}。',
    '解释因果边界时应考虑{{limitation.5}}。',
    '干预证明因果，但解释因果边界时应考虑{{limitation.0}}。',
    '解释因果边界时应考虑{{limitation.0}}，因此结果具有因果意义。',
    '本图使用前瞻性队列研究。', '根据参考文献显示{{correlation.n}}。',
    '保存结果显示12条记录。', '保存结果显示三条记录。', '保存结果显示参条记录。',
    '保存结果显示均值为{{correlation.n}}。', '保存结果具有统计学意义。',
])
def test_cn_negation_meta_or_bound_fact_cannot_grant_unbound_positive_assertions(text):
    with pytest.raises(PlotError):
        validate_draft_v5(draft_with(text, section='interpretation'), HEAT['payload'])


@pytest.mark.parametrize('text', [
    '此记录数不作为已验证的独立参与者人数。',
    '核查观察独立性时应考虑{{limitation.2}}。',
])
def test_cn_independence_caution_needs_nonempty_observation_not_cloud_refit_limit(text):
    payload = deepcopy(HEAT['payload'])
    for value in ('', '仅描述独立云端模型重拟合范围。'):
        payload['facts']['limitation.2'].update(raw=value, value=value)
        with pytest.raises(PlotError):
            validate_draft_v5(draft_with(text, payload, 'interpretation'), payload)


@pytest.mark.parametrize('fragment', [
    '{{scope.variables}}；{{purpose.kind}}。', '图形类型：{{purpose.kind}}。',
    '为{{purpose.kind}}。', '方法说明：{{purpose.kind}}。',
])
def test_cn_title_or_predicate_fragment_is_not_a_substantive_sentence(fragment):
    draft = sentence_draft_v5(HEAT['payload'])
    draft['purpose'] += fragment
    with pytest.raises(PlotError):
        validate_draft_v5(draft, HEAT['payload'])


@pytest.mark.parametrize('expired', [False, True])
def test_cn_retained_response_worker_get_only_and_existing_observation_gate(monkeypatch, expired):
    from tests.domain import test_explanation_v5_receipt_recovery as recovery
    monkeypatch.setattr(recovery, 'FIXTURE', HEAT)
    recovery.test_existing_worker_retrieves_same_receipt_without_reserving_or_posting(monkeypatch, expired)


@pytest.mark.parametrize('noun,ref', [('均值', 'mean'), ('中位数', 'median'), ('标准差', 'std')])
@pytest.mark.parametrize('connector', ['的', '组的', '分组的'])
def test_cn_named_group_natural_connectors_keep_the_same_exact_group(noun, ref, connector):
    text = '{{groups.0.label}}' + connector + noun + '为{{groups.0.' + ref + '}}。'
    validate_draft_v5(draft_with(text, BOX), BOX)


@pytest.mark.parametrize('text', [
    '{{groups.0.label}}组的均值为{{groups.1.mean}}。',
    '{{groups.0.label}}组的中位数为{{groups.1.median}}。',
    '{{groups.0.label}}分组的标准差为{{groups.1.std}}。',
    '{{groups.0.label}}与{{groups.1.label}}组的均值为{{groups.1.mean}}。',
])
def test_cn_full_named_group_scope_cannot_borrow_only_the_adjacent_suffix(text):
    with pytest.raises(PlotError):
        validate_draft_v5(draft_with(text, BOX), BOX)


@pytest.mark.parametrize('text', [
    '{{variables.2.name}}与{{variables.0.name}}与{{variables.1.name}}的系数为{{matrix.0.1}}。',
    '{{variables.2.name}}和{{variables.0.name}}与{{variables.1.name}}的系数为{{matrix.0.1}}。',
    '{{variables.2.name}}与{{variables.0.name}}与{{variables.0.name}}、{{variables.1.name}}的系数分别为{{matrix.0.0}}、{{matrix.0.1}}。',
    'Z与{{variables.0.name}}与{{variables.1.name}}的系数为{{matrix.0.1}}。',
])
def test_cn_matrix_binding_closes_the_entire_pair_or_list_noun_scope(text):
    with pytest.raises(PlotError):
        validate_draft_v5(draft_with(text), HEAT['payload'])


@pytest.mark.parametrize('text', [
    '{{groups.0.label}}组的均值为{{groups.0.mean}}，中位数为{{groups.0.median}}。',
    '{{groups.0.label}}组的均值为{{groups.0.mean}}，标准差为{{groups.0.std}}。',
    '{{groups.0.label}}组，保存的均值为{{groups.0.mean}}。',
    '{{groups.0.label}}组的均值为{{groups.0.mean}}，{{groups.1.label}}组的中位数为{{groups.1.median}}。',
    '{{groups.0.label}}组的均值为{{groups.0.mean}}。保存的中位数为{{groups.1.median}}。',
])
def test_cn_explicit_group_topic_inherits_until_an_explicit_switch_or_sentence_end(text):
    validate_draft_v5(draft_with(text, BOX), BOX)


@pytest.mark.parametrize('text', [
    '{{groups.0.label}}组的均值为{{groups.0.mean}}，中位数为{{groups.1.median}}。',
    '{{groups.0.label}}组的均值为{{groups.0.mean}}，标准差为{{groups.1.std}}。',
    '{{groups.0.label}}组，保存的均值为{{groups.1.mean}}。',
    '{{groups.0.label}}组的均值为{{groups.0.mean}}；中位数为{{groups.1.median}}。',
    '{{groups.0.label}}组和{{groups.1.label}}组，保存的均值为{{groups.1.mean}}。',
])
def test_cn_commas_and_topic_fronting_do_not_erase_the_active_group_identity(text):
    with pytest.raises(PlotError):
        validate_draft_v5(draft_with(text, BOX), BOX)


@pytest.mark.parametrize('text', [
    '总体的均值为{{overall.mean}}。', '整体统计的中位数为{{overall.median}}。',
    '总体，保存的均值为{{overall.mean}}。',
])
def test_cn_explicit_overall_population_noun_matches_overall_keys(text):
    validate_draft_v5(draft_with(text, BOX), BOX)


@pytest.mark.parametrize('text', [
    '总体的均值为{{groups.0.mean}}。', '总体，保存的均值为{{groups.0.mean}}。',
    '整体统计的中位数为{{groups.1.median}}。',
])
def test_cn_overall_population_qualifiers_cannot_be_dropped_before_a_group_metric(text):
    with pytest.raises(PlotError):
        validate_draft_v5(draft_with(text, BOX), BOX)


@pytest.mark.parametrize('text', [
    '共同统计的完整记录数为{{correlation.n}}。',
    '共同统计，完整记录数为{{correlation.n}}。',
])
def test_cn_common_population_modifier_binds_the_joint_record_count(text):
    validate_draft_v5(draft_with(text), HEAT['payload'])


@pytest.mark.parametrize('text', [
    '共同统计的完整记录数为{{data.valid}}。',
    '共同统计，完整记录数为{{data.valid}}。',
    '投影总体的完整记录数为{{data.valid}}。',
])
def test_cn_population_modifier_phrases_cannot_hide_behind_a_final_possessive(text):
    with pytest.raises(PlotError):
        validate_draft_v5(draft_with(text), HEAT['payload'])


@pytest.mark.parametrize('noun', ['调整决定系数', '调整后的决定系数', '调整后决定系数'])
def test_cn_adjusted_metric_whole_name_binds_only_the_adjusted_key(noun):
    payload = CATALOG['explanation:forest:ols:zh-CN']['payload']
    validate_draft_v5(draft_with(noun + '为{{modeling.adjusted_r_squared}}。', payload), payload)


@pytest.mark.parametrize('text', [
    '调整后的决定系数为{{modeling.r_squared}}。',
    '保存的决定系数为{{modeling.r_squared}}，随后进行了调整。',
])
def test_cn_unbound_adjustment_cannot_relabel_an_unadjusted_metric(text):
    payload = CATALOG['explanation:forest:ols:zh-CN']['payload']
    with pytest.raises(PlotError):
        validate_draft_v5(draft_with(text, payload), payload)


@pytest.mark.parametrize('modifier', ['调整后的', '校正后的', '修正后的', '验证后的'])
def test_cn_unknown_metric_modifier_is_not_a_neutral_possessive_introducer(modifier):
    with pytest.raises(PlotError):
        validate_draft_v5(draft_with(modifier + '均值为{{overall.mean}}。', BOX), BOX)
