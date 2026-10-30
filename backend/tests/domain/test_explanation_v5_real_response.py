"""Offline replay of the retained completed provider output; no model or DB."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.core.exceptions import PlotError, StorageError
from app.domain.figure_workbench import explanations as e
from app.domain.figure_workbench.explanation_v5 import sentence_draft_v5, validate_draft_v5

FIXTURE = json.loads((Path(__file__).parents[1] / 'fixtures/figure_b07/real-v5-response-boxplot-en.json').read_text(encoding='utf-8'))


@pytest.fixture(autouse=True)
def postgres_schema():
    """Pure validation and rendering; deliberately bypass the database fixture."""
    yield None


@pytest.mark.parametrize('section', FIXTURE['draft'])
def test_each_actual_provider_section_accepts_normal_bound_english(section):
    draft = sentence_draft_v5(FIXTURE['payload'])
    draft[section] = FIXTURE['draft'][section]
    validate_draft_v5(draft, FIXTURE['payload'])


def test_actual_completed_response_round_trips_render_and_validate_saved():
    original = deepcopy(FIXTURE)
    saved = e.render(FIXTURE['bundle'], FIXTURE['draft'], {'model_call_id': 'offline-retained-call', 'response_id': FIXTURE['source_response_id']})
    assert saved['draft'] == FIXTURE['draft']
    assert e.validate_saved(FIXTURE['bundle'], saved) == saved
    assert len(saved['sections']) == 6
    assert 'independent participants' in saved['sections'][1]['text']
    bad = deepcopy(saved)
    bad['draft']['data'] = bad['draft']['data'].replace('do not establish', 'establish')
    with pytest.raises(StorageError):
        e.validate_saved(FIXTURE['bundle'], bad)
    assert FIXTURE == original


def test_actual_payload_instructions_and_model_input_digest_remain_frozen():
    from app.domain.model_usage.gateway import input_digest
    payload = e.build_payload(FIXTURE['bundle'])
    assert payload == FIXTURE['payload']
    assert e.instructions_for(payload) == FIXTURE['instructions']
    assert input_digest(instructions=e.instructions_for(payload), payload=payload) == FIXTURE['model_input_digest'] == '25bbfe273aa02bde856e1fbc570992ef31b81c13457e864ee5b18ed30f4a79c0'


@pytest.mark.parametrize('tail', [
    ' These record counts establish a count of independent participants.',
    ' These record counts do not establish a count of independent participants but independence is confirmed.',
    ' These record counts do not establish a count of independent participants, and the observations are independent.',
    ' These record counts do not establish a count of independent participants except that independence was verified.',
    ' Independent observations were confirmed.',
    ' Assessing independence requires considering {{limitation.2}}, which establishes independence.',
    ' Assessing independence requires considering {{data.valid}}.',
    ' The study uses a randomized design.',
    ' This figure uses an observational cohort.',
    ' The saved results show regression.',
    ' According to Smith et al., the saved results show {{data.valid}}.',
    ' This figure shows https://example.org.',
    ' They report 12 records.',
    ' They report two records.',
    ' They report both groups.',
    ' The mean is described by {{data.valid}}.',
    ' They report a significant improvement.',
    ' The saved results cause improvement.',
    ' This figure describes {{unknown.reference}}.',
    ' This figure describes {{facts.data.valid}}.',
    ' This figure describes {insert-template}.',
])
def test_actual_prose_still_rejects_unbound_claims_and_scope_bypasses(tail):
    draft = deepcopy(FIXTURE['draft'])
    draft['paper_text'] += tail
    with pytest.raises(PlotError):
        e.render(FIXTURE['bundle'], draft, {'model_call_id': 'offline', 'response_id': 'offline'})


@pytest.mark.parametrize('fragment', [
    'Report {{purpose.kind}}.',
    'Described by {{purpose.kind}}.',
    'Its type described by {{purpose.kind}}.',
    '{{purpose.kind}}.',
    'The displayed type: {{purpose.kind}}.',
])
def test_extra_grammar_does_not_accept_reference_or_passive_fragments(fragment):
    draft = deepcopy(FIXTURE['draft'])
    draft['purpose'] = 'This figure describes {{scope.variables}}. ' + fragment
    with pytest.raises(PlotError):
        e.render(FIXTURE['bundle'], draft, {'model_call_id': 'offline', 'response_id': 'offline'})


@pytest.mark.parametrize('section', ['data', 'paper_text'])
def test_safe_v5_independence_prose_remains_rejected_by_legacy_guard(section):
    from app.domain.figure_workbench.explanation_facts import validate_draft
    with pytest.raises(PlotError):
        validate_draft({section: FIXTURE['draft'][section]}, FIXTURE['payload'])


@pytest.mark.parametrize('tail', [
    ' This figure uses independent{{purpose.kind}} observations.',
    ' This figure uses regression{{scope.variables}}.',
    ' This figure describes {{purpose.kind}} according {{scope.variables}}to Smith.',
])
def test_tokens_cannot_hide_a_legacy_forbidden_word_boundary(tail):
    from app.domain.figure_workbench.explanation_facts import validate_draft
    draft = sentence_draft_v5(FIXTURE['payload'])
    draft['paper_text'] += tail
    with pytest.raises(PlotError):
        validate_draft(draft, FIXTURE['payload'])
    with pytest.raises(PlotError):
        validate_draft_v5(draft, FIXTURE['payload'])
