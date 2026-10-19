"""Extract citation fields from saved EFetch bytes, without filling absent facts."""

import re

from defusedxml import ElementTree


def _text(node, path=None):
    if path is not None:
        node = node.find(path) if node is not None else None
    return ''.join(node.itertext()).strip() if node is not None else ''


def _empty(pmid):
    return dict(article_type='unsupported', authors=[], title='', journal_title='',
                journal_abbreviation='', year='', date='', volume='', issue='',
                pages='', article_number='', doi='', pmid=pmid)


def extract_metadata(raw: bytes, pmid: str) -> dict:
    """Select one exact PMID in an actual saved receipt; reject ambiguous identity."""
    if not isinstance(raw, bytes) or not isinstance(pmid, str) or not re.fullmatch(r'[1-9][0-9]*', pmid):
        raise ValueError('citation_metadata_source_invalid')
    try:
        root = ElementTree.fromstring(raw, forbid_dtd=False, forbid_entities=True, forbid_external=True)
    except Exception as exc:
        raise ValueError('citation_metadata_source_invalid') from exc
    if root.tag != 'PubmedArticleSet' or root.find('.//ERROR') is not None:
        raise ValueError('citation_metadata_source_invalid')
    matches = []
    for record in root:
        if record.tag not in ('PubmedArticle', 'PubmedBookArticle'):
            raise ValueError('citation_metadata_source_invalid')
        citation = record.find('MedlineCitation' if record.tag == 'PubmedArticle' else 'BookDocument')
        if citation is not None and any(_text(node) == pmid for node in citation.findall('PMID')):
            if len(citation.findall('PMID')) != 1:
                raise ValueError('citation_metadata_source_invalid')
            matches.append((record, citation))
    if len(matches) != 1:
        raise ValueError('citation_metadata_source_invalid')
    record, citation = matches[0]
    # ReferenceList IDs identify cited works, not this record (including nested book references).
    identity_paths = ('PubmedData/ArticleIdList/ArticleId',) if record.tag == 'PubmedArticle' else (
        'BookDocument/ArticleIdList/ArticleId', 'PubmedBookData/ArticleIdList/ArticleId')
    declared = [_text(node) for path in identity_paths for node in record.findall(path)
                if node.get('IdType') == 'pubmed']
    if any(value != pmid for value in declared):
        raise ValueError('citation_metadata_source_invalid')
    result = _empty(pmid)
    if record.tag != 'PubmedArticle':
        return result
    article = citation.find('Article')
    if article is None:
        raise ValueError('citation_metadata_source_invalid')
    result['article_type'] = 'journal'
    result['title'] = _text(article, 'ArticleTitle')
    result['journal_title'] = _text(article, 'Journal/Title')
    result['journal_abbreviation'] = _text(article, 'Journal/ISOAbbreviation') or _text(citation, 'MedlineJournalInfo/MedlineTA')
    for author in article.findall('AuthorList/Author'):
        result['authors'].append(dict(family=_text(author, 'LastName'), given=_text(author, 'ForeName'),
                                      initials=_text(author, 'Initials'), collective=_text(author, 'CollectiveName')))
    issue = article.find('Journal/JournalIssue')
    result['volume'] = _text(issue, 'Volume')
    result['issue'] = _text(issue, 'Issue')
    date = issue.find('PubDate') if issue is not None else None
    result['date'] = _text(date, 'MedlineDate') or ' '.join(filter(None, [_text(date, field) for field in ('Year', 'Month', 'Day', 'Season')]))
    year_match = re.match(r'^([12][0-9]{3})(?:\b|$)', _text(date, 'Year') or result['date'])
    result['year'] = year_match.group(1) if year_match else ''
    result['pages'] = _text(article, 'Pagination/MedlinePgn')
    locations = [node for node in article.findall('ELocationID') if node.get('ValidYN') != 'N']
    result['article_number'] = next((_text(node) for node in locations if node.get('EIdType') == 'pii' and _text(node)), '')
    dois = {_text(node) for node in record.findall('PubmedData/ArticleIdList/ArticleId') if node.get('IdType') == 'doi' and _text(node)}
    dois.update(_text(node) for node in locations if node.get('EIdType') == 'doi' and _text(node))
    if len(dois) > 1:
        raise ValueError('citation_metadata_source_invalid')
    result['doi'] = next(iter(dois), '')
    return result


def metadata_gaps(metadata: dict) -> list[str]:
    """Fields necessary for the first journal format; DOI and issue are optional."""
    if metadata.get('article_type') != 'journal':
        return ['article_type']
    authors = metadata.get('authors')
    gaps = []
    if not isinstance(authors, list) or not authors or any(
        not isinstance(author, dict) or not (
            _present(author.get('collective')) or (_present(author.get('family')) and _present(author.get('initials'))))
        for author in authors
    ):
        gaps.append('authors')
    gaps.extend(field for field in ('title', 'journal_abbreviation', 'year', 'volume') if not _present(metadata.get(field)))
    if not (_present(metadata.get('pages')) or _present(metadata.get('article_number'))):
        gaps.append('pages_or_article_number')
    return gaps


def _present(value):
    return isinstance(value, str) and bool(value.strip())
