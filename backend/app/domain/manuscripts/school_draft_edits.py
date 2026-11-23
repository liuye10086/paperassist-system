"""Editorial overlays for exporting an exact, already generated school draft."""
from copy import deepcopy
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.exceptions import StorageError
from app.domain.manuscripts.contracts import SchoolKeywords


Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class SentenceCitations(BaseModel):
    model_config = ConfigDict(extra='forbid')

    sentence: Title
    numbers: list[int] = Field(min_length=1, max_length=25)


class SchoolDraftEdits(BaseModel):
    model_config = ConfigDict(extra='forbid')

    english_title: Title | None = None
    keywords: list[SchoolKeywords] | None = Field(default=None, max_length=300)
    chapter_titles: dict[str, Title] = Field(default_factory=dict, max_length=300)
    figure_titles: dict[str, Title] = Field(default_factory=dict, max_length=300)
    citations: dict[str, list[SentenceCitations]] = Field(default_factory=dict, max_length=400)


def invalid(message):
    return StorageError('school_export_input_invalid', message, 422)


def export_parts(paragraph, anchors):
    original = paragraph['parts']
    if len(original) != 1:
        raise invalid('该段落已包含独立引文位置。')
    text = original[0]['text']
    allowed = {item['number']: item for item in original[0]['citations']}
    spans = []
    for anchor in anchors:
        start = text.find(anchor.sentence)
        end = start + len(anchor.sentence)
        if start < 0 or text.find(anchor.sentence, start + 1) >= 0:
            raise invalid('引文对应的原句必须在该段落中恰好出现一次。')
        if (not set(anchor.numbers) <= allowed.keys()
                or len(set(anchor.numbers)) != len(anchor.numbers)):
            raise invalid('引文只可使用该段落已关联的文献编号。')
        spans.append((start, end, [allowed[n] for n in sorted(anchor.numbers)]))
    parts = []
    cursor = 0
    for start, end, citations in sorted(spans, key=lambda span: span[0]):
        if start < cursor:
            raise invalid('同一段落的引文位置不能重叠。')
        parts.append(dict(text=text[cursor:end], citations=citations))
        cursor = end
    if cursor < len(text):
        parts.append(dict(text=text[cursor:], citations=[]))
    return parts


def apply_export_edits(snapshot, draft, options, edits):
    if edits is None:
        return draft, options
    draft = deepcopy(draft)
    options = deepcopy(options)
    chapters = {s['id']: s for s in draft['sections']}
    figures = {f['id'] for g in snapshot['results_groups'] for f in g['figures']}
    paragraphs = {p['id']: p for s in chapters.values() for p in s['paragraphs']}
    if (not edits.chapter_titles.keys() <= chapters.keys() or not edits.figure_titles.keys() <= figures
            or not edits.citations.keys() <= paragraphs.keys()):
        raise invalid('修改项必须对应当前初稿的章节、图件或段落。')
    for identity, anchors in edits.citations.items():
        paragraphs[identity]['parts'] = export_parts(paragraphs[identity], anchors)
    for identity, title in edits.chapter_titles.items():
        chapters[identity]['heading'] = title
    for chapter in chapters.values():
        chapter_figures = [f for g in chapter['groups'] for f in g['figures']]
        chapter_figures.extend(f for p in chapter['paragraphs'] for f in p.get('figures', ()))
        for figure in chapter_figures:
            if figure['id'] in edits.figure_titles:
                figure['title'] = edits.figure_titles[figure['id']]
    used = {cite['number'] for paragraph in paragraphs.values() for part in paragraph['parts']
            for cite in part['citations']}
    if edits.citations and used != {r['number'] for r in draft['references']}:
        raise invalid('调整引用位置后，正文与文末参考文献必须逐一对应。')
    if edits.english_title is not None:
        options['english_title'] = edits.english_title
        draft['english_title'] = edits.english_title
    if edits.keywords is not None:
        options['keywords'] = [item.model_dump(mode='json') for item in edits.keywords]
        for item in edits.keywords:
            if item.chapter_id not in chapters or chapters[item.chapter_id].get('purpose') != 'abstract':
                raise invalid('关键词必须对应当前初稿中的摘要。')
            chapters[item.chapter_id]['keywords'] = item.values
    return draft, options
