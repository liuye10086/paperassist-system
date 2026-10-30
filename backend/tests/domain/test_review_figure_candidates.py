"""Explicit figure adoption, frozen history and exact reference projection."""
from copy import deepcopy
import pytest
from tests.domain.test_review_science_candidates import materials


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def figure_materials():
    snapshot, analysis = materials()
    analysis['snapshot_json']['source']['file_id'] = 'file'
    snapshot['sources'][1].update(sha256='b'*64)
    figure = snapshot['results_groups'][0]['figures'][0]
    figure.update(sha256='b'*64, panels=[], preview_url='/old')
    paragraph = dict(id='illustrations:main', text='Saved observation: Figure 1.', source_ids=['figure-source'],
                     cross_references=[dict(kind='figure', target_id='figure-old', number=1)], numeric_bindings=[], citations=[])
    snapshot['results_groups'][0]['paragraphs'] = [deepcopy(paragraph)]
    snapshot['sections'][3]['paragraphs'].append(deepcopy(paragraph))
    source = dict(id='new-figure', kind='figure', file_id='file', role='image_observation', label='New actual plot',
        sha256='c'*64, download_url='/new', content=dict(id='new-figure', analysis_run_id='new', language='en',
        sha256='c'*64, title='New plot', caption='New confirmed observation.', panels=[], facts_sha256='d'*64))
    adopted = dict(id='figure-adoption', snapshot_json=dict(item_id='opinion', item_revision=1, source=source,
        analysis_source=analysis['snapshot_json']['source'], supersedes_figure_id='figure-old',
        reason='Explicit redraw adoption.', affected_locations=[dict(kind='figure', id='figure-old')]))
    return snapshot, analysis, adopted


def test_explicit_figure_replaces_identity_caption_sources_and_both_body_views_only():
    from app.domain.review_rounds.figure_candidates import apply_figure_sources, figure_consistency_issues
    snapshot, analysis, adopted = figure_materials()
    before = deepcopy(snapshot)
    candidate, _, changes = apply_figure_sources(snapshot, [adopted], [analysis])
    assert snapshot == before
    new = candidate['results_groups'][0]['figures'][0]
    assert (new['id'], new['number'], new['sha256'], new['caption'], new['preview_url']) == ('new-figure', 1, 'c'*64, 'New confirmed observation.', '/new')
    assert new['source_ids'] == ['new-figure', 'new']
    assert {s['id'] for s in candidate['sources']} >= {'old', 'figure-source', 'new', 'new-figure'}
    for paragraph in [candidate['results_groups'][0]['paragraphs'][0], candidate['sections'][3]['paragraphs'][-1]]:
        assert paragraph['source_ids'] == ['new-figure']
        assert paragraph['cross_references'][0]['target_id'] == 'new-figure'
    assert changes and not any(i['category']=='illustration' for i in figure_consistency_issues(candidate, [adopted]))
    assert not any(i['category']=='illustration' for i in figure_consistency_issues(candidate, []))
    bad = deepcopy(candidate);bad['results_groups'][0]['figures'] = before['results_groups'][0]['figures']
    assert figure_consistency_issues(bad, []), 'Inherited explicit old figure replacement cannot be undone'


def test_only_selected_matching_actual_figure_and_caption_clear_redraw_wait():
    from app.domain.review_rounds.figure_candidates import apply_figure_sources
    from app.domain.review_rounds.science_candidates import science_unexecuted
    snapshot, analysis, adopted = figure_materials()
    item = dict(id='opinion', revision=1, original_text='Update statistics and redraw the figure.')
    assert science_unexecuted([item], [analysis], [], snapshot)
    candidate, _, _ = apply_figure_sources(snapshot, [adopted], [analysis])
    assert not science_unexecuted([item], [analysis], [adopted], candidate)
    candidate['results_groups'][0]['figures'][0]['caption'] = ''
    assert science_unexecuted([item], [analysis], [adopted], candidate)
    with pytest.raises(Exception, match='分析'):
        wrong = deepcopy(analysis);wrong['snapshot_json']['source']['id'] = 'different-run'
        apply_figure_sources(snapshot, [adopted], [wrong])


def test_empty_figure_optional_preserves_historical_revision_request_canonical_shape():
    from app.domain.review_rounds.revisions import revision_request_body
    from app.domain.review_rounds.revision_contracts import RevisionAdopt
    raw = dict(plan_revision=1, expected_current_revision=2, operations=[dict(item_id='opinion', kind='figure_caption',
        location_id='old', text='Caption.', reason='Explicit caption.', evidence_ids=['source'])], analysis_adoption_ids=[], preview_sha256='a'*64)
    assert revision_request_body(RevisionAdopt.model_validate(raw)) == RevisionAdopt.model_validate(raw).model_dump(mode='json', exclude={'figure_adoption_ids'})
    assert 'figure_adoption_ids' not in revision_request_body(RevisionAdopt.model_validate(raw | dict(figure_adoption_ids=[])))
    assert revision_request_body(RevisionAdopt.model_validate(raw | dict(figure_adoption_ids=['selected'])))['figure_adoption_ids'] == ['selected']


def test_explicit_figure_alone_is_an_operation_but_old_statistics_still_block():
    from app.domain.review_rounds.revision_contracts import RevisionPreview
    from app.domain.review_rounds.figure_candidates import apply_figure_sources,figure_consistency_issues
    snapshot,analysis,adopted=figure_materials()
    assert RevisionPreview.model_validate(dict(plan_revision=1,expected_current_revision=1,operations=[],figure_adoption_ids=['figure-adoption'])).figure_adoption_ids
    with pytest.raises(ValueError):RevisionPreview.model_validate(dict(plan_revision=1,expected_current_revision=1,operations=[]))
    candidate,_,_=apply_figure_sources(snapshot,[adopted])
    assert any(i['location']=='abstract:1' for i in figure_consistency_issues(candidate,[adopted]))


def test_new_caption_numeric_bindings_use_actual_new_analysis_and_reject_old_facts():
    from app.domain.review_rounds.figure_candidates import apply_figure_sources
    from app.domain.review_rounds.grounded import apply_operations
    snapshot,analysis,adopted=figure_materials()
    candidate,_,_=apply_figure_sources(snapshot,[adopted],[analysis])
    item=dict(id='opinion',category='figure',original_text='Clarify caption.',needs=[],flags=[],decision=None,status='pending',uncompleted_reason='Pending.')
    op=dict(item_id='opinion',kind='figure_caption',location_id='new-figure',text='n = 13',numeric_bindings=[dict(fact_id='analysis_run:new:/statistics/n',value='13')],evidence_ids=['new','new-figure'],reason='Bind exact new caption.')
    revised,_,_,_,_=apply_operations(candidate,[item],[],[op])
    assert revised['results_groups'][0]['figures'][0]['numeric_bindings']==op['numeric_bindings']


def test_shared_old_image_source_stays_for_retained_figure_reference():
    from app.domain.review_rounds.figure_candidates import apply_figure_sources
    snapshot,analysis,adopted=figure_materials()
    snapshot['results_groups'][0]['figures'].append(dict(id='retained',number=2,title='Retained',caption='Other image.',source_ids=['figure-source'],sha256='b'*64,panels=[]))
    for paragraph in [snapshot['results_groups'][0]['paragraphs'][0],snapshot['sections'][3]['paragraphs'][-1]]:
        paragraph['cross_references'].append(dict(kind='figure',target_id='retained',number=2))
        paragraph['text']+=' Figure 2.'
    candidate,_,_=apply_figure_sources(snapshot,[adopted],[analysis])
    assert candidate['results_groups'][0]['paragraphs'][0]['source_ids']==['figure-source','new-figure']


def test_new_figure_old_panel_reference_needs_explicit_body_edit():
    from app.domain.review_rounds.figure_candidates import apply_figure_sources
    from app.domain.review_rounds.grounded import apply_operations
    from app.domain.manuscripts.illustrations import check_bindings
    snapshot,analysis,adopted=figure_materials()
    for paragraph in [snapshot['results_groups'][0]['paragraphs'][0],snapshot['sections'][3]['paragraphs'][-1]]:
        paragraph['origin']='image_observation'
        paragraph['text']='Figure 1; Figure 1A.'
        paragraph['cross_references'].append(dict(kind='figure',target_id='figure-old',number=1,panel_label='A'))
    snapshot['results_groups'][0]['figures'][0]['panels']=[dict(label='A',description='Old panel.')]
    candidate,_,_=apply_figure_sources(snapshot,[adopted],[analysis])
    assert check_bindings(candidate['results_groups'],'en')
    item=dict(id='opinion',category='figure',original_text='Redraw the figure.',needs=[],flags=[],decision=None,status='pending',uncompleted_reason='Pending.')
    op=dict(item_id='opinion',kind='replace_paragraph',location_id='illustrations:main',text='Figure 1.',evidence_ids=['new-figure'],reason='Explicitly remove the old panel reference.')
    revised,_,_,_,_=apply_operations(candidate,[item],[],[op])
    assert not check_bindings(revised['results_groups'],'en')


def test_legacy_fixed_number_boxplot_is_linkable_but_not_a_new_external_numbered_adoption():
    from app.domain.review_rounds.figure_adoptions import FigureAdoptions
    from app.core.exceptions import StorageError
    service=object.__new__(FigureAdoptions)
    with pytest.raises(StorageError,match='外置编号'):
        service.validated_figure(None,'project',dict(project_id='project',task_type='boxplot',status='succeeded',result_figure_id='saved-old-fixed-number-plot'))


def replacement_chain():
    """Validated saved B/C domain inputs; no task, DB, PNG or provider fixture."""
    from app.domain.review_rounds.science_candidates import apply_analysis_sources
    from app.domain.review_rounds.figure_candidates import apply_figure_sources
    a,analysis,adopt_b=figure_materials()
    augmented,_,_=apply_analysis_sources(a,[analysis])
    b,_,_=apply_figure_sources(augmented,[adopt_b],[analysis])
    # Explicit user changes have already replaced all A statistical statements.
    for section in b['sections']:
        for paragraph in section['paragraphs']:
            if 'old' in paragraph.get('source_ids',[]):
                paragraph.update(source_ids=['new'],text='n = 13; P = 0.2',numeric_bindings=[
                    dict(fact_id='analysis_run:new:/statistics/n',value='13'),
                    dict(fact_id='analysis_run:new:/statistics/p_value/value',value='0.2')])
    source_c=deepcopy(adopt_b['snapshot_json']['source'])
    source_c.update(id='figure-c',sha256='e'*64,download_url='/c')
    source_c['content'].update(id='figure-c',sha256='e'*64,title='C plot',caption='C confirmed caption.',figure_config_version_id='independent-current-config-c')
    adopt_c=dict(id='adopt-c',snapshot_json=dict(item_id='next-opinion',item_revision=1,source=source_c,
        analysis_source=deepcopy(analysis['snapshot_json']['source']),supersedes_figure_id='new-figure',reason='Next explicit redraw.'))
    c,_,_=apply_figure_sources(b,[adopt_c])
    return a,b,c,adopt_b,adopt_c


def test_replacement_chain_validates_only_current_endpoint_and_preserves_historical_b():
    from app.domain.review_rounds.figure_candidates import figure_consistency_issues
    from app.domain.literature.service import digest
    a,b,c,adopt_b,adopt_c=replacement_chain()
    originals=deepcopy((a,b,c))
    assert not figure_consistency_issues(b,[adopt_b])
    assert not figure_consistency_issues(c,[adopt_c]), 'A -> B -> C displays C while retaining B material'
    assert not figure_consistency_issues(c), 'Historical rechecks use the same inherited complete chain'
    assert len(c['review_figure_provenance'])==2
    assert c['review_figure_provenance'][:1]==b['review_figure_provenance']
    assert all(source in c['sources'] for source in b['sources'])
    assert [digest(s) for s in (a,b,c)]==[digest(s) for s in originals]
    assert not figure_consistency_issues(b), 'Checking later C never changes sealed historical B'
    supplied=deepcopy(c);figure=supplied['results_groups'][0]['figures'][0]
    figure.update(caption='Explicit user caption without new numeric claims.',caption_status='supplied',caption_origin='user_provided')
    assert not figure_consistency_issues(supplied), 'Explicit supplied captions retain the existing public-check contract'


@pytest.mark.parametrize('bad',['reinsert-a','reinsert-b','missing-c','missing-caption','candidate-caption','different-source-caption','wrong-c-sha','missing-historical-b-source','wrong-historical-b-sha'])
def test_replacement_chain_still_blocks_old_figures_and_invalid_terminal_or_history(bad):
    from app.domain.review_rounds.figure_candidates import figure_consistency_issues
    a,b,c,_,adopt_c=replacement_chain()
    assert not figure_consistency_issues(c,[adopt_c])
    wrong=deepcopy(c);figures=wrong['results_groups'][0]['figures']
    if bad=='reinsert-a':figures.append(deepcopy(a['results_groups'][0]['figures'][0]))
    elif bad=='reinsert-b':figures.append(deepcopy(b['results_groups'][0]['figures'][0]))
    elif bad=='missing-c':figures.clear()
    elif bad=='missing-caption':figures[0]['caption']=''
    elif bad=='candidate-caption':figures[0]['caption_status']='candidate'
    elif bad=='different-source-caption':figures[0]['caption']='Text differs from the fixed C source caption.'
    elif bad=='wrong-c-sha':figures[0]['sha256']='f'*64
    elif bad=='missing-historical-b-source':wrong['sources']=[s for s in wrong['sources'] if s['id']!='new-figure']
    elif bad=='wrong-historical-b-sha':next(s for s in wrong['sources'] if s['id']=='new-figure')['sha256']='f'*64
    assert any(i['category']=='illustration' and i['severity']=='error' for i in figure_consistency_issues(wrong,[adopt_c]))


def test_replacement_chain_keeps_inherited_analysis_supersession_checks():
    from app.domain.review_rounds.figure_candidates import figure_consistency_issues
    _,_,c,adopt_b,adopt_c=replacement_chain()
    assert not figure_consistency_issues(c,[adopt_c])
    wrong=deepcopy(c);paragraph=next(s for s in wrong['sections'] if s['id']=='abstract')['paragraphs'][0]
    paragraph.update(source_ids=['old'],text='n = 8',numeric_bindings=[dict(fact_id='analysis_run:old:/statistics/n',value='8')])
    issues=figure_consistency_issues(wrong,[adopt_c])
    assert any(i['category']=='source' and i['location']==paragraph['id'] and i['id'].endswith(adopt_b['id']) for i in issues)


def test_constructible_back_edge_cannot_evade_replacement_chain_by_removing_current_figure():
    from app.domain.review_rounds.figure_candidates import apply_figure_sources,figure_consistency_issues
    from app.domain.review_rounds.grounded import apply_operations
    _,b,c,adopt_b,_=replacement_chain()
    assert not figure_consistency_issues(c)
    # B can still be a saved successful task of an independently current config.
    # Reusing that retained validated source for C -> B constructs a real back edge.
    back=deepcopy(adopt_b);back['id']='back-to-b';back['snapshot_json'].update(item_id='back-opinion',supersedes_figure_id='figure-c')
    cyclic,_,_=apply_figure_sources(c,[back])
    assert any(i['category']=='illustration' for i in figure_consistency_issues(cyclic,[back]))
    item=dict(id='back-opinion',category='figure',original_text='Remove the current figure.',needs=[],flags=[],decision=None,status='pending',uncompleted_reason='Pending.')
    op=dict(item_id='back-opinion',kind='remove_figure',location_id='new-figure',evidence_ids=['new-figure'],reason='Explicit removal cannot hide the cyclic adoption.')
    removed,_,_,_,_=apply_operations(cyclic,[item],[],[op])
    assert not removed['results_groups'][0]['figures']
    assert any(i['category']=='illustration' for i in figure_consistency_issues(removed,[back]))
