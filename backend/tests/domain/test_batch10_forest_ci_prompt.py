"""Forward-only forest annotation; no numerical worker, database or provider."""
from copy import deepcopy

import pytest

from app.domain.figure_workbench import prompts


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def forest(method='logistic'):
    return {
        'figure_kind': 'forest', 'legacy_contract': 4, 'method': method,
        'language': 'zh-CN', 'presentation': {'schema_version': 2},
        'plot_config': {'verification_scope': 'local_effect_projection'},
        'effects': [{'estimate': 9, 'ci_low': 2, 'ci_high': 38},
                    {'estimate': 4, 'ci_low': None, 'ci_high': None,
                     'interval_reason': 'unavailable'}],
    }


@pytest.mark.parametrize('method', ['ols', 'logistic'])
@pytest.mark.parametrize('language', ['zh-CN', 'en'])
def test_fixed_forest_intervals_are_visibly_identified_without_changing_payload(method, language):
    payload = forest(method); payload['language'] = language
    before = deepcopy(payload)
    instruction = prompts.instructions_for(payload)
    assert 'existing two-sided 95% confidence intervals from the fixed local OLS/Logistic kernel' in instruction
    assert '95%置信区间' in instruction and '95% confidence interval' in instruction
    assert 'Do not infer the confidence level from the endpoint values or recompute intervals' in instruction
    assert 'An unavailable interval stays absent, never a zero-width interval' in instruction
    assert 'Do not change labels.caption, presentation.abbreviations or returned JSON' in instruction
    assert payload == before


@pytest.mark.parametrize('change', [
    {'presentation': {'schema_version': 1}},
    {'legacy_contract': 3},
    {'method': 'cox'},
    {'plot_config': {'verification_scope': 'external_effect_projection'}},
    {'figure_kind': 'roc_curve'},
    {'figure_kind': 'kaplan_meier'},
])
def test_ci_annotation_does_not_spread_to_historical_or_unrelated_contracts(change):
    payload = forest(); payload.update(change)
    assert 'VERSION 3 FIXED FOREST INTERVAL LABEL' not in prompts.instructions_for(payload)
    payload.pop('presentation', None)
    assert 'VERSION 3 FIXED FOREST INTERVAL LABEL' not in prompts.instructions_for(payload)


@pytest.mark.parametrize('direction,zh,en,op', [
    ('higher_is_positive', '分数越高越倾向阳性', 'Higher scores indicate positive outcomes', '>='),
    ('lower_is_positive', '分数越低越倾向阳性', 'Lower scores indicate positive outcomes', '<='),
])
@pytest.mark.parametrize('language', ['zh-CN', 'en'])
def test_roc_annotation_defines_anonymous_encoding_and_confirmed_score_direction(direction, zh, en, op, language):
    payload = {'figure_kind': 'roc_curve', 'legacy_contract': 4, 'method': 'roc_auc',
               'language': language, 'presentation': {'schema_version': 2},
               'plot_config': {'verification_scope': 'independent_curve_calculation', 'direction': direction}}
    before = deepcopy(payload)
    instruction = prompts.instructions_for(payload)
    assert '匿名绘图编码1为阳性，0为阴性' in instruction
    assert 'Anonymous plotting code 1 is positive and 0 is negative' in instruction
    assert zh in instruction and en in instruction
    assert f'score {op} threshold' in instruction
    assert 'Do not guess or disclose original category identities from these anonymous codes' in instruction
    assert '评估角色为用户声明，程序未独立核验其真实性' in instruction
    assert 'The evaluation role is user-declared and has not been independently verified by the program' in instruction
    assert 'Do not change labels.caption, presentation.abbreviations or returned JSON' in instruction
    assert 'Do not select an optimal threshold or invent an AUC interval' in instruction
    assert payload == before


@pytest.mark.parametrize('change', [
    {'presentation': {'schema_version': 1}},
    {'legacy_contract': 3},
    {'method': 'other'},
    {'plot_config': {'verification_scope': 'independent_curve_calculation', 'direction': 'unknown'}},
    {'plot_config': {'verification_scope': 'other', 'direction': 'higher_is_positive'}},
])
def test_roc_annotation_does_not_guess_missing_or_unsupported_contract_fields(change):
    payload = {'figure_kind': 'roc_curve', 'legacy_contract': 4, 'method': 'roc_auc',
               'presentation': {'schema_version': 2},
               'plot_config': {'verification_scope': 'independent_curve_calculation', 'direction': 'higher_is_positive'}}
    payload.update(change)
    assert 'VERSION 3 ROC INTERPRETATION LABELS' not in prompts.instructions_for(payload)
    payload.pop('presentation', None)
    assert 'VERSION 3 ROC INTERPRETATION LABELS' not in prompts.instructions_for(payload)


def test_km_risk_table_and_coincident_censor_marks_remain_readable_at_true_positions():
    payload = {'figure_kind': 'kaplan_meier', 'legacy_contract': 4, 'method': 'kaplan_meier',
               'presentation': {'schema_version': 2},
               'plot_config': {'verification_scope': 'independent_curve_calculation', 'interval': 'greenwood_loglog_95'}}
    before = deepcopy(payload)
    instruction = prompts.instructions_for(payload)
    for required in ('risk-table title, row labels, counts and time ticks in the final renderer bounding-box checks',
                     'Keep the risk-table title separate from the main y-axis zero tick',
                     'distinct line styles and distinguishable censor symbols',
                     'Keep every censor-symbol center at its actual time and survival value; never jitter',
                     'Show each group line style and censor-symbol key in the dedicated legend',
                     'Do not offset coincident confidence bands or fabricate separation'):
        assert required in instruction
    assert payload == before
    payload['presentation']['schema_version'] = 1
    assert 'VERSION 3 KM READABILITY' not in prompts.instructions_for(payload)


@pytest.mark.parametrize('change', [
    {'legacy_contract': 3}, {'method': 'other'},
    {'plot_config': {'verification_scope': 'independent_curve_calculation', 'interval': 'unknown'}},
])
def test_km_readability_annotations_only_apply_to_the_fixed_supported_contract(change):
    payload = {'figure_kind': 'kaplan_meier', 'legacy_contract': 4, 'method': 'kaplan_meier',
               'presentation': {'schema_version': 2},
               'plot_config': {'verification_scope': 'independent_curve_calculation', 'interval': 'greenwood_loglog_95'}}
    payload.update(change)
    assert 'VERSION 3 KM READABILITY' not in prompts.instructions_for(payload)
