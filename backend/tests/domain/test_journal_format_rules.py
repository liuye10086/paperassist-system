"""Finite extraction and read-only checks never turn missing evidence into pass."""
import pytest

def test_extract_is_finite_keeps_unknown_count_and_does_not_guess_semantics():
    from app.domain.journals.guide_rules import extract_requirements
    rules=extract_requirements('Maximum body words: 20\nPlease write concisely\nReference style: APA\nMinimum DPI: 300')
    assert len(rules)==3
    assert rules[0]['count_method'] is None
    assert rules[1]['status']=='unsupported'
    assert rules[2]['key']=='dpi'


def test_specific_rule_wins_but_cross_source_conflict_is_not_auto_passed():
    from app.domain.journals.guide_rules import select_requirements
    rules=[dict(id='general',key='word_limit',value=3000,status='known',quote='3000',location='p1',article_type=None,origin='journal'),dict(id='specific',key='word_limit',value=2000,status='known',quote='2000',location='p2',article_type='research',origin='journal'),dict(id='unit',key='word_limit',value=1500,status='known',quote='1500',location='p3',article_type=None,origin='unit')]
    selected,conflicts,decisions=select_requirements(rules,'research',[])
    assert conflicts[0]['key']=='word_limit'
    assert selected==[]
    assert decisions[0]['selected_id']=='specific'
    assert set(decisions[0]['preserved_ids'])=={'general','specific'}
    chosen,conflicts,_=select_requirements(rules,'research',[dict(key='word_limit',requirement_id='unit',reason='unit restriction')])
    assert chosen[0]['id']=='unit' and not conflicts


def test_counts_and_five_categories_with_missing_rules_and_abstract():
    from app.domain.journals.format_rules import check_format,count_text
    assert count_text('研究结果 alpha beta', 'zh-CN')==dict(hanzi=4,latin_words=2,whitespace_words=3)
    snap=dict(title='Research',output_language='en',methods=[],results_groups=[],sources=[],references=[],issues=[])
    result=check_format(snap,[],[],public_issues=[])
    assert {i['category'] for i in result['items']}=={'length','sections','abstract','illustrations','references'}
    assert not any(i['status']=='pass' for i in result['items'])
    rules=[dict(id='length',key='word_limit',status='known',value=20,count_method=None,quote='20',location='p1'),dict(id='abstract',key='abstract_required',status='known',value=True,quote='required',location='p1')]
    result=check_format(snap,rules,[],public_issues=[dict(id='numeric:p1',category='numeric',severity='error',location='p1',actual='99',expected='4',message='public mismatch')])
    assert next(i for i in result['items'] if i['key']=='word_limit')['status']=='pending_verification'
    assert next(i for i in result['items'] if i['key']=='abstract_required')['status']=='mismatch'
    assert result['summary']['all_passed'] is False
    assert any(i['key']=='public_consistency' and i['status']=='mismatch' for i in result['items'])


def test_five_category_observations_on_supported_structure_and_unsupported_styles():
    from app.domain.journals.format_rules import check_format
    from app.domain.journals.guide_rules import extract_requirements
    snap=dict(title='Synthetic',output_language='en',sections=[dict(id='abstract',title='Abstract',paragraphs=[dict(id='a',text='Background: Study\nMethods: Test')]),dict(id='introduction',title='Introduction',paragraphs=[dict(id='i',text='Sample body')])],results_groups=[dict(figures=[dict(id='f',number=1,caption='',caption_status='missing')],tables=[])],references=[],sources=[])
    rules=extract_requirements('Maximum body words: 20; count: en_whitespace_body\nRequired sections: Introduction\nSection order: Abstract | Introduction\nAbstract required: yes\nAbstract headings: Background | Methods\nMaximum abstract words: 20; count: en_whitespace_abstract\nMaximum figures: 1\nFigure captions: required\nFigure references: required\nReference style: APA')
    result=check_format(snap,rules,[],public_issues=[])
    states={i['key']:i['status'] for i in result['items']}
    assert states['word_limit']==states['required_sections']==states['abstract_required']==states['abstract_headings']=='pass'
    assert states['figure_captions']==states['figure_references']=='mismatch'
    assert states['reference_style']=='unsupported'
    assert result['summary']['all_passed'] is False


@pytest.mark.parametrize('language,headings',[
    ('en',['Results','Materials and methods']),
    ('zh-CN',['结果','材料与方法']),
])
def test_legacy_section_order_matches_public_display_not_method_storage_order(language,headings):
    from app.domain.journals.format_rules import check_format
    rule=dict(id='order',key='section_order',status='known',value=headings,quote=' | '.join(headings),location='line:1')
    snapshot=dict(title='synthetic',output_language=language,methods=[],results_groups=[],sources=[],references=[],issues=[])
    item=next(i for i in check_format(snapshot,[rule],[],public_issues=[])['items'] if i['key']=='section_order')
    assert item['actual']==headings
    assert item['status']=='pass'


@pytest.mark.parametrize('language,headings',[
    ('en',['Abstract','Introduction','Results','Discussion','Materials and methods','References']),
    ('zh-CN',['摘要','引言','结果','讨论','材料与方法','参考文献']),
])
def test_canonical_writing_sections_without_title_fields_use_public_heading_labels(language,headings):
    from app.domain.journals.format_rules import check_format
    from app.domain.manuscript_writing.contracts import SECTION_IDS
    snapshot=dict(title='synthetic',output_language=language,sections=[dict(id=key,paragraphs=[]) for key in SECTION_IDS],methods=[],results_groups=[],sources=[],references=[],issues=[])
    rules=[dict(id=key,key=key,status='known',value=headings,quote=' | '.join(headings),location='line:1') for key in ('required_sections','section_order')]
    items=[i for i in check_format(snapshot,rules,[],public_issues=[])['items'] if i['category']=='sections']
    assert all(i['actual']==headings and i['status']=='pass' for i in items)
