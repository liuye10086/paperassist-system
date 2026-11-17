from copy import deepcopy
from io import BytesIO

import pytest
from docx import Document
from docx.oxml.ns import qn

from app.adapters.manuscript_docx import build_manuscript_docx
from app.domain.journals.display import apply, plan
from app.domain.journals.format_contracts import Requirement
from app.domain.journals.format_rules import check_format
from app.domain.literature_citations.formatter import render_paragraphs
from app.domain.manuscript_writing.article_contract import STRUCTURES


JOURNAL = 'Frontiers in Cardiovascular Medicine'
TYPES = 'https://www.frontiersin.org/journals/cardiovascular-medicine/for-authors/article-types'
GUIDE = 'https://www.frontiersin.org/guidelines/author-guidelines'
STYLES = 'https://www.frontiersin.org/Design/pdf/Frontiers_Journal_style_table.pdf'
OVERVIEW = 'https://www.frontiersin.org/for-authors/where-to-publish/article-types'
STYLE = 'Frontiers Vancouver (Numbered)'
HEADINGS = 'Abstract,\nIntroduction\nSubsections relevant for the subject\nDiscussion.'
LAYOUT = 'The entire document should be single-spaced and must contain page and line numbers'


def guide_rule(source, key, value, quote):
    return dict(id=f'{source}:{key}', source_id=source, source_version='checked', key=key, value=value,
                article_type='review', status='known', quote=quote, location='line:1')


def reviewed_input():
    fields = dict(article_type='journal', title='Cells in the heart', journal_abbreviation='Nat Cardiovasc Res',
                  year='2022', date='2022 Mar', volume='1', issue='3', pages='263-280', doi='10.1038/test-one')
    references = [
        fields | dict(authors=[dict(family='Bedi', initials='KC', suffix='Jr'),
                              *[dict(family=f'Author{i}', initials='A') for i in range(2, 8)]]),
        fields | dict(authors=[dict(family='Lee', initials='M')], pages='', article_number='6', doi='10.3389/test-two'),
    ]
    bindings = [dict(project_reference_id=f'reference-{i}', metadata=metadata)
                for i, metadata in enumerate(references, 1)]
    fragments = [dict(id=f'citation-{i}', fragments=[dict(kind='claim', text=f'Supported claim {i}', bindings=[b]),
                                                   dict(kind='text', text='.')]) for i, b in enumerate(bindings, 1)]
    rendered = render_paragraphs(fragments)
    title='Reviewed heart manuscript'
    sections = [dict(id=s, paragraphs=[dict(id=s+'-body', text=title if s=='title' else 'Text for '+s,
                                           citations=[], origin='user_provided', source_ids=[])])
                for s in STRUCTURES['narrative_review']]
    for i, section_id in enumerate(('introduction', 'themes')):
        p = next(s['paragraphs'][0] for s in sections if s['id'] == section_id)
        p.update(text=rendered['paragraphs'][i]['text'], citations=[bindings[i]])
    return dict(schema_version=1, title=title, output_language='en', article_type='narrative_review',
                writing_provenance=dict(schema_version=2, verification_status='scientific_and_language_reviewed'),
                notice='Reviewed notice', issues=[], sources=[], methods=[], results_groups=[], sections=sections,
                references=rendered['references'], citation_snapshot=dict(paragraphs=fragments, output=rendered))


def confirmed_target():
    def guide(identity, url, source_text):
        return dict(id=identity, source_version='checked', source_text=source_text, source_type='official_local',
                    source_url=url, official_url=url, source_status='available', permission_status='allowed')

    requirements = [
        guide_rule('types', 'required_sections', ['Abstract', 'Introduction', 'Discussion'], HEADINGS),
        guide_rule('types', 'section_order', ['Abstract', 'Introduction', 'Discussion'], HEADINGS),
        guide_rule('guide', 'document_single_spacing', True, LAYOUT),
        guide_rule('guide', 'document_page_line_numbers', True, LAYOUT),
        guide_rule('styles', 'reference_style', STYLE, JOURNAL+'\n'+STYLE),
    ]
    return dict(article_type='review', confirmed_by='editor', synthetic=False,
                candidate=dict(profile=dict(name=JOURNAL, source_type='official_local', official_url=TYPES)),
                guide=guide('types', TYPES, HEADINGS),
                additional_guides=[guide('guide', GUIDE, LAYOUT), guide('styles', STYLES, JOURNAL+'\n'+STYLE)],
                selected_requirements=requirements, conflicts=[])


def test_scoped_frontiers_review_projects_frozen_text_and_renders_word():
    snapshot = reviewed_input()
    target = confirmed_target()
    original_snapshot = deepcopy(snapshot)
    original_file = build_manuscript_docx(snapshot, {}, customer_view=True)
    preview = plan(snapshot, target, [])
    assert {a['key'] for a in preview['actions']} == {'required_sections', 'document_single_spacing',
                                                      'document_page_line_numbers', 'reference_style'}
    assert not preview['unexecuted']
    assert all(a['evidence'][0]['source_version'] == 'checked' for a in preview['actions'])
    candidate = apply(snapshot, preview['actions'])
    assert snapshot == original_snapshot
    assert {k: v for k, v in candidate.items() if k != 'journal_display_context'} == original_snapshot
    assert not plan(candidate, target, [])['actions']
    assert build_manuscript_docx(snapshot, {}, customer_view=True) == original_file
    before = check_format(snapshot, target['selected_requirements'], [], target=target)
    after = check_format(candidate, target['selected_requirements'], [], target=target)
    assert [item['status'] for item in before['items'][:5]] == ['mismatch'] * 5
    assert [item['status'] for item in after['items'][:5]] == ['pass'] * 5

    word = Document(BytesIO(build_manuscript_docx(candidate, {}, customer_view=True)))
    old_word = Document(BytesIO(original_file))
    headings = [(p.text, p.style.name) for p in word.paragraphs if p.style.name.startswith('Heading')]
    assert headings == [(s, 'Heading 1') for s in ('Abstract', 'Introduction', 'Literature sources and inclusion scope',
                                                    'Thematic synthesis', 'Discussion')] + [
        ('Conclusion', 'Heading 2'), ('References', 'Heading 1')]
    cite_text = [p.text for p in word.paragraphs if p.text.startswith('Supported claim')]
    assert cite_text == [p.text for p in old_word.paragraphs if p.text.startswith('Supported claim')]
    assert cite_text == ['Supported claim 1 (1).', 'Supported claim 2 (2).']
    assert [p.text for p in word.paragraphs if 'doi:' in p.text] == [
        '1. Bedi KC Jr, Author2 A, Author3 A, Author4 A, Author5 A, Author6 A, et al. '
        'Cells in the heart. Nat Cardiovasc Res. (2022) 1:263-280. doi: 10.1038/test-one',
        '2. Lee M. Cells in the heart. Nat Cardiovasc Res. (2022) 1:6. doi: 10.3389/test-two',
    ]
    assert word.styles['Normal'].paragraph_format.line_spacing == 1
    assert old_word.styles['Normal'].paragraph_format.line_spacing == 1.15
    for section in word.sections:
        line = section._sectPr.find(qn('w:lnNumType'))
        assert line is not None and line.get(qn('w:countBy')) == '1' and line.get(qn('w:restart')) == 'continuous'
        assert [x.get(qn('w:instr')) for x in section.footer._element.iter(qn('w:fldSimple'))] == ['PAGE']
        for block in (word.element, section.header._element, section.footer._element):
            for p in block.iter(qn('w:p')):
                spacing=p.find(qn('w:pPr')).find(qn('w:spacing'))
                assert spacing.get(qn('w:line')) == '240' and spacing.get(qn('w:lineRule')) == 'auto'
    assert old_word.sections[0]._sectPr.find(qn('w:lnNumType')) is None


def test_frontiers_rules_require_the_confirmed_source_and_verified_reference_metadata():
    snapshot = reviewed_input()
    target = confirmed_target()
    unrelated = deepcopy(target)
    unrelated['candidate']['profile']['name'] = 'Other journal'
    assert not plan(snapshot, unrelated, [])['actions']
    unavailable = [dict(source_id='guide', blocks_rules=True, message='Unavailable')]
    actions = {a['key'] for a in plan(snapshot, target, unavailable)['actions']}
    assert actions == {'required_sections', 'reference_style'}
    pending = deepcopy(snapshot)
    pending['writing_provenance']['verification_status'] = 'scientific_reviewed_language_pending'
    assert not plan(pending, target, [])['actions']
    invalid_reference = deepcopy(snapshot)
    invalid_reference['citation_snapshot']['paragraphs'][0]['fragments'][0]['bindings'][0]['metadata']['year'] = ''
    assert 'reference_style' not in {a['key'] for a in plan(invalid_reference, target, [])['actions']}
    with pytest.raises(ValueError):
        Requirement(id='layout', key='document_single_spacing', status='known', value=True, quote='Some spacing', location='line:1')


def submission_target():
    target = confirmed_target()
    overview = dict(target['guide'], id='overview', source_url=OVERVIEW, official_url=OVERVIEW,
                    source_text='Review\nFigures and/or tables (combined)')
    target['additional_guides'].append(overview)
    requirements = (
        ('types', 'word_limit', 12000, 'Review articles are peer-reviewed and have a maximum word count of 12,000.'),
        ('guide', 'document_submission_layout', True, 'The manuscript length includes only the main body of the text, '
         'footnotes, and all citations within it.\nPlease indicate the number of words and the number of figures and '
         'tables included in your manuscript on the first page.'),
        ('guide', 'figure_captions', True, 'Figure captions should be placed at the end of the manuscript.'),
        ('guide', 'table_captions', True, 'Table captions must be placed immediately before the table.'),
        ('guide', 'table_editable_at_end', True, 'Tables should be inserted at the end of the manuscript in an editable format.'),
        ('guide', 'figure_references', True, 'Ensure that each figure is mentioned in the text and in numerical order.'),
        ('guide', 'table_references', True, 'Ensure that each table is mentioned in the text and in numerical order.'),
        ('guide', 'figure_submission', True, 'We require figures to be submitted individually'),
        ('guide', 'dpi', 300, 'All images must have a resolution of 300 dpi at final size.'),
        ('guide', 'table_page_span', True, 'Large tables covering several pages cannot be included in the final PDF'),
        ('overview', 'figure_table_limit', 15, 'Figures/Tables: 15 maximum'),
        ('overview', 'abstract_word_limit', 350, 'Maximum abstract length: 350 words'),
    )
    guides = dict(types=target['guide'], guide=target['additional_guides'][0], overview=overview)
    for source, key, value, quote in requirements:
        guides[source]['source_text'] += '\n' + quote
        target['selected_requirements'].append(guide_rule(source, key, value, quote))
    return target


def checks(snapshot, target, **kwargs):
    result = check_format(snapshot, target['selected_requirements'], [], target=target, **kwargs)
    return {row['key']: row for row in result['items']}


def test_frontiers_word_limit_uses_frozen_body_and_citations_at_official_boundary():
    snapshot = reviewed_input()
    intro = next(s['paragraphs'][0] for s in snapshot['sections'] if s['id'] == 'introduction')
    for section in snapshot['sections']:
        if section['id'] != 'title':
            section['paragraphs'][0]['text'] = ''
    snapshot['sections'][1]['paragraphs'][0]['text'] = 'ignored ' * 12001
    snapshot['acknowledgements'] = 'also excluded ' * 12001
    intro['text'] = 'Heart (1) ' + 'fibrosis ' * 11998
    target = submission_target()
    at_limit = checks(snapshot, target)['word_limit']
    assert (at_limit['status'], at_limit['actual'], at_limit['expected']) == ('pass', 12000, 12000)
    assert {e['source_id'] for e in at_limit['evidence']} == {'types', 'guide'}
    intro['text'] += '(2)'
    over_limit = checks(snapshot, target)['word_limit']
    assert (over_limit['status'], over_limit['actual']) == ('mismatch', 12001)
    warnings = [dict(source_id='guide', blocks_rules=True, message='Unavailable')]
    assert checks(snapshot, target, warnings=warnings)['word_limit']['status'] == 'pending_verification'
    target['article_type'] = 'mini review'
    assert checks(snapshot, target)['word_limit']['status'] == 'pending_verification'


def test_frontiers_zero_figure_review_reports_counts_without_certifying_figure_files():
    snapshot = reviewed_input()
    target = submission_target()
    preview = plan(snapshot, target, [])
    candidate = apply(snapshot, preview['actions'])
    word = Document(BytesIO(build_manuscript_docx(candidate, {}, customer_view=True)))
    result = checks(candidate, target)
    words = result['word_limit']['actual']
    assert word.paragraphs[1].text == f'Word count: {words} | Figures: 0 | Tables: 0'
    assert result['document_submission_layout']['status'] == 'pass'
    assert result['figure_submission']['status'] == result['dpi']['status'] == 'manual'
    assert result['dpi']['actual'] is None
    assert 'figure_limit' not in result and 'table_limit' not in result
    assert (result['figure_table_limit']['status'], result['figure_table_limit']['actual']) == ('pass', 0)
    assert not any(p.text in ('Figure captions', 'Tables') for p in word.paragraphs)


def illustrated_review():
    snapshot = reviewed_input()
    for section in snapshot['sections']:
        if section['id'] == 'introduction':
            section['paragraphs'].append(dict(id='illustration-callouts', origin='user_provided', citations=[],
                                              text='Figure 1 and Table 1 summarize the published evidence.'))
    figure = dict(id='illustration-1', number=1, title='Published cardiac studies',
                  caption='Overview of findings from the cited literature.', caption_status='supplied',
                  panels=[dict(label='A', description='Cardiac atlases.')])
    table = dict(id='comparison-1', number=1, title='Table 1. Evidence comparison',
                 columns=['Study', 'Method'], rows=[['Study A', 'Spatial transcriptomics']])
    snapshot['results_groups'] = [dict(id='illustrations', title='Published evidence', paragraphs=[],
                                      figures=[figure], tables=[table])]
    return snapshot


def test_frontiers_word_places_figure_legends_and_editable_tables_at_end():
    snapshot = illustrated_review()
    original = deepcopy(snapshot)
    target = submission_target()
    assert checks(snapshot, target)['document_submission_layout']['status'] == 'mismatch'
    candidate = apply(snapshot, plan(snapshot, target, [])['actions'])
    assert {k: v for k, v in candidate.items() if k != 'journal_display_context'} == original == snapshot
    word = Document(BytesIO(build_manuscript_docx(candidate, {}, customer_view=True)))
    result = checks(candidate, target)
    assert all(result[key]['status'] == 'pass'
               for key in ('document_submission_layout', 'figure_captions', 'table_captions',
                           'table_editable_at_end', 'figure_references', 'table_references'))
    assert result['table_page_span']['status'] == 'manual'
    words = result['word_limit']['actual']
    assert words == sum(len(p['text'].split()) for s in snapshot['sections']
                        if s['id'] not in ('title', 'abstract', 'references') for p in s['paragraphs'])
    assert word.paragraphs[1].text == f'Word count: {words} | Figures: 1 | Tables: 1'
    assert not word.inline_shapes
    legend = next(p for p in word.paragraphs if p.text.startswith('Figure 1.'))
    assert legend.text == 'Figure 1. Published cardiac studies Overview of findings from the cited literature. (A) Cardiac atlases.'
    assert [(r.text, r.bold) for r in legend.runs if r.bold] == [('(A)', True)]
    blocks = list(word.element.body)
    bibliography = next(p for p in word.paragraphs if 'doi:' in p.text)
    assert blocks.index(legend._p) > blocks.index(bibliography._p)
    table, = word.tables
    assert [c.text for c in table.rows[1].cells] == ['Study A', 'Spatial transcriptomics']
    caption = table._tbl.getprevious()
    assert caption.tag == qn('w:p') and caption.text == 'Table 1. Evidence comparison'
    assert caption.getprevious().text == '' and table._tbl.getnext().text == ''


def test_frontiers_checks_missing_or_out_of_order_display_item_callouts_without_adding_any():
    snapshot = illustrated_review()
    group, = snapshot['results_groups']
    group['figures'] += [dict(group['figures'][0], id=f'illustration-{i}', number=i) for i in (2, 3)]
    intro = next(s for s in snapshot['sections'] if s['id'] == 'introduction')
    intro['paragraphs'][-1]['text'] = 'Figure 3 is considered before Figures 1 and 2.'
    target = submission_target()
    result = checks(snapshot, target)
    assert result['table_references']['status'] == 'mismatch'
    assert result['figure_references']['status'] == 'mismatch'
    intro['paragraphs'][-1]['text'] = 'Figures 1–3 and Table 1 summarize the published evidence.'
    result = checks(snapshot, target)
    assert result['figure_references']['status'] == result['table_references']['status'] == 'pass'
    intro['paragraphs'][-1]['text'] = 'As shown in Figures 1 and 2, 34 patients participated. Figure 3 and Table 1 provide the context.'
    assert checks(snapshot, target)['figure_references']['status'] == 'pass'
    assert 'figure_limit' not in result


def test_frontiers_detects_explicit_ranges_and_lists_with_singular_figure_callouts():
    snapshot = illustrated_review()
    intro = next(s for s in snapshot['sections'] if s['id'] == 'introduction')
    paragraph = intro['paragraphs'][-1]
    target = submission_target()
    for text in ('Fig. 1-3 and Table 1 show the evidence.', 'Figure 1 and 5; Table 1 summarizes.'):
        paragraph['text'] = text
        assert checks(snapshot, target)['figure_references']['status'] == 'mismatch'
        assert checks(snapshot, target)['table_references']['status'] == 'pass'
    for text in ('Figure 1 and Table 1 show the evidence.',
                 'As shown in Figure 1, 300 patients participated. Table 1 gives the context.',
                 'Figure 1 and 5-fold changes are described in Table 1.',
                 'Figure 1 and 1,000 cells are described in Table 1.',
                 'Figure 1 and Table 1 contrast with Supplementary Figure 5 and Supplementary Table 6.'):
        paragraph['text'] = text
        result = checks(snapshot, target)
        assert result['figure_references']['status'] == result['table_references']['status'] == 'pass'
    paragraph['text'] = 'Figure 1 and 5 clarify the evidence in Table 1.'
    assert checks(snapshot, target)['figure_references']['status'] == 'manual'


def test_frontiers_overview_caps_the_combined_main_illustrations_and_the_abstract():
    snapshot = illustrated_review()
    target = submission_target()
    group, = snapshot['results_groups']
    group['figures'] = [dict(group['figures'][0], id=f'figure-{i}', number=i) for i in range(1, 9)]
    group['tables'] = [dict(group['tables'][0], id=f'table-{i}', number=i) for i in range(1, 8)]
    abstract = next(s['paragraphs'][0] for s in snapshot['sections'] if s['id'] == 'abstract')
    abstract['text'] = 'words ' * 350
    actual = checks(snapshot, target)
    assert (actual['figure_table_limit']['status'], actual['figure_table_limit']['actual'],
            actual['figure_table_limit']['expected']) == ('pass', 15, 15)
    assert (actual['abstract_word_limit']['status'], actual['abstract_word_limit']['actual']) == ('pass', 350)
    assert actual['figure_table_limit']['evidence'][0]['source_id'] == 'overview'
    group['tables'].append(dict(group['tables'][0], id='table-8', number=8))
    abstract['text'] += 'extra'
    actual = checks(snapshot, target)
    assert (actual['figure_table_limit']['status'], actual['figure_table_limit']['actual']) == ('mismatch', 16)
    assert (actual['abstract_word_limit']['status'], actual['abstract_word_limit']['actual']) == ('mismatch', 351)
