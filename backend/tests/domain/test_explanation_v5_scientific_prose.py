"""Retained logistic response and typed scientific English boundaries; offline."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.core.exceptions import PlotError
from app.domain.figure_workbench import explanations as e
from app.domain.figure_workbench.explanation_v5 import sentence_draft_v5, validate_draft_v5
from tests.domain.test_explanation_v5_real_response import FIXTURE as BOX

LOGISTIC = json.loads((Path(__file__).parents[1] / 'fixtures/figure_b07/real-v5-response-logistic-en.json').read_text(encoding='utf-8'))


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


@pytest.mark.parametrize('section', LOGISTIC['draft'])
def test_each_retained_logistic_section_is_complete_bound_scientific_prose(section):
    draft = sentence_draft_v5(LOGISTIC['payload'])
    draft[section] = LOGISTIC['draft'][section]
    validate_draft_v5(draft, LOGISTIC['payload'])


def test_retained_logistic_response_round_trips_without_metric_label_duplication():
    before = deepcopy(LOGISTIC)
    saved = e.render(LOGISTIC['bundle'], LOGISTIC['draft'], {'model_call_id': 'offline-retained-logistic', 'response_id': LOGISTIC['source_response_id']})
    assert e.validate_saved(LOGISTIC['bundle'], saved) == saved
    assert saved['draft'] == LOGISTIC['draft']
    result = saved['sections'][3]
    for phrase, ref in [('residual degrees of freedom', 'modeling.df_residual'), ('log likelihood', 'modeling.log_likelihood'), ('deviance', 'modeling.deviance'), ('Akaike information criterion', 'modeling.aic')]:
        fact = LOGISTIC['payload']['facts'][ref]
        assert fact['label'] + ': ' + fact['value'] in result['text']
        assert phrase + ' of ' + fact['label'] not in result['text']
        assert {'key': ref, 'label': fact['label'], 'value': fact['value']} in result['evidence']
    assert 'of Residual degrees of freedom:' not in result['text']
    assert 'of Log likelihood:' not in result['text']
    assert LOGISTIC == before


def test_retained_logistic_input_bytes_semantics_and_model_digest_do_not_change():
    from app.domain.model_usage.gateway import input_digest
    payload = e.build_payload(LOGISTIC['bundle'])
    assert payload == LOGISTIC['payload']
    assert e.instructions_for(payload) == LOGISTIC['instructions']
    assert input_digest(instructions=e.instructions_for(payload), payload=payload) == LOGISTIC['model_input_digest'] == '86dc2a53098df11bdb2a200a1bb7f93bbb363a692074ce0daff9e152644d759c'


@pytest.mark.parametrize('sentence', [
    'The figure contains {{scope.variables}} and depicts {{purpose.kind}}.',
    'The figure retains {{scope.variables}} and presents {{purpose.kind}}.',
    'The figure states {{scope.variables}} and specifies {{purpose.kind}}.',
    'The figure can describe {{scope.variables}} using {{purpose.kind}}.',
    'The figure is presented as {{purpose.kind}} and describes {{scope.variables}}.',
    'The figure has been described by {{scope.variables}} using {{purpose.kind}}.',
    'The figure must consider {{scope.variables}} using {{purpose.kind}}.',
    'The variables are represented by {{scope.variables}} using {{purpose.kind}}.',
    'This figure summarizes {{scope.variables}} with {{purpose.kind}}.',
])
def test_regular_finite_auxiliary_modal_and_passive_constructions(sentence):
    draft = sentence_draft_v5(LOGISTIC['payload'])
    draft['purpose'] = sentence
    validate_draft_v5(draft, LOGISTIC['payload'])


@pytest.mark.parametrize('fixture, phrase, ref', [
    (BOX, 'mean', 'overall.mean'), (BOX, 'median', 'overall.median'),
    (BOX, 'standard deviation', 'overall.std'), (BOX, 'lower quartile', 'overall.q1'),
    (BOX, 'upper quartile', 'overall.q3'), (BOX, 'Q1', 'overall.q1'), (BOX, 'Q3', 'overall.q3'),
    (BOX, 'interquartile range', 'overall.iqr'),
    (BOX, 'minimum', 'overall.min'), (BOX, 'maximum', 'overall.max'),
    (BOX, 'lower whisker', 'series.0.whislo'), (BOX, 'upper whisker', 'series.1.whishi'),
    (BOX, 'outlier count', 'series.0.outlier_count'),
    (LOGISTIC, 'valid-record count', 'modeling.n'), (LOGISTIC, 'parameter count', 'modeling.p'),
    (LOGISTIC, 'residual degrees of freedom', 'modeling.df_residual'),
    (LOGISTIC, 'log likelihood', 'modeling.log_likelihood'),
    (LOGISTIC, 'deviance', 'modeling.deviance'), (LOGISTIC, 'Akaike information criterion', 'modeling.aic'),
])
def test_explicit_scalar_metric_name_requires_its_exact_bound_identity(fixture, phrase, ref):
    draft = sentence_draft_v5(fixture['payload'])
    draft['results'] += ' The saved results report ' + phrase + ' of {{' + ref + '}}.'
    saved = e.render(fixture['bundle'], draft, {'model_call_id': 'offline', 'response_id': 'offline'})
    fact = fixture['payload']['facts'][ref]
    assert fact['label'] + ': ' + fact['value'] in saved['sections'][3]['text']
    assert phrase + ' of ' + fact['label'] not in saved['sections'][3]['text']
    assert saved['draft'] == draft
    assert {'key': ref, 'label': fact['label'], 'value': fact['value']} in saved['sections'][3]['evidence']


@pytest.mark.parametrize('fixture, phrase, ref', [
    (BOX, 'mean', 'overall.median'), (BOX, 'standard deviation', 'overall.mean'),
    (BOX, 'Q1', 'overall.q3'), (BOX, 'geometric mean', 'overall.mean'),
    (BOX, 'weighted mean', 'overall.mean'), (BOX, 'new mean', 'overall.mean'),
    (BOX, 'recomputed mean', 'overall.mean'),
    (LOGISTIC, 'residual degrees of freedom', 'modeling.p'),
    (LOGISTIC, 'log likelihood', 'modeling.aic'),
    (LOGISTIC, 'deviance', 'modeling.log_likelihood'),
    (LOGISTIC, 'Akaike information criterion', 'modeling.deviance'),
    (LOGISTIC, 'odds ratio', 'modeling.coefficients.1.inference'),
    (LOGISTIC, 'P value', 'modeling.p'),
])
def test_wrong_metric_identity_extra_statistical_qualifier_or_composite_fact_is_rejected(fixture, phrase, ref):
    draft = sentence_draft_v5(fixture['payload'])
    draft['results'] += ' The saved results report ' + phrase + ' of {{' + ref + '}}.'
    with pytest.raises(PlotError):
        validate_draft_v5(draft, fixture['payload'])


@pytest.mark.parametrize('tail', [
    ' It reports a deviance.', ' It reports a log likelihood.',
    ' It reports an Akaike information criterion.', ' It reports a parameter count.',
    ' It reports residual degrees of freedom.', ' It reports a deviance of 44.',
    ' It reports a log likelihood of two.',
    ' It reports a mean of {{modeling.n}} and an odds ratio of {{modeling.p}}.',
    ' It reports log likelihood after {{modeling.log_likelihood}}.',
    ' It reports log likelihood of extra {{modeling.log_likelihood}}.',
    ' It reports log likelihood of {{modeling.p}}{{modeling.log_likelihood}}.',
])
def test_metric_guard_still_rejects_free_numbers_names_nonadjacent_or_wrong_spans(tail):
    draft = sentence_draft_v5(LOGISTIC['payload'])
    draft['results'] += tail
    with pytest.raises(PlotError):
        validate_draft_v5(draft, LOGISTIC['payload'])


@pytest.mark.parametrize('tail', [
    ' Assessment of independence requires considering {{limitation.4}}.',
    ' Assessing independence requires considering {{limitation.4}}.',
    ' Review of causal interpretation must consider {{limitation.2}}.',
    ' The verification and causal boundaries are described by {{limitation.2}}.',
    ' These record counts do not establish a count of verified independent participants.',
    ' These record counts do not establish a count of independent participants.',
    ' The data contain {{data.valid}} valid records, which are not established here as verified independent participants.',
])
def test_cautious_boundary_language_requires_correct_scoped_semantics(tail):
    draft = sentence_draft_v5(LOGISTIC['payload'])
    draft['interpretation'] += tail
    validate_draft_v5(draft, LOGISTIC['payload'])


@pytest.mark.parametrize('tail', [
    ' Assessment of independence requires considering {{limitation.5}}.',
    ' Review of causal interpretation must consider {{limitation.5}}.',
    ' The verification and causal boundaries are described by {{limitation.5}}.',
    ' The causal effects are described by {{limitation.2}}.',
    ' Independence is confirmed by {{limitation.4}}.',
    ' The causal boundaries are confirmed by {{limitation.2}}.',
    ' The verification and causal boundaries are described by {{limitation.2}}, so causation is established.',
    ' Assessment of independence requires considering {{limitation.4}}, which confirms independence.',
    ' These record counts do not establish a count of verified independent participants, but independent observations were confirmed.',
    ' The data contain {{data.valid}} valid records, which are not established here as verified independent participants and independence is confirmed.',
    ' The saved results establish verified independent participants.',
    ' It states a randomized research design.',
    ' It reports a significant effect.',
    ' It reports regression{{scope.variables}}.',
    ' It describes {{purpose.kind}} according {{scope.variables}}to Smith.',
])
def test_meta_words_and_negation_cannot_authorize_a_positive_or_wrong_fact_claim(tail):
    draft = sentence_draft_v5(LOGISTIC['payload'])
    draft['interpretation'] += tail
    with pytest.raises(PlotError):
        validate_draft_v5(draft, LOGISTIC['payload'])


def test_empty_limit_does_not_authorize_causal_or_independence_prose():
    payload = deepcopy(LOGISTIC['payload'])
    for topic, ref in [('causal boundaries', 'limitation.2'), ('independence', 'limitation.4')]:
        payload['facts'][ref].update(raw='', value='')
        draft = sentence_draft_v5(payload)
        draft['interpretation'] += ' Assessment of ' + topic + ' requires considering {{' + ref + '}}.'
        with pytest.raises(PlotError):
            validate_draft_v5(draft, payload)


@pytest.mark.parametrize('fragment', [
    'The saved results {{purpose.kind}}.', 'Report {{purpose.kind}}.',
    'Contains {{purpose.kind}}.', 'Described as {{purpose.kind}}.',
    'Its type labeled {{purpose.kind}}.', 'Must consider {{purpose.kind}}.',
    'The type: {{purpose.kind}}.', '{{purpose.kind}}.',
])
def test_more_flexible_verbs_still_require_a_subject_and_finite_predicate(fragment):
    draft = sentence_draft_v5(LOGISTIC['payload'])
    draft['purpose'] = 'This figure describes {{scope.variables}}. ' + fragment
    with pytest.raises(PlotError):
        validate_draft_v5(draft, LOGISTIC['payload'])


@pytest.mark.parametrize('expired', [False, True])
def test_logistic_worker_uses_original_get_only_and_preserves_observation_gate(monkeypatch, expired):
    from tests.domain import test_explanation_v5_receipt_recovery as recovery
    monkeypatch.setattr(recovery, 'FIXTURE', LOGISTIC)
    recovery.test_existing_worker_retrieves_same_receipt_without_reserving_or_posting(monkeypatch, expired)


@pytest.mark.parametrize('tail', [
    ' The treatment establishes causation but the causal boundaries are described by {{limitation.2}}.',
    ' Independence is confirmed and the independence boundaries are described by {{limitation.4}}.',
    ' The causal effects have been established, and their causal boundaries are described by {{limitation.2}}.',
    ' Assessment of confirmed independence requires considering {{limitation.4}}.',
    ' Review of established causation requires considering {{limitation.2}}.',
    ' Assessment of proven independence requires considering {{limitation.4}}.',
    ' Review of verified causation requires considering {{limitation.2}}.',
    ' Assessment of assumed independence requires considering {{limitation.4}}.',
])
def test_neutral_topic_cannot_swallow_an_affirmative_predicate_or_modifier(tail):
    draft = sentence_draft_v5(LOGISTIC['payload'])
    draft['interpretation'] += tail
    with pytest.raises(PlotError):
        validate_draft_v5(draft, LOGISTIC['payload'])


def test_metric_deduplication_preserves_full_fact_labels_and_named_group_context():
    payload = BOX['payload']
    draft = sentence_draft_v5(payload)
    draft['results'] += ' The saved results report mean of {{overall.mean}}, mean of {{groups.0.mean}} for {{groups.0.label}}, and mean of {{groups.1.mean}} for {{groups.1.label}}.'
    saved = e.render(BOX['bundle'], draft, {'model_call_id': 'offline', 'response_id': 'offline'})
    text = saved['sections'][3]['text'].rsplit('The saved results report', 1)[-1]
    assert 'Overall: Mean: 5.5' in text
    assert 'Mean: 3 for Group label: A' in text and 'Mean: 8 for Group label: B' in text
    assert saved['draft'] == draft
    for ref in ('overall.mean', 'groups.0.mean', 'groups.1.mean'):
        fact = payload['facts'][ref]
        assert {'key': ref, 'label': fact['label'], 'value': fact['value']} in saved['sections'][3]['evidence']


@pytest.mark.parametrize('fragment', [
    'The figure is described by.', 'The {{purpose.kind}} is described by.',
    'The figure has been described by.', 'The figure is labeled as.',
    'The figure can be.', 'The figure is described by the.',
])
def test_auxiliary_or_passive_cannot_end_with_a_dangling_complement(fragment):
    draft = sentence_draft_v5(LOGISTIC['payload'])
    draft['purpose'] += ' ' + fragment
    with pytest.raises(PlotError):
        validate_draft_v5(draft, LOGISTIC['payload'])


@pytest.mark.parametrize('tail', [
    ' The saved results report mean of {{overall.mean}} (weighted).',
    ' The saved results report mean of {{overall.mean}}, computed geometrically.',
    ' The saved results report mean of {{overall.mean}} after re-estimation.',
])
def test_typed_metric_does_not_authorize_an_unbound_trailing_statistical_modifier(tail):
    draft = sentence_draft_v5(BOX['payload'])
    draft['results'] += tail
    with pytest.raises(PlotError):
        validate_draft_v5(draft, BOX['payload'])


@pytest.mark.parametrize('topic', ['observation independence', 'independence'])
def test_independent_cloud_refit_limit_is_not_an_observation_independence_fact(topic):
    draft = sentence_draft_v5(LOGISTIC['payload'])
    draft['interpretation'] += ' Assessment of ' + topic + ' requires considering {{limitation.2}}.'
    with pytest.raises(PlotError):
        validate_draft_v5(draft, LOGISTIC['payload'])


@pytest.mark.parametrize('tail', [
    ' These record counts do not establish a count of independent participants.',
    ' The data contain {{data.valid}} valid records, which are not established here as verified independent participants.',
])
def test_record_count_caution_needs_a_nonempty_observation_independence_limit(tail):
    payload = deepcopy(LOGISTIC['payload'])
    payload['facts']['limitation.4'].update(raw='', value='')
    draft = sentence_draft_v5(payload)
    draft['data'] += tail
    with pytest.raises(PlotError):
        validate_draft_v5(draft, payload)


@pytest.mark.parametrize('predicate', ['is', 'equals'])
@pytest.mark.parametrize('position', ['start', 'after_sentence'])
def test_the_same_typed_metric_sentence_has_position_independent_grammar(predicate, position):
    draft = sentence_draft_v5(BOX['payload'])
    sentence = 'The mean ' + predicate + ' {{overall.mean}}. '
    draft['results'] = sentence + draft['results'] if position == 'start' else draft['results'] + ' ' + sentence
    validate_draft_v5(draft, BOX['payload'])
    saved = e.render(BOX['bundle'], draft, {'model_call_id': 'offline', 'response_id': 'offline'})
    assert 'The mean ' + predicate + ' Overall: Mean: 5.5.' in saved['sections'][3]['text']


@pytest.mark.parametrize('fragment', [
    'The saved report: {{purpose.kind}}.', 'The figure label: {{purpose.kind}}.',
    'These record counts {{purpose.kind}}.', 'The saved report {{purpose.kind}}.',
    'The displayed labels: {{purpose.kind}}.',
])
def test_nominal_report_label_or_record_count_cannot_masquerade_as_a_finite_verb(fragment):
    draft = sentence_draft_v5(LOGISTIC['payload'])
    draft['purpose'] += ' ' + fragment
    with pytest.raises(PlotError):
        validate_draft_v5(draft, LOGISTIC['payload'])


@pytest.mark.parametrize('negated_modal', ['do not', 'cannot', 'must not', 'should not'])
def test_existing_record_count_caution_modal_variants_are_consistently_complete(negated_modal):
    draft = sentence_draft_v5(LOGISTIC['payload'])
    draft['interpretation'] += ' These record counts ' + negated_modal + ' establish a count of independent participants.'
    validate_draft_v5(draft, LOGISTIC['payload'])
