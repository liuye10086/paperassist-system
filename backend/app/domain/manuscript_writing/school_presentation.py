"""Versioned presentation suggestions for the simplified thesis draft."""
import re
from typing import Annotated

from pydantic import Field, StringConstraints

from .contracts import Strict
from .live_contracts import LiveParagraph

PRESENTATION_VERSION = 'school-presentation-v1'
INSTRUCTIONS = (
    'Also return the presentation of the draft. Translate source_title faithfully into English '
    'or copy it if already English. Return keywords in each listed abstract language and concise '
    'content-specific headings only for the listed chapter and figure aliases. Do not supply chapter '
    'or figure numbers in those headings. Use existing evidence aliases only. For each literature '
    'claim, copy the exact full sentence, including its final punctuation, into citation_anchors '
    'with only the evidence aliases that support that sentence. A citation anchor must be a single '
    'sentence that occurs once in its paragraph. The union of the anchor aliases must equal the '
    'paragraph evidence_aliases. Never add citations to descriptions of this study or to unsupported claims.'
)
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=220)]
Keyword = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
PLACEHOLDER = re.compile(r'^(?P<number>\s*\d+(?:\.\d+)*\.?\s*)?(?:某某(?:法)?|待拟标题)$')
PLACEHOLDER_FIGURES = {'论文配图', 'Thesis illustration'}
HAN = re.compile(r'[\u3400-\u9fff]')


class CitationAnchor(Strict):
    sentence: str = Field(min_length=1, max_length=10000)
    evidence_aliases: list[str] = Field(min_length=1, max_length=100)


class PresentationParagraph(LiveParagraph):
    citation_anchors: list[CitationAnchor] = Field(max_length=100)


class PresentationSection(Strict):
    id: str = Field(pattern=r'^chapter[1-9][0-9]*$')
    paragraphs: list[PresentationParagraph] = Field(min_length=1, max_length=200)


class AliasTitle(Strict):
    id: str
    title: ShortText


class AliasKeywords(Strict):
    id: str
    values: list[Keyword] = Field(min_length=1, max_length=12)


class Presentation(Strict):
    english_title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    keywords: list[AliasKeywords] = Field(max_length=300)
    chapter_titles: list[AliasTitle] = Field(max_length=300)
    figure_titles: list[AliasTitle] = Field(max_length=300)


class SchoolPresentationOutput(Strict):
    sections: list[PresentationSection] = Field(min_length=1, max_length=300)
    presentation: Presentation


def add_presentation_input(base, payload, local):
    from .bundle import safe_text

    school = local['school']
    writable = {a: school['chapters'][a] for a in school['writable_aliases']}
    abstracts = {a: c['output_language'] for a, c in writable.items() if c['purpose'] == 'abstract'}
    headings = [a for a, c in writable.items() if PLACEHOLDER.fullmatch(c['title'])]
    figures = {f['number']: f for g in base['results_groups'] for f in g['figures']
               if f['title'] in PLACEHOLDER_FIGURES}
    local['presentation_figures'] = {f'figure{number}': figures[number]['id'] for number in sorted(figures)}
    payload['draft_presentation'] = dict(
        source_title=safe_text(base['title']),
        abstracts=[dict(id=a, output_language=language) for a, language in abstracts.items()],
        chapter_titles=headings,
        figure_titles=[dict(id=a, number=number) for a, number in
                       zip(local['presentation_figures'], sorted(figures), strict=True)],
    )


def presentation_schema(numeric):
    schema = SchoolPresentationOutput.model_json_schema()
    defs = schema['$defs']
    defs['StudyNumericBinding'] = numeric['$defs']['StudyNumericBinding']
    numerical = numeric['$defs']['LiveParagraph']['properties']
    for key in ('study_numeric_bindings', 'source_aliases', 'evidence_aliases'):
        defs['PresentationParagraph']['properties'][key] = numerical[key]
    evidence = numerical['evidence_aliases']
    if evidence.get('maxItems') == 0:
        defs['PresentationParagraph']['properties']['citation_anchors']['maxItems'] = 0
    else:
        defs['CitationAnchor']['properties']['evidence_aliases']['items'] = evidence['items']
    return schema


def validate_anchors(paragraph):
    text = paragraph['text']
    anchors = paragraph['citation_anchors']
    last_end = 0
    selected = set()
    for anchor in anchors:
        sentence = anchor['sentence']
        aliases = anchor['evidence_aliases']
        start = text.find(sentence)
        end = start + len(sentence)
        prefix = text[:start].rstrip()
        if (start < last_end or text.find(sentence, start + 1) >= 0 or sentence != sentence.strip()
                or not re.search(r'[。！？.!?][”’」』")]*$', sentence)
                or prefix and prefix[-1] not in '。！？.!?；;”’」』"'
                or re.search(r'[。！？]|[.!?]\s+(?=[A-Z])', sentence[:-1].rstrip('”’」』")'))
                or len(set(aliases)) != len(aliases)):
            raise ValueError('Citation anchor must be an exact, distinct sentence in paragraph order')
        last_end = end
        selected.update(aliases)
    if selected != set(paragraph['evidence_aliases']):
        raise ValueError('Citation anchors must cover the exact paragraph evidence')


def _by_alias(rows, expected, key):
    result = {item['id']: item[key] for item in rows}
    if len(result) != len(rows) or set(result) != set(expected):
        raise ValueError('Draft presentation aliases differ from the selected template or material')
    return result


def project_presentation(presentation, payload, local):
    requested = payload['draft_presentation']
    chapters = local['school']['chapters']
    keywords = _by_alias(presentation['keywords'], (r['id'] for r in requested['abstracts']), 'values')
    titles = _by_alias(presentation['chapter_titles'], requested['chapter_titles'], 'title')
    figures = _by_alias(presentation['figure_titles'], local['presentation_figures'], 'title')
    english_title = presentation['english_title']
    if (not re.search(r'[A-Za-z]', english_title) or HAN.search(english_title)
            or any(HAN.search(word) for a, words in keywords.items()
                   if chapters[a]['output_language'] == 'en' for word in words)):
        raise ValueError('English title and keywords must be written in English')
    if (any(re.match(r'^\s*\d+(?:\.\d+)*[.、\s]', value) or PLACEHOLDER.fullmatch(value) for value in titles.values())
            or any(value in PLACEHOLDER_FIGURES for value in figures.values())):
        raise ValueError('Draft presentation requires descriptive, unnumbered titles')
    return dict(
        english_title=english_title,
        keywords=[dict(chapter_id=chapters[a]['chapter_id'], values=words) for a, words in keywords.items()],
        chapter_titles={chapters[a]['chapter_id']: ((PLACEHOLDER.fullmatch(chapters[a]['title'])['number'] or '').strip()
                                                  + ' ' + title).strip() for a, title in titles.items()},
        figure_titles={local['presentation_figures'][a]: title for a, title in figures.items()},
    )
