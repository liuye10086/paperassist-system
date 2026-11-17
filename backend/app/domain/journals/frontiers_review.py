"""Finite format of a confirmed Frontiers in Cardiovascular Medicine Review."""

import re

from app.domain.literature_citations.formatter import format_frontiers_reference, render_paragraphs


JOURNAL = 'Frontiers in Cardiovascular Medicine'
ARTICLE_TYPES = 'https://www.frontiersin.org/journals/cardiovascular-medicine/for-authors/article-types'
ARTICLE_OVERVIEW = 'https://www.frontiersin.org/for-authors/where-to-publish/article-types'
AUTHOR_GUIDE = 'https://www.frontiersin.org/guidelines/author-guidelines'
STYLE_TABLE = 'https://www.frontiersin.org/Design/pdf/Frontiers_Journal_style_table.pdf'
REFERENCE_STYLE = 'Frontiers Vancouver (Numbered)'
WORD_FORMAT = 'frontiers_review_word_v1'
WORD_LIMIT = 12000
OVERVIEW_LIMITS = {
    'figure_table_limit': (15, 'Figures/Tables: 15 maximum'),
    'abstract_word_limit': (350, 'Maximum abstract length: 350 words'),
}
REVIEW_HEADINGS = ('Abstract', 'Introduction', 'Discussion')
HEADING_NAMES = {'introduction': 'Introduction', 'discussion': 'Discussion'}
HEADING_LEVELS = {'conclusion': 2}
LAYOUT_QUOTES = {
    'document_single_spacing': 'the entire document should be single-spaced',
    'document_page_line_numbers': 'must contain page and line numbers',
}
DISPLAY_FLAGS = {'document_single_spacing': 'single_spacing', 'document_page_line_numbers': 'page_line_numbers'}
SUBMISSION_LAYOUT = 'document_submission_layout'
SUBMISSION_RULES = {
    SUBMISSION_LAYOUT: ('main body of the text, footnotes, and all citations within it',
                        'number of words and the number of figures and tables',
                        'on the first page'),
    'figure_captions': ('figure captions should be placed at the end of the manuscript',),
    'table_captions': ('table captions must be placed immediately before the table',),
    'table_editable_at_end': ('tables should be inserted at the end of the manuscript in an editable format',),
    'figure_references': ('each figure is mentioned in the text and in numerical order',),
    'table_references': ('each table is mentioned in the text and in numerical order',),
    'figure_submission': ('figures to be submitted individually',),
    'dpi': ('300 dpi at final size',),
    'table_page_span': ('large tables covering several pages cannot be included in the final pdf',),
}
LAYOUT_RULES = (SUBMISSION_LAYOUT, 'figure_captions', 'table_captions', 'table_editable_at_end')
BODY_EXCLUSIONS = {'title', 'abstract', 'references'}
_CALLOUT_NUMBER = r'([0-9]+)(?:[A-Z]\b|\s*\([A-Z]\))?(?![\w%×]|\.\d|,\d{3}\b|[-–—][A-Za-z])'
_CALLOUT = re.compile(r'\b(?:(supplementary)\s+)?(figures?|figs?\.?|tables?)\s*' + _CALLOUT_NUMBER, re.I)
_NEXT_CALLOUT = re.compile(r'(\s*[-–—]\s*|\s*,\s*(?:and\s+)?|\s+and\s+)' + _CALLOUT_NUMBER, re.I)


def matches_submission_quote(key, quote):
    return all(fragment in quote.casefold() for fragment in SUBMISSION_RULES[key])


def confirmed_rule(target, rule):
    """Match the confirmed journal and the located, permitted publisher evidence."""
    if not target or target.get('article_type') != 'review' or target.get('synthetic') or not target.get('confirmed_by'):
        return False
    profile = target.get('candidate', {}).get('profile', {})
    if (profile.get('name'), profile.get('source_type'), profile.get('official_url')) != (JOURNAL, 'official_local', ARTICLE_TYPES):
        return False
    key = rule['key']
    quote = rule.get('quote', '')
    if rule.get('article_type') != 'review' or rule.get('status') != 'known':
        return False
    if key in ('required_sections', 'section_order'):
        # Earlier confirmed targets did not include the publisher's document rules.
        if not any(r['key'] in DISPLAY_FLAGS for r in target.get('selected_requirements', [])):
            return False
        if tuple(rule['value']) != REVIEW_HEADINGS or 'Subsections relevant for the subject' not in quote:
            return False
        url = ARTICLE_TYPES
    elif key in DISPLAY_FLAGS:
        if rule['value'] is not True or LAYOUT_QUOTES[key] not in quote.casefold():
            return False
        url = AUTHOR_GUIDE
    elif key == 'reference_style':
        if rule['value'] != REFERENCE_STYLE or JOURNAL not in quote or REFERENCE_STYLE not in quote:
            return False
        url = STYLE_TABLE
    elif key == 'word_limit':
        if rule['value'] != WORD_LIMIT or ('review articles are peer-reviewed and have a maximum word count of 12,000'
                                           not in quote.casefold()):
            return False
        url = ARTICLE_TYPES
    elif key in OVERVIEW_LIMITS:
        expected, phrase = OVERVIEW_LIMITS[key]
        if type(rule['value']) is not int or rule['value'] != expected or phrase not in quote:
            return False
        url = ARTICLE_OVERVIEW
    elif key in SUBMISSION_RULES:
        expected = 300 if key == 'dpi' else True
        if type(rule['value']) is not type(expected) or rule['value'] != expected or not matches_submission_quote(key, quote):
            return False
        url = AUTHOR_GUIDE
    else:
        return False
    return any(
        guide.get('id') == rule.get('source_id') and guide.get('source_version') == rule.get('source_version')
        and guide.get('source_url') == guide.get('official_url') == url and guide.get('source_type') == 'official_local'
        and guide.get('permission_status') == 'allowed' and guide.get('source_status') == 'available'
        and quote in guide.get('source_text', '')
        and (url != ARTICLE_OVERVIEW or 'Review' in guide['source_text'].splitlines())
        and (key != 'figure_table_limit' or 'Figures and/or tables (combined)' in guide['source_text'])
        for guide in (target.get('guide', {}), *target.get('additional_guides', []))
    )


def submission_evidence(target, keys, warnings):
    selected = {rule['key']: rule for rule in (target or {}).get('selected_requirements', [])}
    evidence = [selected.get(key) for key in keys]
    if all(rule and confirmed_rule(target, rule) and not any(
        warning.get('blocks_rules', True) and warning.get('source_id') in (None, rule['source_id'])
        for warning in warnings
    ) for rule in evidence):
        return evidence
    return []


def submission_content(snapshot, excluded_chapter_ids=frozenset()):
    """Project the frozen English body text and the main manuscript illustrations."""
    paragraphs = [item['text'] for section in snapshot['sections']
                  if section['id'] not in BODY_EXCLUSIONS and section['id'] not in excluded_chapter_ids
                  for item in section['paragraphs']]
    words = sum(len(text.split()) for text in paragraphs)
    groups = snapshot.get('results_groups', [])
    figures = [item for group in groups for item in group.get('figures', [])]
    tables = [item for group in groups for item in group.get('tables', [])]
    return dict(body=paragraphs, words=words, figures=figures, tables=tables)


def sequential_numbering(records):
    numbers = [record.get('number') for record in records]
    return all(type(number) is int for number in numbers) and sorted(numbers) == list(range(1, len(records) + 1))


def _number(text):
    return int(text) if len(text) <= 9 else 0


def first_callouts(paragraphs, kind, record_count):
    """Read first appearances of explicit numbered callouts, including lists and ranges."""
    mentions = {}
    ambiguous = False
    for text in paragraphs:
        for match in _CALLOUT.finditer(text):
            supplementary, label, raw = match.groups()
            label = label.casefold().rstrip('.')
            if supplementary or label.startswith('tab') != (kind == 'table'):
                continue
            previous = _number(raw)
            mentions[previous] = None
            end = match.end()
            joined = False
            plural = label.endswith('s')
            while following := _NEXT_CALLOUT.match(text, end):
                separator, raw = following.groups()
                is_range = separator.strip() in ('-', '–', '—')
                if joined and not is_range:
                    break
                has_conjunction = 'and' in separator.casefold()
                if not plural and not is_range and text[following.end():].lstrip()[:1].isalpha():
                    # A bare number before a word can begin a new clause after a singular callout.
                    ambiguous = ambiguous or has_conjunction
                    break
                number = _number(raw)
                if is_range and 1 <= previous < number <= record_count:
                    mentions.update(dict.fromkeys(range(previous + 1, number)))
                mentions[number] = None
                joined = joined or has_conjunction
                previous, end = number, following.end()
    return list(mentions), ambiguous


def caption_text(record, label, field='title'):
    """Strip an existing matching label before projecting the publisher punctuation."""
    text = (record.get(field) or '').strip()
    return re.sub(rf'^{label}\s+{record.get("number")}(?:\s*[.:–—]\s*|\s+|$)', '', text,
                  count=1, flags=re.I)


def editable_table(table):
    return bool(table.get('columns')) and 'rows' in table and all(
        len(row) == len(table['columns']) for row in table['rows'])


def submission_requirement(key, content, projected):
    figures, tables = content['figures'], content['tables']
    if key == SUBMISSION_LAYOUT:
        counts = dict(words=content['words'], figures=len(figures), tables=len(tables)) if projected else None
        return counts, 'pass' if projected else 'mismatch', '首页统计与 Word 导出使用同一份固定正文与图表。', 'first_page'
    if key in ('figure_submission', 'dpi'):
        reason = ('请按正文顺序单独提交图件，核对 TIFF、JPEG 或录用阶段的 EPS、终稿宽度 85 或 180 mm、'
                  'RGB、300 DPI、轴标单位及使用许可。' if figures else '当前稿件没有图件，未核验独立图件及其文件要求。')
        actual = None if key == 'dpi' else len(figures)
        return actual, 'manual', reason, 'figure_files'
    if key == 'table_page_span':
        if tables:
            return len(tables), 'manual', '按实际分页核对跨多页的大表，期刊要求此类表格作为补充材料。', 'table_pages'
        return 0, 'pass', '当前稿件没有表格，跨多页表格要求不适用。', 'table_pages'
    if key in ('figure_references', 'table_references'):
        kind = key.split('_', 1)[0]
        records = figures if kind == 'figure' else tables
        mentions, ambiguous = first_callouts(content['body'], kind, len(records))
        matches = sequential_numbering(records) and mentions == list(range(1, len(records) + 1))
        if matches and ambiguous:
            return mentions, 'manual', '单数图表引文后的裸数字可能属于正文，请核对是否还有图表编号。', 'body'
        reason = '按正文首次出现顺序核对主稿图表，编号须从 1 连续排列。补充图表另行核对。'
        return mentions, 'pass' if matches else 'mismatch', reason, 'body'
    if key == 'figure_captions':
        missing = [item['id'] for item in figures if not caption_text(item, 'Figure', 'caption')
                   or item.get('caption_status') in (None, 'missing', 'candidate')]
        matches = not missing and (not figures or projected)
        return dict(count=len(figures), missing=missing), 'pass' if matches else 'mismatch', (
            '已保存的图注随投稿版式放在稿末，并带图号。' if figures else '当前稿件没有图，稿末图注要求不适用。'), 'figure_captions'
    if key == 'table_captions':
        missing = [item['id'] for item in tables if not caption_text(item, 'Table')]
        matches = not missing and (not tables or projected)
        return dict(count=len(tables), missing=missing), 'pass' if matches else 'mismatch', (
            '投稿版式将带表号的单段表题紧接在对应表格上方。' if tables else '当前稿件没有表，表题要求不适用。'), 'table_captions'
    matches = not tables or projected and all(editable_table(table) for table in tables)
    return len(tables), 'pass' if matches else 'mismatch', (
        '投稿版式将可编辑 Word 表格统一放在稿末。' if tables else '当前稿件没有表，稿末可编辑表要求不适用。'), 'tables'


def reference_texts(snapshot):
    """Render only the verified, already numbered journal-article bindings."""
    citation = snapshot.get('citation_snapshot') or {}
    paragraphs = citation.get('paragraphs', [])
    references = snapshot['references']
    if not references or render_paragraphs(paragraphs) != citation.get('output') or references != citation['output']['references']:
        raise ValueError('Frontiers reference display requires the exact frozen citation output')
    metadata = {binding['project_reference_id']: binding['metadata'] for p in paragraphs for f in p['fragments']
                if f['kind'] == 'claim' for binding in f['bindings']}
    return [format_frontiers_reference(metadata[r['project_reference_id']]) for r in references]
