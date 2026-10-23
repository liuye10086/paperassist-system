"""Exact source supersession checks; no numerical engine or external calls."""
from copy import deepcopy
import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def materials():
    from app.domain.manuscript_writing.contracts import SECTION_IDS
    paragraph = lambda pid, text: dict(id=pid, text=text, source_ids=['old'], numeric_bindings=[], citations=[], origin='user_provided')
    snapshot = dict(output_language='en', sections=[dict(id=s, paragraphs=[]) for s in SECTION_IDS],
        sources=[dict(id='old', kind='analysis_run', role='computed_results', content=dict(statistics=dict(n=8, p_value=dict(value=0.03)))),
                 dict(id='figure-source', kind='figure', role='image_observation', content=dict(analysis_run_id='old'))],
        results_groups=[dict(id='main', title='Results', paragraphs=[], tables=[dict(id='table-old', number=1, source_ids=['old'], rows=[['Old', '8']], columns=['Fact', 'Value'], title='Table 1')],
        figures=[dict(id='figure-old', number=1, title='Old figure', caption='Original plot.', source_ids=['figure-source'], caption_status='source', caption_origin='source')])], references=[], issues=[])
    for section in snapshot['sections']:
        if section['id'] in ('abstract', 'results', 'discussion'):
            section['paragraphs'] = [paragraph(section['id'] + ':1', 'n = 8; P = 0.03')]
    source = dict(id='new', kind='analysis_run', role='computed_results', label='New computed statistics', sha256='a'*64,
                  content=dict(statistics=dict(n=13, p_value=dict(value=0.2))))
    adoption = dict(id='adopted', snapshot_json=dict(id='adopted', item_id='opinion', source=source,
        supersedes_source_ids=['old'], affected_locations=[dict(kind='paragraph', id='results:1')],
        reason='Adopt actual local analysis.', pending=['New figure remains pending.']))
    return snapshot, adoption


def test_superseded_results_keep_old_sources_and_transcribe_only_fixed_new_tables():
    from app.domain.review_rounds import science_candidates as science
    assert hasattr(science, 'apply_analysis_sources'), 'Receipt-backed candidate source adoption is missing'
    snapshot, adoption = materials()
    original = deepcopy(snapshot)
    candidate, _, changes = science.apply_analysis_sources(snapshot, [adoption])
    assert snapshot == original
    assert [s['id'] for s in candidate['sources']] == ['old', 'figure-source', 'new']
    assert candidate['results_groups'][0]['tables'][0]['source_ids'] == ['new']
    assert any(row[1] == '13' for row in candidate['results_groups'][0]['tables'][0]['rows'])
    assert candidate['review_analysis_provenance'][0]['adoption_id'] == 'adopted'
    issues = science.analysis_consistency_issues(candidate, [adoption])
    assert {i['location'] for i in issues if i['severity'] == 'error'} >= {'abstract:1', 'results:1', 'discussion:1', 'caption:figure-old'}
    assert changes


def test_exact_new_fact_bindings_and_old_plot_removal_pass_existing_public_check():
    from app.domain.review_rounds import science_candidates as science
    assert hasattr(science, 'apply_analysis_sources'), 'New scientific source projection is missing'
    from app.domain.review_rounds.grounded import apply_operations
    from app.domain.manuscript_review.checks import check_snapshot
    snapshot, adoption = materials()
    candidate, authority, _ = science.apply_analysis_sources(snapshot, [adoption])
    item = dict(id='opinion', category='statistics', original_text='Update saved statistics.', needs=[], flags=[], decision=None, status='pending', uncompleted_reason='Pending.')
    bindings = [dict(fact_id='analysis_run:new:/statistics/n', value='13'), dict(fact_id='analysis_run:new:/statistics/p_value/value', value='0.2')]
    operations = [dict(item_id='opinion', kind='replace_paragraph', location_id=pid, text='n = 13; P = 0.2', numeric_bindings=bindings,
        evidence_ids=['new'], reason='Adopt verified exact statistics.') for pid in ('abstract:1', 'results:1', 'discussion:1')]
    operations.append(dict(item_id='opinion', kind='remove_figure', location_id='figure-old', evidence_ids=['new'], reason='Old plot depends on superseded statistics; new plot pending.'))
    revised, changes, skipped, strict, _ = apply_operations(candidate, [item], [], operations, writing_context=authority)
    assert not skipped and len(changes) == 4
    assert revised['results_groups'][0]['figures'] == []
    assert snapshot['results_groups'][0]['figures']
    assert not science.analysis_consistency_issues(revised, [adoption])
    assert not [i for i in check_snapshot(revised, strict_locations=strict, writing_context=authority) if i['severity'] == 'error']
    wrong = deepcopy(revised)
    wrong['sections'][3]['paragraphs'][0]['text'] = 'n = 13; P = 0.03'
    assert any(i['category'] == 'numeric' and i['severity'] == 'error' for i in check_snapshot(wrong, strict_locations=strict, writing_context=authority))


def test_future_revision_cannot_reintroduce_already_superseded_analysis():
    from app.domain.review_rounds import science_candidates as science
    snapshot, adoption = materials()
    candidate, _, _ = science.apply_analysis_sources(snapshot, [adoption])
    assert science.analysis_consistency_issues(candidate, []), 'Inherited supersession must remain enforced in later rounds without a new adoption'


def test_new_plot_request_keeps_material_wait_after_actual_numeric_adoption():
    from app.domain.review_rounds import science_candidates as science
    assert hasattr(science, 'science_unexecuted'), 'Missing actual plot must not become a completed scientific opinion'
    _, adoption = materials()
    items = [dict(id='opinion', category='statistics', original_text='Update statistics and redraw the figure.'),
             dict(id='caption', category='figure', original_text='Clarify the figure caption.')]
    skipped = science.science_unexecuted(items, [adoption])
    assert len(skipped) == 1 and skipped[0]['item_id'] == 'opinion' and skipped[0]['status'] == 'waiting_material'


def test_explicit_old_figure_removal_clears_only_rewritten_canonical_cross_reference():
    from app.domain.manuscript_writing.contracts import SECTION_IDS
    from app.domain.manuscripts.illustrations import attach_references, check_bindings
    from app.domain.review_rounds.grounded import apply_operations
    from app.domain.manuscript_review.checks import check_snapshot
    figures = [dict(id=identity, number=n, title=identity, caption='Saved observation.', caption_status='source',
        caption_origin='source', source_ids=['material'], panels=[]) for n, identity in enumerate(('old-figure', 'retained-figure'), 1)]
    groups = [dict(id='main', title='Figures', paragraphs=[], figures=figures, tables=[])]
    attach_references(groups, 'en', lambda *args: None)
    canonical = groups[0]['paragraphs'][0]
    assert canonical['id'] == 'illustrations:main' and len(canonical['cross_references']) == 2
    snapshot = dict(output_language='en', sources=[dict(id='material', kind='document_version', content=dict(text='Saved figures.'))],
        sections=[dict(id=identity, paragraphs=[deepcopy(canonical)] if identity == 'results' else []) for identity in SECTION_IDS],
        results_groups=groups, references=[], issues=[])
    item = dict(id='remove', category='figure', original_text='Remove the superseded figure.', needs=[], flags=[], decision=None, status='pending', uncompleted_reason='Pending.')
    operations = [dict(item_id='remove', kind='remove_figure', location_id='old-figure', evidence_ids=['material'], reason='Explicitly remove the old observation.'),
        dict(item_id='remove', kind='replace_paragraph', location_id=canonical['id'], evidence_ids=['material'], text='Retained image observation: Figure 2.', reason='Explicitly remove the old figure reference from the paragraph.')]
    candidate, _, skipped, strict, _ = apply_operations(snapshot, [item], [], operations)
    assert not skipped
    paragraph = next(s for s in candidate['sections'] if s['id'] == 'results')['paragraphs'][0]
    assert paragraph['cross_references'] == [canonical['cross_references'][1]], 'Explicit rewritten figure prose must drop the removed target binding only'
    assert not check_bindings(candidate['results_groups'], 'en')
    assert not [i for i in check_snapshot(candidate, strict_locations=strict) if i['severity'] == 'error']
    still_referencing = deepcopy(operations)
    still_referencing[1]['text'] = 'Retained image observations: Figure 1; Figure 2.'
    blocked, _, _, strict, _ = apply_operations(snapshot, [item], [], still_referencing)
    assert any(i['category'] == 'illustration' and i['severity'] == 'error' for i in check_snapshot(blocked, strict_locations=strict))
    unedited, _, _, strict, _ = apply_operations(snapshot, [item], [], operations[:1])
    assert any(i['category'] == 'illustration' and i['severity'] == 'error' for i in check_snapshot(unedited, strict_locations=strict))
    assert len(canonical['cross_references']) == 2 and len(snapshot['results_groups'][0]['figures']) == 2
