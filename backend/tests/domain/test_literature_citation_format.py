"""Synthetic saved EFetch fixtures; no NCBI or model requests."""

from copy import deepcopy

import pytest


def _metadata(**changes):
    result = dict(article_type='journal', authors=[dict(family='Smith', given='Jane', initials='J', collective='')],
                  title='Original title', journal_title='Full Journal', journal_abbreviation='Full J',
                  year='2024', date='2024 May 12', volume='12', issue='3', pages='101-109',
                  article_number='', doi='10.1234/example', pmid='123')
    result.update(changes)
    return result


def _xml(article_extra='', journal_extra='', authors=None, pmid='123'):
    author_xml = authors if authors is not None else '<Author><LastName>Smith</LastName><ForeName>Jane</ForeName><Initials>J</Initials></Author>'
    return f'''<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>{pmid}</PMID>
    <Article><Journal><JournalIssue><Volume>12</Volume><Issue>3</Issue><PubDate><Year>2024</Year><Month>May</Month><Day>12</Day></PubDate></JournalIssue>
    <Title>Full Journal</Title><ISOAbbreviation>Full J</ISOAbbreviation>{journal_extra}</Journal>
    <ArticleTitle>Original <i>title</i></ArticleTitle><AuthorList>{author_xml}</AuthorList>
    {article_extra}</Article></MedlineCitation><PubmedData><ArticleIdList>
    <ArticleId IdType="pubmed">{pmid}</ArticleId><ArticleId IdType="doi">10.1234/example</ArticleId>
    </ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>'''.encode()


def test_extract_saved_efetch_preserves_structured_names_and_fields():
    from app.domain.literature_citations.metadata import extract_metadata

    raw = _xml('<Pagination><MedlinePgn>101-109</MedlinePgn></Pagination>')
    assert extract_metadata(raw, '123') == _metadata()


def test_extract_collective_article_number_and_medline_date_without_inventing_initials():
    from app.domain.literature_citations.metadata import extract_metadata, metadata_gaps

    raw = _xml('<ELocationID EIdType="pii" ValidYN="Y">e12345</ELocationID>', authors='''
    <Author><CollectiveName>Study Team &amp; Partners</CollectiveName></Author>
    <Author><LastName>Li</LastName><ForeName>Ming</ForeName></Author>''')
    raw = raw.replace(b'<Year>2024</Year><Month>May</Month><Day>12</Day>', b'<MedlineDate>2023 Winter</MedlineDate>')
    actual = extract_metadata(raw, '123')
    assert actual['authors'] == [dict(family='', given='', initials='', collective='Study Team & Partners'),
                                  dict(family='Li', given='Ming', initials='', collective='')]
    assert (actual['year'], actual['date'], actual['pages'], actual['article_number']) == ('2023', '2023 Winter', '', 'e12345')
    assert metadata_gaps(actual) == ['authors']


def test_extract_only_requested_record_and_reports_unsupported_book():
    from app.domain.literature_citations.metadata import extract_metadata, metadata_gaps

    raw = b'<PubmedArticleSet><PubmedBookArticle><BookDocument><PMID>456</PMID><ArticleTitle>Book title</ArticleTitle></BookDocument></PubmedBookArticle></PubmedArticleSet>'
    actual = extract_metadata(raw, '456')
    assert actual['article_type'] == 'unsupported'
    assert metadata_gaps(actual) == ['article_type']
    with pytest.raises(ValueError):
        extract_metadata(raw, '123')


@pytest.mark.parametrize('raw', [b'<invalid', b'<!DOCTYPE x [<!ENTITY x "forbidden">]><PubmedArticleSet>&x;</PubmedArticleSet>'])
def test_extract_rejects_invalid_or_entity_xml(raw):
    from app.domain.literature_citations.metadata import extract_metadata

    with pytest.raises(ValueError):
        extract_metadata(raw, '123')


def test_extract_rejects_duplicate_or_conflicting_identity():
    from app.domain.literature_citations.metadata import extract_metadata

    raw = _xml()
    duplicate = raw.replace(b'</PubmedArticleSet>', raw.split(b'<PubmedArticleSet>')[1])
    with pytest.raises(ValueError):
        extract_metadata(duplicate, '123')
    with pytest.raises(ValueError):
        extract_metadata(raw.replace(b'IdType="pubmed">123', b'IdType="pubmed">999'), '123')


def test_extract_journal_identity_ignores_cited_article_ids_in_nested_reference_lists():
    from app.domain.literature_citations.metadata import extract_metadata

    # Minimal version of EFetch PubmedData/ReferenceList; cited IDs identify other papers.
    references = b'''<ReferenceList><Reference><Citation>Synthetic cited work</Citation><ArticleIdList>
        <ArticleId IdType="pubmed">999</ArticleId><ArticleId IdType="doi">10.1234/cited</ArticleId>
        </ArticleIdList></Reference><ReferenceList><Reference><ArticleIdList>
        <ArticleId IdType="pubmed">888</ArticleId></ArticleIdList></Reference></ReferenceList></ReferenceList>'''
    raw = _xml('<Pagination><MedlinePgn>101-109</MedlinePgn></Pagination>')
    raw = raw.replace(b'</PubmedData>', references + b'</PubmedData>')
    assert extract_metadata(raw, '123') == _metadata()


def test_extract_book_identity_ignores_citations_in_both_own_containers():
    from app.domain.literature_citations.metadata import extract_metadata

    own = b'<ArticleIdList><ArticleId IdType="pubmed">456</ArticleId></ArticleIdList>'
    reference = b'<ReferenceList><Reference><ArticleIdList><ArticleId IdType="pubmed">999</ArticleId></ArticleIdList></Reference></ReferenceList>'
    raw = (b'<PubmedArticleSet><PubmedBookArticle><BookDocument><PMID>456</PMID>'
           + own + reference + b'</BookDocument><PubmedBookData>' + own + reference
           + b'</PubmedBookData></PubmedBookArticle></PubmedArticleSet>')
    actual = extract_metadata(raw, '456')
    assert actual['article_type'] == 'unsupported'
    assert actual['pmid'] == '456'


@pytest.mark.parametrize('container', ['PubmedData', 'BookDocument', 'PubmedBookData'])
def test_extract_rejects_conflicting_identity_in_every_own_id_container(container):
    from app.domain.literature_citations.metadata import extract_metadata

    conflicting = b'<ArticleIdList><ArticleId IdType="pubmed">999</ArticleId></ArticleIdList>'
    if container == 'PubmedData':
        raw = _xml().replace(b'</PubmedData>', conflicting + b'</PubmedData>')
    else:
        raw = (b'<PubmedArticleSet><PubmedBookArticle><BookDocument><PMID>456</PMID>'
               b'<ArticleIdList><ArticleId IdType="pubmed">456</ArticleId></ArticleIdList>'
               b'</BookDocument><PubmedBookData><ArticleIdList><ArticleId IdType="pubmed">456</ArticleId>'
               b'</ArticleIdList></PubmedBookData></PubmedBookArticle></PubmedArticleSet>')
        closing = f'</{container}>'.encode()
        raw = raw.replace(closing, conflicting + closing)
    with pytest.raises(ValueError, match='citation_metadata_source_invalid'):
        extract_metadata(raw, '123' if container == 'PubmedData' else '456')


def test_gaps_require_actual_abbreviation_authors_and_locator_but_not_doi():
    from app.domain.literature_citations.metadata import metadata_gaps

    assert metadata_gaps(_metadata(doi='', pages='', article_number='e123')) == []
    assert metadata_gaps(_metadata(authors=[], title='', journal_abbreviation='', year='', volume='', pages='')) == [
        'authors', 'title', 'journal_abbreviation', 'year', 'volume', 'pages_or_article_number']
    assert metadata_gaps(_metadata(authors=[dict(family='', given='', initials='', collective='')])) == ['authors']


def test_format_six_authors_and_seven_author_cutoff():
    from app.domain.literature_citations.formatter import format_reference

    authors = [dict(family=f'Author{i}', given='Jane', initials='J', collective='') for i in range(1, 8)]
    expected = ', '.join(f'Author{i} J' for i in range(1, 7))
    assert format_reference(_metadata(authors=authors[:6])) == expected + '. Original title. Full J. 2024 May 12;12(3):101-109. doi:10.1234/example.'
    assert format_reference(_metadata(authors=authors)) == expected + ', et al. Original title. Full J. 2024 May 12;12(3):101-109. doi:10.1234/example.'


def test_format_collective_author_article_number_without_doi_or_issue():
    from app.domain.literature_citations.formatter import format_reference

    assert format_reference(_metadata(authors=[dict(family='', given='', initials='', collective='Study Team')],
                                     issue='', pages='', article_number='e123', doi='')) == 'Study Team. Original title. Full J. 2024 May 12;12:e123.'
    with pytest.raises(ValueError):
        format_reference(_metadata(journal_abbreviation=''))


def test_format_ignores_blank_fallback_fields_without_mutating_metadata():
    from app.domain.literature_citations.formatter import format_reference
    from app.domain.literature_citations.metadata import metadata_gaps

    metadata = _metadata(authors=[dict(family='Smith', given='Jane', initials='J', collective=' ')],
                         pages=' ', article_number='e123', doi='')
    before = deepcopy(metadata)
    assert metadata_gaps(metadata) == []
    assert format_reference(metadata) == 'Smith J. Original title. Full J. 2024 May 12;12(3):e123.'
    assert metadata == before


@pytest.mark.parametrize('optional,expected', [
    (dict(issue=' '), 'Smith J. Original title. Full J. 2024 May 12;12:101-109. doi:10.1234/example.'),
    (dict(doi=' '), 'Smith J. Original title. Full J. 2024 May 12;12(3):101-109.'),
])
def test_format_omits_blank_optional_fields_without_mutating_metadata(optional, expected):
    from app.domain.literature_citations.formatter import format_reference

    metadata = _metadata(**optional)
    before = deepcopy(metadata)
    assert format_reference(metadata) == expected
    assert metadata == before


@pytest.mark.parametrize('date,year,expected_date', [
    ('2024 May 12', '2024', '2024 May 12'),
    ('2023 Winter', '2023', '2023 Winter'),
    ('', '2024', '2024'),
    (' ', '2024', '2024'),
])
def test_format_preserves_actual_date_and_only_falls_back_when_missing(date, year, expected_date):
    from app.domain.literature_citations.formatter import format_reference

    metadata = _metadata(date=date, year=year, doi='')
    before = deepcopy(metadata)
    assert format_reference(metadata) == f'Smith J. Original title. Full J. {expected_date};12(3):101-109.'
    assert metadata == before


@pytest.mark.parametrize('date,expected_date', [
    ('2024 01 12', '2024 Jan 12'),
    ('2024 1 12', '2024 Jan 12'),
    ('2024 January 12', '2024 Jan 12'),
    ('2024 December', '2024 Dec'),
    ('2024 12', '2024 Dec'),
    ('2024 Feb 3', '2024 Feb 3'),
    ('2024', '2024'),
    ('2023 Winter', '2023 Winter'),
    ('2024 Jan-Feb', '2024 Jan-Feb'),
])
def test_format_normalizes_only_explicit_month_without_changing_source_metadata(date, expected_date):
    from app.domain.literature_citations.formatter import format_reference

    metadata = _metadata(date=date, doi='')
    before = deepcopy(metadata)
    assert format_reference(metadata) == f'Smith J. Original title. Full J. {expected_date};12(3):101-109.'
    assert metadata == before


@pytest.mark.parametrize('family,initials', [('Smith', ''), ('Smith', ' '), ('', 'J')])
def test_personal_author_requires_actual_family_and_initials(family, initials):
    from app.domain.literature_citations.formatter import format_reference
    from app.domain.literature_citations.metadata import metadata_gaps

    metadata = _metadata(authors=[dict(family=family, given='Jane', initials=initials, collective=' ')])
    before = deepcopy(metadata)
    assert metadata_gaps(metadata) == ['authors']
    with pytest.raises(ValueError, match='citation_metadata_incomplete:authors'):
        format_reference(metadata)
    assert metadata == before


def _claim(text, *ids):
    return dict(kind='claim', text=text, bindings=[dict(project_reference_id=ref, metadata=_metadata(title=f'Title {ref}')) for ref in ids])


def test_render_reuses_numbers_sorts_multicitation_and_keeps_input_immutable():
    from app.domain.literature_citations.formatter import render_paragraphs

    paragraphs = [dict(id='first', fragments=[dict(kind='text', text='Intro. '), _claim('First.', 'b'), _claim('Next.', 'a')]),
                  dict(id='second', fragments=[_claim('Together.', 'a', 'b', 'a', 'c')])]
    before = deepcopy(paragraphs)
    result = render_paragraphs(paragraphs)
    assert result['paragraphs'] == [dict(id='first', text='Intro. First. (1)Next. (2)'), dict(id='second', text='Together. (1, 2, 3)')]
    assert result['text'] == 'Intro. First. (1)Next. (2)\n\nTogether. (1, 2, 3)'
    assert [(r['number'], r['project_reference_id']) for r in result['references']] == [(1, 'b'), (2, 'a'), (3, 'c')]
    assert result['references'][0]['text'].startswith('Smith J. Title b.')
    assert paragraphs == before


def test_reorder_and_delete_only_change_new_render():
    from app.domain.literature_citations.formatter import render_paragraphs

    first = dict(id='first', fragments=[_claim('A.', 'a')])
    second = dict(id='second', fragments=[_claim('B.', 'b')])
    original = render_paragraphs([first, second])
    snapshot = deepcopy(original)
    assert render_paragraphs([second, first])['references'][0]['project_reference_id'] == 'b'
    assert len(render_paragraphs([first])['references']) == 1
    assert original == snapshot


def test_render_rejects_mixed_metadata_versions_for_same_reference():
    from app.domain.literature_citations.formatter import render_paragraphs

    first, second = _claim('A.', 'a'), _claim('B.', 'a')
    second['bindings'][0]['metadata']['year'] = '2025'
    with pytest.raises(ValueError):
        render_paragraphs([dict(id='p', fragments=[first, second])])
