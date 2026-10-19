"""Deterministic nlm_numeric_journal_v1 rendering of already resolved bindings."""

import re

from .metadata import metadata_gaps


_MONTHS = {
    spelling: name[:3]
    for number, name in enumerate(('January', 'February', 'March', 'April', 'May', 'June',
                                    'July', 'August', 'September', 'October', 'November', 'December'), 1)
    for spelling in (str(number), f'{number:02}', name.lower(), name[:3].lower())
}


def _nlm_date(value):
    """Normalize only an explicit English/numeric month; retain other date text."""
    match = re.fullmatch(r'([12][0-9]{3}) ([A-Za-z]+|[0-9]{1,2})( [0-9]{1,2})?', value)
    if match:
        month = _MONTHS.get(match[2].lower())
        if month:
            return match[1] + ' ' + month + (match[3] or '')
    return value


def _sentence(text):
    return text if text.endswith(('.', '!', '?')) else text + '.'


def _first_present(*values):
    return next((value for value in values if isinstance(value, str) and value.strip()), '')


def format_reference(metadata: dict) -> str:
    gaps = metadata_gaps(metadata)
    if gaps:
        raise ValueError('citation_metadata_incomplete:' + ','.join(gaps))
    authors = []
    for author in metadata['authors'][:6]:
        authors.append(_first_present(author.get('collective')) or ' '.join(filter(None, [
            _first_present(author.get('family')), _first_present(author.get('initials'))])))
    if len(metadata['authors']) > 6:
        authors.append('et al.')
    author_text = _sentence(', '.join(authors))
    issue_value = _first_present(metadata.get('issue'))
    issue = f'({issue_value})' if issue_value else ''
    locator = _first_present(metadata.get('pages'), metadata.get('article_number'))
    date = _nlm_date(_first_present(metadata.get('date'), metadata.get('year')))
    text = f"{author_text} {_sentence(metadata['title'])} {_sentence(metadata['journal_abbreviation'])} {date};{metadata['volume']}{issue}:{locator}."
    doi = _first_present(metadata.get('doi'))
    if doi:
        text += f' doi:{doi}.'
    return text


def render_paragraphs(paragraphs: list[dict]) -> dict:
    """Number by first appearance, preserving paragraph IDs and exact text fragments."""
    numbers = {}
    selected_metadata = {}
    references = []
    output = []
    for paragraph in paragraphs:
        parts = []
        for fragment in paragraph['fragments']:
            if fragment['kind'] == 'text':
                parts.append(fragment['text'])
                continue
            if fragment['kind'] != 'claim' or not fragment.get('bindings'):
                raise ValueError('citation_fragment_invalid')
            cited = set()
            for binding in fragment['bindings']:
                ref_id = binding['project_reference_id']
                metadata = binding['metadata']
                if ref_id not in numbers:
                    numbers[ref_id] = len(numbers) + 1
                    selected_metadata[ref_id] = metadata
                    references.append(dict(number=numbers[ref_id], project_reference_id=ref_id, text=format_reference(metadata)))
                elif selected_metadata[ref_id] != metadata:
                    raise ValueError('citation_metadata_versions_conflict')
                cited.add(numbers[ref_id])
            parts.append(fragment['text'] + ' (' + ', '.join(str(number) for number in sorted(cited)) + ')')
        output.append(dict(id=paragraph['id'], text=''.join(parts)))
    return dict(paragraphs=output, text='\n\n'.join(paragraph['text'] for paragraph in output), references=references)
