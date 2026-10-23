"""Finite source projection into the existing public facts and revision checker."""
from copy import deepcopy
import re

from app.domain.manuscript_review.checks import issue
from app.domain.manuscript_review.facts import displayed_paragraphs
from app.domain.manuscript_writing.context import normalize_sections, NUMBER
from app.domain.manuscripts.draft import flat_values
from .grounded import locations_for
from .planning import invalid


def references(value, identities):
    if isinstance(value, str):
        return value in identities
    if isinstance(value, dict):
        return any(references(v, identities) for v in value.values())
    if isinstance(value, list):
        return any(references(v, identities) for v in value)
    return False


def figure_depends(snapshot, figure, superseded):
    sources = {s['id']: s for s in snapshot.get('sources', [])}
    return bool(set(figure.get('source_ids', [])) & superseded or references(figure, superseded)
                or any(references(sources.get(sid, {}), superseded) for sid in figure.get('source_ids', [])))


def analysis_impact(snapshot, supersedes, requested):
    locations = locations_for(snapshot)
    valid = {(loc['kind'], loc['id']): loc for loc in locations}
    if any((loc['kind'], loc['id']) not in valid for loc in requested):
        raise invalid('影响位置必须属于本轮固定父稿。')
    selected = {(loc['kind'], loc['id']) for loc in requested}
    roles = {s['id']: s.get('purpose', s['id']) for s in normalize_sections(snapshot)}
    old = set(supersedes)
    dependent = {p['id'] for _, p in displayed_paragraphs(snapshot) if set(p.get('source_ids', [])) & old}
    for loc in locations:
        if loc['id'] in dependent:
            selected.add((loc['kind'], loc['id']))
    for group in snapshot.get('results_groups', []):
        for figure in group.get('figures', []):
            if figure_depends(snapshot, figure, old):
                selected.add(('figure', figure['id']))
        for table in group.get('tables', []):
            if set(table.get('source_ids', [])) & old:
                selected.add(('table', table['id']))
    result = []
    for role in ('abstract', 'results', 'discussion', 'captions'):
        anchors = []
        for kind, identity in sorted(selected):
            loc = valid[(kind, identity)]
            mapped = 'captions' if kind == 'figure' else 'results' if kind == 'table' else roles.get(loc['section_id'], loc['section_id'])
            if mapped == role:
                anchors.append(dict(kind=kind, id=identity))
        result.append(dict(section_id=role, locations=anchors,
            status='pending_figure' if role == 'captions' else 'requires_revision',
            reason='新数值图未生成；旧依赖图需明确移出或由实际新图替换。' if role == 'captions' else '核对新统计结果与相关表述；明确受影响处须提交具体改文。'))
    return result


def apply_analysis_sources(snapshot, adoptions, writing_context=None):
    if not adoptions:
        return snapshot, writing_context, []
    candidate = deepcopy(snapshot)
    changes = []
    tables = deepcopy(writing_context.tables) if writing_context else {}
    for row in adoptions:
        adoption = row['snapshot_json']
        source = adoption['source']
        existing = next((s for s in candidate['sources'] if s['id'] == source['id']), None)
        if existing is not None and existing != source:
            raise invalid('新分析来源与固定来源冲突。', 409)
        if existing is None:
            candidate['sources'].append(deepcopy(source))
        old = set(adoption['supersedes_source_ids'])
        lookup = {s['id']: s for s in candidate['sources']}
        replaced = []
        for g, group in enumerate(candidate.get('results_groups', [])):
            for t, table in enumerate(group.get('tables', [])):
                if not set(table.get('source_ids', [])) & old:
                    continue
                before = deepcopy(table)
                table['source_ids'] = list(dict.fromkeys(source['id'] if sid in old else sid for sid in table['source_ids']))
                table['rows'] = []
                for sid in table['source_ids']:
                    content = lookup[sid]['content']
                    table['rows'].extend(flat_values({k: content[k] for k in ('check', 'overall', 'groups', 'statistics', 'variables') if k in content}, en=candidate['output_language'] == 'en'))
                table['title'] = ('Table ' if candidate['output_language'] == 'en' else '表 ') + str(table['number']) + '. ' + source['label']
                tables[f'/results_groups/{g}/tables/{t}'] = dict(original=deepcopy(table), approved=deepcopy(table), language=candidate['output_language'])
                replaced.append(dict(before=before, after=deepcopy(table)))
                changes.append(dict(item_id=adoption['item_id'], kind='analysis_table',
                    location=dict(kind='table', id=table['id'], section_id=group['id'], section_title=group.get('title', group['id'])),
                    before=before, after=deepcopy(table), reason=adoption['reason'], evidence=[deepcopy(source)]))
        candidate.setdefault('review_analysis_provenance', []).append(dict(adoption_id=row['id'], source_id=source['id'],
            source_sha256=source['sha256'], supersedes_source_ids=deepcopy(adoption['supersedes_source_ids']),
            affected_locations=deepcopy(adoption['affected_locations']), replaced_tables=replaced, pending=deepcopy(adoption['pending'])))
    if writing_context:
        from app.domain.manuscript_review.writing_context import WritingCheckContext
        writing_context = WritingCheckContext(paragraphs=writing_context.paragraphs,
            sources={s['id']: deepcopy(s) for s in candidate['sources']}, tables=tables, check_version=writing_context.check_version)
    return candidate, writing_context, changes


def analysis_consistency_issues(candidate, adoptions):
    issues = []
    relations=list(adoptions)
    known={r['id'] for r in relations}
    sources={s['id']:s for s in candidate.get('sources',[])}
    for prior in candidate.get('review_analysis_provenance',[]):
        if prior['adoption_id'] in known:continue
        if prior['source_id'] not in sources:
            issues.append(issue('source','review_analysis_provenance','已冻结的新分析来源不可删除。',severity='error',suffix=prior['adoption_id']))
            continue
        relations.append(dict(id=prior['adoption_id'],snapshot_json=dict(source=sources[prior['source_id']],supersedes_source_ids=prior['supersedes_source_ids'])))
        known.add(prior['adoption_id'])
    for row in relations:
        adopted = row['snapshot_json']
        old = set(adopted['supersedes_source_ids'])
        for section, paragraph in displayed_paragraphs(candidate):
            bound_old = any(any(b.get('fact_id', '').startswith('analysis_run:' + sid + ':') for sid in old) for b in paragraph.get('numeric_bindings', []))
            if bound_old or set(paragraph.get('source_ids', [])) & old and (section in ('abstract', 'results', 'discussion') or NUMBER.search(paragraph['text'])):
                issues.append(issue('source', paragraph['id'], '正文仍使用明确被替代的旧统计、数值或结论来源；请采用新结果逐值改文。', severity='error', actual=sorted(old), expected=adopted['source']['id'], suffix=row['id']))
        for group in candidate.get('results_groups', []):
            for figure in group.get('figures', []):
                if figure_depends(candidate, figure, old):
                    issues.append(issue('illustration', 'caption:' + figure['id'], '旧图仍依赖明确被替代的统计结果；请明确移出当前候选或提供实际新图。', severity='error', expected='actual replacement or explicit remove_figure', suffix=row['id']))
            for table in group.get('tables', []):
                if set(table.get('source_ids', [])) & old:
                    issues.append(issue('numeric', 'table:' + table['id'], '结果表仍使用已替代统计。', severity='error', suffix=row['id']))
    return issues


def science_unexecuted(items, adoptions):
    """Finite explicit redraw requests need actual pixels, never a caption edit."""
    result=[]
    pattern=r'\b(?:redraw|replot|regenerate)\b|\bnew\s+(?:figure|plot|boxplot)\b|\bupdate\s+(?:the\s+)?(?:figure|plot|boxplot)\b|重[新绘].{0,8}(?:绘图|图表|作图)|更新.{0,4}(?:图表|数值图)|新图'
    for item in items:
        text=item['original_text']
        if not re.search(pattern,text,re.I):continue
        if re.search(r'caption|图注',text,re.I) and not re.search(r'redraw|replot|regenerate|new\s+(?:figure|plot)|新图|重绘',text,re.I):continue
        result.append(dict(item_id=item['id'],status='waiting_material',reason='本次只采用实际统计和具体文字；新的数值图尚未实际生成，继续等待实际图件及所需授权。'))
    return result
