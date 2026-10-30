"""Project selected saved pixels into a fixed manuscript without scientific rewriting."""
from copy import deepcopy
from app.domain.literature.service import digest
from app.domain.manuscript_review.checks import issue
from .planning import invalid


def apply_figure_sources(snapshot, adoptions, analyses=(), writing_context=None):
    if not adoptions:
        return snapshot, writing_context, []
    candidate = deepcopy(snapshot)
    changes = []
    for row in adoptions:
        adopted = row['snapshot_json'];source = adopted['source'];analysis = adopted['analysis_source']
        for material in (analysis, source):
            prior = next((s for s in candidate['sources'] if s['id'] == material['id']), None)
            if prior is not None and prior != material:
                raise invalid('新图或分析来源与固定来源冲突。', 409)
            if prior is None:candidate['sources'].append(deepcopy(material))
        old_id = adopted['supersedes_figure_id']
        group = next((g for g in candidate['results_groups'] if any(f['id'] == old_id for f in g.get('figures', []))), None)
        if group is None or any(f['id'] == source['id'] for g in candidate['results_groups'] for f in g.get('figures', [])):
            raise invalid('被替代图必须唯一存在于固定父稿，且新图尚未使用。', 409)
        old = next(f for f in group['figures'] if f['id'] == old_id);content = source['content']
        from .science_candidates import figure_depends
        old_analyses={s['id'] for s in snapshot['sources'] if s['kind']=='analysis_run' and figure_depends(snapshot,old,{s['id']}) and s['id']!=analysis['id']}
        selected=[r['snapshot_json'] for r in analyses if r['snapshot_json']['item_id']==adopted['item_id'] or set(r['snapshot_json']['supersedes_source_ids']) & old_analyses]
        if any(r['source']!=analysis for r in selected):
            raise invalid('新图必须绑定明确采用的同一分析和确认数据。',409)
        figure = dict(id=source['id'], number=old['number'], title=content['title'], caption=content['caption'],
            caption_status='source', caption_origin='source', panels=deepcopy(content.get('panels', [])),
            sha256=source['sha256'], source_ids=[source['id'], analysis['id']], preview_url=source['download_url'])
        group['figures'] = [figure if f['id'] == old_id else f for f in group['figures']]
        # Update the same exact identities in both persisted paragraph views.
        for paragraphs in [*[s['paragraphs'] for s in candidate.get('sections', [])],
                           *[g.get('paragraphs', []) for g in candidate['results_groups']]]:
            for paragraph in paragraphs:
                refs = paragraph.get('cross_references', [])
                if not any(r.get('kind') == 'figure' and r.get('target_id') == old_id for r in refs):continue
                for ref in refs:
                    if ref.get('kind') == 'figure' and ref.get('target_id') == old_id:ref['target_id'] = source['id']
                retained_sources={sid for ref in refs if ref.get('kind')=='figure' and ref.get('target_id')!=source['id']
                    for g in candidate['results_groups'] for f in g.get('figures',[]) if f['id']==ref.get('target_id') for sid in f.get('source_ids',[])}
                paragraph['source_ids'] = list(dict.fromkeys([sid for sid in paragraph.get('source_ids',[]) if sid not in old['source_ids'] or sid in retained_sources]+[source['id']]))
        candidate.setdefault('review_figure_provenance', []).append(dict(adoption_id=row['id'], source_id=source['id'],
            source_sha256=source['sha256'], supersedes_figure_id=old_id, item_id=adopted['item_id'],
            analysis_source_id=analysis['id'],supersedes_analysis_source_ids=sorted(old_analyses)))
        changes.append(dict(item_id=adopted['item_id'], kind='figure_replacement',
            location=dict(kind='figure', id=old_id, section_id=group['id'], section_title=group.get('title', group['id'])),
            before=deepcopy(old), after=deepcopy(figure), reason=adopted['reason'],
            evidence=[dict(id=s['id'], kind=s['kind'], sha256=digest(s), content=deepcopy(s['content'])) for s in (source, analysis)]))
    if writing_context:
        from app.domain.manuscript_review.writing_context import WritingCheckContext
        # Reconstruct unchanged prose against its updated cross-reference/source identities.
        paragraphs = deepcopy(writing_context.paragraphs)
        for section in candidate.get('sections', []):
            for paragraph in section['paragraphs']:
                prior = paragraphs.get(paragraph['id'])
                if prior and prior['paragraph'] != paragraph:
                    prior['paragraph'] = deepcopy(paragraph)
        writing_context = WritingCheckContext(paragraphs=paragraphs, sources={s['id']:deepcopy(s) for s in candidate['sources']},
            tables=writing_context.tables, check_version=writing_context.check_version)
    return candidate, writing_context, changes


def figure_consistency_issues(candidate, adoptions=()):
    relations = {r['adoption_id']:r for r in candidate.get('review_figure_provenance', [])}
    for row in adoptions:
        a = row['snapshot_json'];relations.setdefault(row['id'],dict(source_id=a['source']['id'], source_sha256=a['source']['sha256'], supersedes_figure_id=a['supersedes_figure_id']))
    issues = []
    sources = {s['id']:s for s in candidate.get('sources', [])}
    figures = [f for g in candidate.get('results_groups', []) for f in g.get('figures', [])]
    successors = {r['supersedes_figure_id']:r['source_id'] for r in relations.values()}
    superseded = set(successors)
    for identity, relation in relations.items():
        source = sources.get(relation['source_id']);figure = next((f for f in figures if f['id'] == relation['source_id']), None)
        # Every historical material stays frozen; only the chain endpoint must
        # still be displayed. A retained successful task can form a back edge,
        # which must remain invalid even after an explicit current-figure removal.
        cursor = relation['source_id'];seen = set()
        while cursor in successors and cursor not in seen:
            seen.add(cursor);cursor = successors[cursor]
        cyclic = cursor in seen
        if (not source or source['sha256'] != relation['source_sha256'] or cyclic
            or any(f['id'] == relation['supersedes_figure_id'] for f in figures)
            or relation['source_id'] not in superseded and (not figure
                or figure['sha256'] != relation['source_sha256'] or relation['source_id'] not in figure['source_ids']
                or not figure.get('caption', '').strip() or figure.get('caption_status') in (None, 'missing', 'candidate')
                or figure.get('caption_origin') == 'source' and figure['caption'] != source.get('content', {}).get('caption'))):
            issues.append(issue('illustration', 'caption:'+relation['source_id'], '明确采用的新图、来源与有效图注必须保留；不可重新引入旧图。', severity='error', suffix=identity))
        old=set(relation.get('supersedes_analysis_source_ids',[]))
        from app.domain.manuscript_review.facts import displayed_paragraphs
        from app.domain.manuscript_writing.context import NUMBER
        for section,paragraph in displayed_paragraphs(candidate):
            bound=any(any(b.get('fact_id','').startswith('analysis_run:'+sid+':') for sid in old) for b in paragraph.get('numeric_bindings',[]))
            if bound or set(paragraph.get('source_ids',[]))&old and (section in ('abstract','results','discussion') or NUMBER.search(paragraph['text'])):
                issues.append(issue('source',paragraph['id'],'新图已替代旧分析图；正文仍使用旧统计，须明确采用新分析并逐值改文。',severity='error',suffix=identity))
    return issues
