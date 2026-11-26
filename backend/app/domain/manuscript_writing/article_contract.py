"""Opt-in W1 article structures and exact edit scopes on the existing live path.

This module never grants execution or publication. Stored schema1/2/3 wire bytes
are deliberately not reinterpreted by the new contract.
"""
from copy import deepcopy
import json
import re

from pydantic import Field
from app.core.exceptions import StorageError
from app.domain.literature.service import digest
from app.domain.research_intake.sci_templates import MAX_SCI_SECTIONS
from .contracts import Strict
from .live_contracts import LiveParagraph, scoped_draft_revision

VERSION='article-scope-v1'
COMMON={
    'title':('Title','标题'), 'abstract':('Abstract','摘要'),
    'introduction':('Introduction','引言'), 'results':('Results','结果'),
    'discussion':('Discussion','讨论'), 'materials_and_methods':('Materials and methods','材料与方法'),
    'references':('References','参考文献'), 'conclusion':('Conclusion','结论'),
    'literature_scope':('Literature sources and inclusion scope','文献来源与纳入说明'),
    'themes':('Thematic synthesis','主题综合'), 'validation':('Actual validation','实际验证'),
}
STRUCTURES={
    'research':('title','abstract','introduction','results','discussion','materials_and_methods','references'),
    'brief':('title','abstract','introduction','materials_and_methods','results','discussion','references'),
    'narrative_review':('title','abstract','introduction','literature_scope','themes','discussion','conclusion','references'),
    'methods':('title','abstract','introduction','materials_and_methods','validation','discussion','conclusion','references'),
}
OVERRIDES={
    'brief':{'abstract':('Short abstract','短摘要'),'introduction':('Brief background','简要背景')},
    'narrative_review':{'introduction':('Scope and background','范围与背景'),'discussion':('Synthesis and limitations','综合讨论与局限')},
    'methods':{'introduction':('Problem and existing methods','问题与现有方法'),'materials_and_methods':('Method and procedure','方法与步骤'),'discussion':('Applicability and limitations','适用范围与限制')},
}
_ARTICLE_RULES='''Preserve all other local prose. Full drafts use the supplied article structure, not a generic SCI template. A narrative review synthesizes only acquired literature and scope: never invent a systematic search, screening, original experiment or study results. Methods validation must use actual frozen validation evidence; if unavailable return only the supplied validation-gap text. Briefs must retain critical methods and limitations while meeting confirmed limits; unconfirmed limits remain gaps. Polish changes wording only: preserve facts, numeric expressions, citation premises and conclusion strength. Expand/restructure may only use frozen paragraph lineage and selected new sources; never transfer old review decisions to changed text. References remain server-owned. All new claims require the existing explicit human scientific and language review.'''
INSTRUCTIONS='Use article-scope-v1. Return exactly writing_scope.output_section_ids and only planned/selected paragraph identities. '+_ARTICLE_RULES
SCI_PROSE_INSTRUCTIONS=(
    'Use article-scope-v1. Return sections in the exact order of writing_scope.output_section_ids. '
    'Write at least one non-empty paragraph in every requested section, with exactly one paragraph in the title section. '
    'A full draft can assign new, unique paragraph IDs. Scoped edits use exactly the planned or selected paragraph IDs. '
    + _ARTICLE_RULES + ' '
    'Write ordinary manuscript prose and express source attribution within sentences. '
    'Treat field labels, source headings, interface text, workflow notes and internal identifiers as input context. '
    'Exclude those labels from the manuscript. Describe the documented source or observation in its place. '
    'When evidence is missing for a section, use the supplied aim, observations or methods to state the specific scope '
    'or limitation relevant to that section. Never invent results, methods, citations or literature claims.'
)


def theme_sections(snapshot):
    plan = (snapshot or {}).get('paper_plan') or {}
    if plan.get('kind') != 'narrative_review' or plan.get('combine_review_topics'):
        return []
    rows = plan['sections']
    ids = [row['id'] for row in rows]
    outline = plan.get('sci_template', {}).get('sections', STRUCTURES['narrative_review'])
    if (not rows or len(rows) + len(outline) > MAX_SCI_SECTIONS
            or len(ids) != len(set(ids))
            or any(not re.fullmatch(r'paper-[a-f0-9]{32}', sid) for sid in ids)
            or any(not row['label'].strip() for row in rows)):
        raise ValueError('Invalid frozen review themes')
    return [dict(id=row['id'], title=row['label'], level=2, parent_id='themes',
                 result_group_ids=[row['id']]) for row in rows]


def labels(kind, snapshot=None):
    children = theme_sections(snapshot) if kind == 'narrative_review' else []
    template = ((snapshot or {}).get('paper_plan') or {}).get('sci_template')
    if template and template['article_type'] == kind:
        headings = [(section['id'], section['en'], section['zh']) for section in template['sections']]
    else:
        headings = [(sid, *OVERRIDES.get(kind, {}).get(sid, COMMON[sid])) for sid in STRUCTURES[kind]]
    result = []
    for sid, english, chinese in headings:
        result.append((sid, english, chinese))
        if sid == 'themes':
            result.extend((s['id'], s['title'], s['title']) for s in children)
    return result


def template_heading_levels(kind, snapshot):
    template = (snapshot.get('paper_plan') or {}).get('sci_template')
    if not template or template['article_type'] != kind:
        return {}
    return {section['id']: section['level'] for section in template['sections'] if 'level' in section}


def combined_theme_group_ids(snapshot):
    plan = snapshot.get('paper_plan') or {}
    if not plan.get('combine_review_topics'):
        return []
    target_ids = {row['id'] for row in plan['sections']}
    target_ids.add('themes')
    return [group['id'] for group in snapshot['results_groups'] if group['id'] in target_ids]


def matches_structure(snapshot):
    kind = snapshot.get('article_type')
    if snapshot.get('article_structure_version') != VERSION or kind not in STRUCTURES:
        return False
    sections = snapshot.get('sections', [])
    if [s['id'] for s in sections] != [sid for sid, _, _ in labels(kind, snapshot)]:
        return False
    levels = template_heading_levels(kind, snapshot)
    if any(s.get('level') != levels[s['id']] for s in sections if s['id'] in levels):
        return False
    if kind == 'narrative_review' and (snapshot.get('paper_plan') or {}).get('combine_review_topics'):
        parent = next(s for s in sections if s['id'] == 'themes')
        if parent.get('result_group_ids') != combined_theme_group_ids(snapshot):
            return False
    children = {s['id']: s for s in theme_sections(snapshot)} if kind == 'narrative_review' else {}
    if children:
        group_ids = [g['id'] for g in snapshot.get('results_groups', [])]
        for section in sections:
            identity = section['id']
            if identity == 'themes' and section['paragraphs']:
                return False
            child = children.get(identity)
            if child and (any(section.get(key) != value for key, value in child.items())
                          or group_ids.count(identity) != 1):
                return False
    return True


def seed_review_sections(snapshot):
    """Keep the frozen source groups; show user prose once under its saved heading."""
    from .context import literature_paragraphs, normalize_sections

    common = {s['id']: s['paragraphs'] for s in normalize_sections(snapshot)}
    groups = {g['id']: g['paragraphs'] for g in snapshot['results_groups']}
    children = {s['id']: s for s in theme_sections(snapshot)}
    combined = (snapshot.get('paper_plan') or {}).get('combine_review_topics')
    combined_ids = combined_theme_group_ids(snapshot)
    levels = template_heading_levels('narrative_review', snapshot)
    sections = []
    for identity, _, _ in labels('narrative_review', snapshot):
        section = dict(children[identity]) if identity in children else dict(id=identity)
        if identity in levels:
            section['level'] = levels[identity]
        if identity in children:
            paragraphs = groups[identity]
        elif identity == 'themes' and combined:
            section['result_group_ids'] = combined_ids
            paragraphs = [paragraph for group in combined_ids for paragraph in groups[group]]
        elif identity == 'literature_scope':
            paragraphs = literature_paragraphs(snapshot)
        else:
            paragraphs = common.get(identity, [])
        section['paragraphs'] = deepcopy(paragraphs)
        sections.append(section)
    seeded = dict(snapshot, sections=sections, article_type='narrative_review', article_structure_version=VERSION)
    add_review_figure_references(seeded, sections)
    return seeded


def writing_keywords(base, request):
    return base['keywords'] if base.get('paper_plan') else request['keywords']


def illustration_groups(snapshot, section):
    groups = snapshot.get('results_groups', [])
    sid = section['id']
    plan = snapshot.get('paper_plan') or {}
    configured = [group for group in groups if group.get('illustration_chapter_id') == sid]
    if sid == 'results':
        return [group for group in groups if not group.get('illustration_chapter_id')] + configured
    if plan.get('kind') == 'narrative_review':
        if 'result_group_ids' in section:
            return [group for group in groups if group['id'] in section['result_group_ids']] + configured
        from app.domain.paper_materials import REVIEW_FIGURE_SECTIONS
        if plan.get('review_figure_placement_version') == 1 and sid in REVIEW_FIGURE_SECTIONS:
            return [group for group in groups if group['id'] == sid] + configured
    return configured


def add_review_figure_references(snapshot, sections):
    from app.domain.manuscripts.illustrations import BODY_REFERENCE, reference_text

    plan = snapshot.get('paper_plan') or {}
    if plan.get('review_figure_placement_version') != 1 and not plan.get('sci_figures'):
        return
    language = snapshot['output_language']
    used_ids = {p['id'] for section in snapshot['sections'] for p in section['paragraphs']}
    for section in sections:
        mentioned = {int(match['number']) for p in section['paragraphs'] for match in BODY_REFERENCE.finditer(p['text'])
                     if match['kind'].lower() not in ('table', '表')}
        for group in illustration_groups(snapshot, section):
            missing = [figure for figure in group['figures'] if figure['number'] not in mentioned]
            if not missing:
                continue
            refs = [dict(kind='figure', target_id=f['id'], number=f['number'], panel_label=None) for f in missing]
            labels = (', ' if language == 'en' else '、').join(reference_text(r, language) for r in refs)
            base_id = 'review-illustrations:' + group['id']
            identity = base_id
            suffix = 1
            while identity in used_ids:
                identity = f'{base_id}:{suffix}'
                suffix += 1
            used_ids.add(identity)
            section['paragraphs'].append(dict(id=identity, origin='image_observation',
                source_ids=[sid for f in missing for sid in f['source_ids']], citations=[], cross_references=refs,
                text=(f'See {labels}.' if language == 'en' else f'见{labels}。')))


def visible_illustration_groups(snapshot, excluded_section_ids=frozenset()):
    if (snapshot.get('paper_plan') or {}).get('kind') != 'narrative_review':
        return snapshot.get('results_groups', [])
    return [group for section in snapshot['sections']
            if section['id'] not in excluded_section_ids and section.get('parent_id') not in excluded_section_ids
            for group in illustration_groups(snapshot, section)]


class ArticleSection(Strict):
    id:str=Field(min_length=1,max_length=200)
    paragraphs:list[LiveParagraph]=Field(min_length=1,max_length=200)


class ArticleOutput(Strict):
    sections:list[ArticleSection]=Field(min_length=1,max_length=MAX_SCI_SECTIONS)


def structure(base,request):
    from .context import normalize_sections
    old=normalize_sections(base)
    if base.get('thesis_context'):return old
    kind=request['article_type']
    plan=base.get('paper_plan')
    if plan and plan['kind']!=kind:
        raise ValueError('Article type must match the frozen paper requirements')
    if request['mode']!='full_draft' and kind!=base.get('article_type','research'):
        raise ValueError('Article type changes require an explicit full draft candidate')
    by_id={s['id']:s for s in old}
    sections = [deepcopy(by_id.get(sid, dict(id=sid, paragraphs=[]))) for sid, _, _ in labels(kind, base)]
    levels = template_heading_levels(kind, base)
    for section in sections:
        if section['id'] in levels:
            section['level'] = levels[section['id']]
    return sections


def protected_section_ids(base):
    return {'references', 'themes'} if theme_sections(base) else {'references'}


def editable_draft_section_ids(candidate):
    if candidate.get('thesis_context'):
        from .school_live import WRITABLE

        return [section['id'] for section in candidate['sections'] if section['purpose'] in WRITABLE and section['paragraphs']]
    protected = protected_section_ids(candidate)
    return [section['id'] for section in candidate['sections'] if section['id'] not in protected and section['paragraphs']]


def writing_base_sections(base, request, revision_sections):
    sections = structure(base, request)
    if not scoped_draft_revision(request):
        return sections
    if not revision_sections or [s['id'] for s in revision_sections] != [s['id'] for s in sections]:
        raise ValueError('Missing original draft or changed article structure')
    return revision_sections


def scope(base,request,sections):
    from .school_live import WRITABLE
    school=bool(base.get('thesis_context'));mode=request['mode']
    protected=protected_section_ids(base)
    eligible=[s['id'] for s in sections if (s.get('purpose') in WRITABLE if school else s['id'] not in protected)]
    if scoped_draft_revision(request):
        selected_sections = set(request['target_sections'])
        targets = [s['id'] for s in sections if s['id'] in selected_sections and s['id'] in eligible and s['paragraphs']]
        if set(targets) != selected_sections:
            raise ValueError('Unknown, empty or protected target section')
    elif mode=='full_draft':targets=eligible
    else:
        if not base.get('sections'):raise ValueError('Scoped editing requires published sections')
        if (base.get('paper_plan') or {}).get('kind') == 'narrative_review' and not base.get('writing_provenance'):
            raise ValueError('Produce the planned review before requesting scoped edits')
        if mode=='rewrite_section':targets=[request['target_section']]
        elif mode=='results_discussion':
            if request['article_type']=='narrative_review' and not school:raise ValueError('Narrative review has no original results')
            targets=[s['id'] for s in sections if s.get('purpose',s['id']) in (('validation','discussion') if request['article_type']=='methods' and not school else ('results','discussion'))]
            roles={s.get('purpose',s['id']) for s in sections if s['id'] in targets}
            if len(roles)!=2:raise ValueError('Both results and discussion roles must exist')
        else:targets=request['target_sections']
        if not targets or not set(targets)<=set(eligible):raise ValueError('Unknown or protected target section')
        targets=[s['id'] for s in sections if s['id'] in targets]
    old={p['id']:(s['id'],p) for s in sections for p in s['paragraphs']}
    selected=request['target_paragraph_ids'] or [p['id'] for s in sections if s['id'] in targets for p in s['paragraphs']]
    if not set(selected)<=old.keys() or any(old[pid][0] not in targets for pid in selected):raise ValueError('Paragraph lies outside frozen target')
    if mode!='full_draft' and any(not any(old[p][0]==sid for p in selected) for sid in targets):raise ValueError('Every target must contain selected paragraphs')
    plan=request['paragraph_plan'];lineage=set()
    for row in plan:
        ancestors=row['source_paragraph_ids']
        if row['section_id'] not in targets or len(ancestors)!=len(set(ancestors)) or not set(ancestors)<=set(selected):raise ValueError('Lineage consumes non-target paragraph')
        if row['id'] in old and (row['id'] not in selected or ancestors!=[row['id']]):raise ValueError('Existing paragraph identity cannot be reassigned')
        if not ancestors and not (request['selected_source_ids'] or request['selected_evidence_ids']):raise ValueError('New paragraph requires selected evidence')
        lineage.update(ancestors)
    if mode=='expand_restructure' and (lineage!=set(selected) or any(not any(r['section_id']==sid for r in plan) for sid in targets)):
        raise ValueError('Explicit paragraph plan must account for every selected identity')
    return dict(version=VERSION,mode=mode,target_section_ids=targets,target_paragraph_ids=selected,
        preserved_paragraph_ids=[pid for pid in old if (mode!='full_draft' or scoped_draft_revision(request)) and pid not in selected],
        paragraph_plan=deepcopy(plan),base_sections_sha256=digest(sections))


def validation_gap(language):
    return 'Actual validation evidence was not provided; performance and comparative benchmarks remain unverified.' if language=='en' else '未提供实际验证证据；性能和对照基准尚未验证。'


def has_validation(payload):
    # Explicit user assignment freezes intended use, never scientific validity.
    return bool(payload.get('validation_source_aliases'))


def _advice_bundle(base, request, frozen, sections, editing, revision_figures):
    from .bundle import finish_bundle, safe_text

    english = request['output_language'] == 'en'
    headings = {sid: en if english else zh for sid, en, zh in labels(request['article_type'], base)}
    selected = set(editing['target_section_ids'])
    payload = dict(output_language=request['output_language'], instructions=safe_text(request['instructions']),
                   draft_sections=[dict(heading=safe_text(headings[section['id']]),
                                        paragraphs=[safe_text(paragraph['text']) for paragraph in section['paragraphs']],
                                        **({'id': section['id']} if revision_figures else {}))
                                   for section in sections if section['id'] in selected])
    local = dict(sources={}, evidence={}, writing_scope=editing)
    omitted = ['attachments', 'binary_images', 'local_paths', 'private_configuration', 'prior_reviews',
               'source_catalogs', 'evidence_catalogs', 'unselected_sections']
    return finish_bundle(payload, frozen, local, omitted, revision_sections=sections,
                         revision_figures=revision_figures, figure_section_ids=editing['target_section_ids'])


def build_bundle(base,request,frozen,*,include_reported_results=True,revision_sections=None,revision_figures=()):
    from .bundle import build_bundle as common, finish_bundle, safe_text
    from .context import paragraph_sources_selected
    from .school_live import build_bundle as school_bundle
    from .paper_context import add_illustration_context, add_notes, is_note, place_illustrations, review_material_ids
    school=bool(base.get('thesis_context'))
    if (request['document_kind']=='thesis')!=school or frozen['document_kind']!=request['document_kind']:raise ValueError('Frozen document kind mismatch')
    scoped = scoped_draft_revision(request)
    if bool(revision_figures) != bool(frozen.get('scope_figure_input')) or revision_figures and (school or not scoped):
        raise ValueError('Figure input requires a scoped SCI draft')
    sections=writing_base_sections(base,request,revision_sections);editing=scope(base,request,sections)
    if request.get('draft_advice') is True:
        if school or not scoped:
            raise ValueError('Draft advice requires a scoped SCI draft')
        return _advice_bundle(base, request, frozen, sections, editing, revision_figures)
    seed_contract={k:deepcopy(v) for k,v in frozen.items()
                   if k not in ('document_kind','article_scope_version','numeric_contract_version','article_instruction_revision',
                                'response_stream','scope_figure_input','skills_snapshot')}
    seed_contract['schema_version']=3 if school else 2
    seed_request=dict(request,mode='full_draft',target_section=None,keywords=writing_keywords(base,request))
    if school:seed_contract.update(numeric_contract_version=2,school_content_version='school-live-v1')
    seed=(school_bundle if school else common)(base,seed_request,seed_contract) if school else common(base,seed_request,execution_contract=seed_contract)
    payload=json.loads(json.loads(seed['wire_json'])['input']);local=seed['local_manifest']
    if include_reported_results and not school and request['article_type']=='research':
        from .numeric_contract import add_reported_results
        add_reported_results(base,request,payload,local,safe_text)
    if request['article_type']=='narrative_review' and not school:
        from .numeric_contract import add_literature_numbers, includes_written_literature_counts
        if includes_written_literature_counts(frozen):
            add_literature_numbers(payload['evidence'], include_written_cardinals=True)
        allowed = review_material_ids(base)
        prohibited=[s for s in payload['sources']
                    if local['sources'][s['alias']] not in allowed
                    and (s.get('role') in ('computed_results','user_results','image_observation') or s.get('kind')=='analysis_run')]
        if prohibited:raise ValueError('Narrative review uses acquired literature evidence, not original study results')
        if not base.get('paper_plan'):
            payload['illustrations']=[]
        else:
            allowed_illustrations={(kind, item['number'])
                                   for group in base['results_groups'] for kind in ('figure', 'table')
                                   for item in group[kind+'s'] if item['source_ids'] and set(item['source_ids']) <= allowed}
            payload['illustrations']=[item for item in payload['illustrations']
                                      if (item['kind'], item['number']) in allowed_illustrations]
    local['writing_scope']=editing
    selected_ids=set(request['selected_source_ids'])
    reviewed_sources=frozen.get('source_selection_version')==2
    if school:
        layout=local['school'];mapping={c['chapter_id']:a for a,c in layout['chapters'].items()}
        layout['writable_aliases']=[mapping[sid] for sid in editing['target_section_ids']]
        payload['chapters']=[c for c in payload['chapters'] if c['alias'] in layout['writable_aliases']]
        aliases={pid:f'paragraph{i+1}' for i,pid in enumerate([p['id'] for s in sections for p in s['paragraphs']])}
        for row in editing['paragraph_plan']:
            if row['id'] not in aliases:aliases[row['id']]=f'paragraph{len(aliases)+1}'
        local['writing_paragraph_aliases']={alias:pid for pid,alias in aliases.items()}
    else:
        mapping={s['id']:s['id'] for s in sections}
        if scoped:
            aliases = {p['id']: f"{s['id']}-p{i}" for s in sections if s['id'] in editing['target_section_ids']
                       for i, p in enumerate(s['paragraphs'], 1)}
            local['writing_paragraph_aliases'] = {alias: pid for pid, alias in aliases.items()}
        else:
            aliases={p['id']:p['id'] for s in sections for p in s['paragraphs']}
        add_notes(base, request, payload, local, mapping)
        place_illustrations(base, payload, mapping)
        add_illustration_context(base, payload, local)
    output_ids=[mapping[sid] for sid in editing['target_section_ids']]
    if scoped:
        payload['draft_revision_scope'] = 'selected_sections'
        payload['original_draft'] = [dict(id=s['id'], paragraphs=[
            dict(id=aliases[p['id']], text=safe_text(p['text']), source_aliases=p.get('suggested_source_aliases', []),
                 evidence_aliases=p.get('suggested_evidence_aliases', [])) for p in s['paragraphs']])
            for s in sections if s['id'] in output_ids]
        payload['context'] = [row for row in payload['context'] if row['id'] in output_ids]
    elif request.get('revision_of_request_id'):
        if not revision_sections or [s['id'] for s in revision_sections] != output_ids:
            raise ValueError('Missing original draft or changed article structure')
        payload['original_draft'] = revision_sections
    payload.update(schema_version=4,article_scope_version=VERSION,document_kind=request['document_kind'],article_type=request['article_type'],
        mode=request['mode'],target_section=mapping.get(request['target_section']),brief_limits=request['brief_limits'])
    wire_scope=dict(output_section_ids=output_ids,mode=request['mode'],
        target_paragraph_ids=[aliases[p] for p in editing['target_paragraph_ids']],
        paragraph_plan=[dict(id=aliases.get(r['id'],r['id']),section_id=mapping[r['section_id']],source_paragraph_ids=[aliases[p] for p in r['source_paragraph_ids']]) for r in editing['paragraph_plan']])
    payload['writing_scope']=wire_scope
    headings={sid:en if request['output_language']=='en' else zh for sid,en,zh in labels(request['article_type'],base)}
    payload['article_structure']=[dict(id=mapping[s['id']],heading=safe_text(s['title'] if school else headings[s['id']]),
        **({key: s[key] for key in ('parent_id', 'level') if key in s} if not school else {}))
        for s in sections if s['id'] in mapping and (not school or mapping[s['id']] in local['school']['writable_aliases'])]
    if school:
        # Add paragraph aliases only to eligible text already projected by school.
        for context in payload['context']:
            chapter=local['school']['chapters'][context['id']]
            rows=next(s for s in sections if s['id']==chapter['chapter_id'])['paragraphs']
            permitted=[p for p in rows if not p.get('citations') and paragraph_sources_selected(p,selected_ids,reviewed_sources=reviewed_sources)
                       and not (base.get('paper_plan') and is_note(p))]
            for projected,p in zip(context['paragraphs'],permitted):projected['id']=aliases[p['id']]
    else:
        for context in payload['context']:
            old=next((s for s in sections if s['id']==context['id']),None)
            if old:
                for p in context['paragraphs']:
                    original=next((v for v in old['paragraphs'] if v['text']==p['text']),None)
                    if original:p['id']=aliases[original['id']]
    from .context import citation_prose
    citation_context={}
    for section in sections:
        if section['id'] not in editing['target_section_ids']:continue
        for paragraph in section['paragraphs']:
            if not paragraph.get('citations') or paragraph['id'] not in editing['target_paragraph_ids']:continue
            if reviewed_sources and not paragraph_sources_selected(paragraph,selected_ids,reviewed_sources=True):continue
            evidence_ids={e['id'] for binding in paragraph['citations'] for e in binding.get('evidence',[])}
            if not evidence_ids or not evidence_ids<=set(request['selected_evidence_ids']):
                if request['mode']=='polish':raise ValueError('Polishing cited prose requires its explicitly selected frozen evidence')
                continue
            text=safe_text(citation_prose(base,paragraph))
            required_aliases=[alias for alias,row in local['evidence'].items() if row['evidence_id'] in evidence_ids]
            citation_context[paragraph['id']]=dict(text=text,required_evidence_aliases=required_aliases)
            sid=mapping[section['id']]
            context=next((row for row in payload['context'] if row['id']==sid),None)
            if context is None:context=dict(id=sid,paragraphs=[]);payload['context'].append(context)
            context['paragraphs'].append(dict(id=aliases[paragraph['id']],text=text))
    local['citation_context']=citation_context
    validation_ids=request.get('validation_source_ids',[])
    validation_aliases=[alias for alias,sid in local['sources'].items() if sid in validation_ids]
    computed={s['alias'] for s in payload['sources'] if s.get('role')=='computed_results' and s.get('kind')=='analysis_run' and s.get('facts')}
    if len(validation_aliases)!=len(validation_ids) or not set(validation_aliases)<=computed:
        raise ValueError('Validation requires explicitly selected computed study sources with facts')
    local['validation_source_ids']=deepcopy(validation_ids)
    payload['validation_source_aliases']=validation_aliases
    payload['validation_available']=has_validation(payload)
    payload['validation_gap']=validation_gap(request['output_language'])
    return finish_bundle(payload, frozen, local, seed['omitted_manifest'], revision_sections=revision_sections,
                         revision_figures=revision_figures, figure_section_ids=editing['target_section_ids'])


def output_schema(payload,*,require_paragraph=False):
    from .numeric_contract import output_schema as numeric_schema
    result=numeric_schema(payload);ids=payload['writing_scope']['output_section_ids']
    section=result['$defs']['LiveSection']['properties']
    section['id']=dict(type='string',enum=ids)
    if require_paragraph:
        section['paragraphs']['minItems']=1
    result['properties']['sections'].update(minItems=len(ids),maxItems=len(ids))
    return result


def selected_ids(candidate):
    return set(candidate['writing_provenance'].get('target_paragraph_ids',[]))


def enforce_science(candidate,payload,target_ids):
    if candidate.get('article_type')=='methods' and payload['validation_available']:
        validation=next(s for s in candidate['sections'] if s['id']=='validation')
        permitted=set(payload['validation_source_aliases'])
        for p in validation['paragraphs']:
            if p['id'] in target_ids and (not p.get('suggested_source_aliases') or not set(p['suggested_source_aliases'])<=permitted or any(b['source_alias'] not in permitted for b in p.get('study_numeric_bindings',[]))):
                raise ValueError('Validation prose must trace only its explicitly assigned computed sources')
    if candidate.get('article_type')=='methods' and not payload['validation_available']:
        validation=next(s for s in candidate['sections'] if s['id']=='validation')
        for p in validation['paragraphs']:
            if p['id'] not in target_ids:continue
            if any(p.get(key) for key in ('study_numeric_bindings','context_numeric_bindings','literature_numeric_bindings')):raise ValueError('Validation facts require explicitly assigned computed validation sources')
            if re.search(r'outperform|benchmark|accuracy|sensitivity|specificity|性能|准确|优于|领先',p['text'],re.I):raise ValueError('Validation evidence unavailable; performance claim is forbidden')
            p['text']=payload['validation_gap']
    if candidate.get('article_type')=='narrative_review':
        from .paper_context import review_material_ids
        original_result_ids={s['id'] for s in candidate.get('sources',[]) if s.get('role') in ('computed_results','user_results','image_observation') or s.get('kind')=='analysis_run'}
        original_result_ids -= review_material_ids(candidate)
        for s in candidate['sections']:
            for p in s['paragraphs']:
                if p['id'] in target_ids and (set(p.get('source_ids',[])) & original_result_ids or p.get('study_numeric_bindings')):raise ValueError('Literature review cannot claim original study results')
    if candidate.get('article_type')=='brief':
        limits=payload.get('brief_limits') or {}
        words=sum(len(re.findall(r'[\u4e00-\u9fff]|[^\W\u4e00-\u9fff]+',p['text'])) for s in candidate['sections'] if s['id']!='references' for p in s['paragraphs'])
        figures=sum(len(g.get('figures',[])) for g in candidate['results_groups'])
        if limits.get('max_words') is not None and words>limits['max_words']:raise ValueError('Brief word limit exceeded')
        if limits.get('max_figures') is not None and figures>limits['max_figures']:raise ValueError('Brief figure limit exceeded')


def compose(output,snapshot,bundle,call_id,provenance,composition_version):
    from .numeric_contract import validate_bindings
    from .school_live import compose as school_compose,validate_preservation
    from .context import normalize_sections
    from .frozen import wire_payload
    from app.domain.manuscripts.illustrations import check_references,rendered_groups
    from .numeric_review import numbers
    parsed=ArticleOutput.model_validate(output).model_dump(mode='json');request=snapshot['input'];base=snapshot['base_snapshot']
    payload=wire_payload(bundle['wire_json']);local=bundle['local_manifest'];editing=local['writing_scope'];school=bool(base.get('thesis_context'))
    if [s['id'] for s in parsed['sections']]!=payload['writing_scope']['output_section_ids']:raise ValueError('Wrong output section scope')
    scoped = scoped_draft_revision(request)
    original=writing_base_sections(base,request,bundle.get('revision_sections'))
    if digest(original)!=editing['base_sections_sha256']:raise ValueError('Frozen edit base mismatch')
    aliases=local.get('writing_paragraph_aliases',{})
    result=deepcopy(base);proposed={};seen=set()
    if school:
        result=school_compose(parsed,snapshot,bundle,call_id,provenance,composition_version)
        for rendered,raw in zip((s for s in result['sections'] if s['id'] in editing['target_section_ids']),parsed['sections']):
            for paragraph,wire_p in zip(rendered['paragraphs'],raw['paragraphs']):paragraph['id']=aliases.get(wire_p['id'],wire_p['id'])
            proposed[rendered['id']]=rendered['paragraphs']
    else:
        for section in parsed['sections']:
            paragraphs=[]
            for p in section['paragraphs']:
                pid = aliases.get(p['id'], p['id'])
                if not set(p['source_aliases'])<=local['sources'].keys() or len(p['source_aliases'])!=len(set(p['source_aliases'])):raise ValueError('Unknown source alias')
                if not set(p['evidence_aliases'])<=local['evidence'].keys() or len(p['evidence_aliases'])!=len(set(p['evidence_aliases'])):raise ValueError('Unknown evidence alias')
                bindings=validate_bindings(p,payload)
                issues=check_references(rendered_groups(base,[dict(id=pid,text=p['text'],origin='model_generated')]),request['output_language'])
                if any(i['field']==pid for i in issues):raise ValueError('Unknown figure or table')
                paragraphs.append(dict(id=pid,text=p['text'],origin='model_generated',source_ids=[local['sources'][a] for a in p['source_aliases']],
                    citations=[],numeric_bindings=[],suggested_source_aliases=p['source_aliases'],suggested_evidence_aliases=p['evidence_aliases'],
                    study_numeric_bindings=bindings['study'],context_numeric_bindings=bindings['context'],literature_numeric_bindings=bindings['literature'],verification_status='pending'))
            proposed[section['id']]=paragraphs
        result.update(article_type=request['article_type'],article_structure_version=VERSION)
        if request['mode']=='full_draft':
            result.update(output_language=request['output_language'],keywords=deepcopy(writing_keywords(base,request)),acknowledgements=request['acknowledgements'])
        elif request['output_language']!=base['output_language']:raise ValueError('Scoped editing cannot change manuscript language')
    old={p['id']:p for s in original for p in s['paragraphs']}
    for sid,paragraphs in proposed.items():
        ids=[p['id'] for p in paragraphs]
        if request['mode']!='full_draft':
            expected=[r['id'] for r in editing['paragraph_plan'] if r['section_id']==sid] if request['mode']=='expand_restructure' else [p['id'] for s in original if s['id']==sid for p in s['paragraphs'] if p['id'] in editing['target_paragraph_ids']]
            if ids!=expected:raise ValueError('Output paragraph identities differ from frozen plan')
        for p in paragraphs:
            if p['id'] in seen:raise ValueError('Duplicate paragraph identity')
            seen.add(p['id'])
            if request['mode']=='polish':
                prior=old[p['id']]
                cited=local.get('citation_context',{}).get(p['id'])
                prior_text=cited['text'] if cited else prior['text']
                if numbers(p['text'])!=numbers(prior_text) or p['source_ids']!=prior.get('source_ids',[]):raise ValueError('Polish must preserve facts, numeric strings and sources')
                # New certainty terms are rejected; semantics still require exact human review.
                certainty=r'\bsignifican\w*|\bcaus\w*|\bprove\w*|\bsuperior\w*|显著|因果|证明|优于'
                if set(re.findall(certainty,p['text'],re.I))-set(re.findall(certainty,prior['text'],re.I)):raise ValueError('Polish cannot strengthen conclusions')
                if prior.get('citations') and p['text']!=prior['text'] and not p.get('suggested_evidence_aliases'):raise ValueError('Polishing cited prose requires selected literature evidence and new review')
                if cited and not set(cited['required_evidence_aliases'])<=set(p.get('suggested_evidence_aliases',[])):raise ValueError('Polishing cited prose must trace its explicitly selected evidence')
            if p['id'] in old and p['text']==old[p['id']]['text'] and p['source_ids']==old[p['id']].get('source_ids',[]):
                saved=deepcopy(old[p['id']]);p.clear();p.update(saved)
    final=[]
    for section in original:
        s=deepcopy(section);ps=proposed.get(s['id'])
        if ps is not None:
            if request['mode']=='full_draft':s['paragraphs']=ps
            elif request['mode']!='expand_restructure':
                replacements={p['id']:p for p in ps}
                s['paragraphs']=[replacements.get(p['id'],p) for p in s['paragraphs']]
            else:
                merged=[];inserted=False
                for p in s['paragraphs']:
                    if p['id'] in editing['target_paragraph_ids']:
                        if not inserted:merged.extend(ps);inserted=True
                    else:merged.append(p)
                s['paragraphs']=merged
        final.append(s)
    result['sections']=final
    if request['mode'] == 'full_draft':
        add_review_figure_references(result, [s for s in final if s['id'] in proposed] if scoped else final)
    all_ids=[p['id'] for s in final for p in s['paragraphs']]
    if len(all_ids)!=len(set(all_ids)):raise ValueError('Duplicate paragraph identity across candidate')
    if not school:
        if len(final[0]['paragraphs'])!=1:raise ValueError('Exactly one title paragraph required')
        result['title']=final[0]['paragraphs'][0]['text']
    if result.get('review_provenance'):result.setdefault('review_history',[]).append(dict(provenance=result.pop('review_provenance'),review=result.pop('review'),applies_to_current_text=False,status='historical_requires_recheck'))
    result['writing_provenance']=dict(schema_version=2,request_id=snapshot['request_id'],bundle_id=bundle['id'],bundle_sha256=bundle['bundle_sha256'],
        model_call_id=call_id,provider_provenance=provenance,verification_status='pending',raw_output=parsed,raw_output_sha256=digest(parsed),
        required_reviews=['scientific_claims','study_numeric_facts','complete_language']+(['school_export'] if school else []),base_version_id=snapshot['base_version_id'],composition_version=composition_version,
        numeric_contract_version=2,writing_scope_version=1,mode=request['mode'],target_section_ids=editing['target_section_ids'],target_paragraph_ids=[p['id'] for s in final for p in s['paragraphs'] if p['id'] in seen],
        preserved_paragraph_ids=editing['preserved_paragraph_ids'],paragraph_lineage=deepcopy(editing['paragraph_plan']))
    if skills := bundle['execution_contract'].get('skills_snapshot'):
        result['writing_provenance']['skills_trace'] = deepcopy(skills['trace'])
    if school:
        result['writing_provenance']['school_content_version']='school-live-v1'
        from .school_live import update_notice
        from app.domain.manuscripts.school import school_content_report
        validate_preservation(result,base,bundle);result['school_content_report']=school_content_report(result)
    else:
        # A legacy journal display mapping cannot relabel a different structure.
        research_order = [sid for sid, _, _ in labels('research', base)]
        if [s['id'] for s in original] != research_order:
            result.pop('journal_display_context', None)
        from .live_notice import update_notice
    enforce_science(result,payload,seen)
    if request.get('revision_of_request_id'):
        def section_text(sections):
            return {s['id']: ' '.join(' '.join(p['text'] for p in s['paragraphs']).split())
                    for s in sections if s['paragraphs'] and s['id'] != 'references'}
        revised_sections = [s for s in final if s['id'] in proposed] if scoped else final
        if section_text(revised_sections) == section_text(payload['original_draft']):
            raise ValueError('Revision text is unchanged')
    if request['article_type']=='brief' and not request['brief_limits']:
        result['issues'].append(dict(id='brief_limits',kind='missing',field='brief_limits',message='Brief word and figure limits are unconfirmed; target compliance is not established.',values=[]))
    update_notice(result,request)
    return result
