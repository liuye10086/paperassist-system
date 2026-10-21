"""Compose prose separately from immutable statistical facts and citation decisions."""
from copy import deepcopy
import re

from .contracts import WritingOutput, SECTION_IDS, PROMPT_VERSION, POLICY_VERSION
from app.domain.literature.service import digest

# Do not use a word boundary: Unicode \w includes Chinese characters, so
# "样本量12" must yield the whole 12 and "P值1e-05" one complete token.
# New prose is deliberately conservative even for digits inside identifiers;
# exact frozen paragraphs retain their original text and provenance below.
NUMBER = re.compile(r'[-+]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][-+]?\d+)?')
MISSING = re.compile(r'missing|unavailable|requires? (?:review|verification)|not provided|待核实|缺失|未提供|待补充',re.I)


class WritingCitationScopeError(ValueError):
    """Rewriting needs a full draft or renewed, ordered reviewed citations."""


def literature_paragraphs(snapshot):
    """Only immutable, already reviewed exact rendering may carry its decisions."""
    citation=snapshot.get('citation_snapshot') or {}
    resolved={p['id']:p for p in citation.get('paragraphs',[])}
    result=[]
    for output in citation.get('output',{}).get('paragraphs',[]):
        paragraph=resolved.get(output['id'])
        if not paragraph: continue
        bindings=[deepcopy(b) for f in paragraph.get('fragments',[]) if f.get('kind')=='claim' for b in f.get('bindings',[])]
        if bindings:
            result.append(dict(id='literature:'+output['id'],text=output['text'],origin='literature',source_ids=[],citations=bindings,numeric_bindings=[]))
    return result


def normalize_sections(snapshot):
    if 'sections' in snapshot:
        sections=deepcopy(snapshot['sections'])
        if [s['id'] for s in sections] != list(SECTION_IDS):
            raise ValueError('Invalid frozen sections')
        return sections
    paragraphs={key:[] for key in SECTION_IDS}
    paragraphs['title']=[dict(id='title:1',text=snapshot['title'],origin='user_provided',source_ids=[],citations=[])]
    paragraphs['materials_and_methods']=deepcopy(snapshot.get('methods',[]))
    reviewed={p['id']:p for p in literature_paragraphs(snapshot)}
    for paragraph in paragraphs['materials_and_methods']:
        saved=reviewed.get(paragraph['id'])
        # Legacy fact drafts add a fixed source-scope prefix to this exact text.
        prefix='Literature finding (not this study’s results): ' if snapshot.get('output_language')=='en' else '文献发现（并非本研究结果）：'
        if saved and paragraph['text'] in (saved['text'],prefix+saved['text']):
            paragraph['citations']=deepcopy(saved['citations'])
    paragraphs['results']=[deepcopy(p) for group in snapshot.get('results_groups',[]) for p in group.get('paragraphs',[])]
    for index,reference in enumerate(snapshot.get('references',[])):
        text=reference.get('text') or reference.get('formatted') or reference.get('formatted_reference')
        if text:
            paragraphs['references'].append(dict(id='reference:'+str(index+1),text=text,origin='literature',source_ids=[],citations=[]))
    return [dict(id=key,paragraphs=paragraphs[key]) for key in SECTION_IDS]


def numeric_leaves(value):
    if isinstance(value,dict):
        for child in value.values(): yield from numeric_leaves(child)
    elif isinstance(value,list):
        for child in value: yield from numeric_leaves(child)
    elif type(value) in (int,float): yield str(value)


def numeric_facts(base):
    result={}
    for source in base.get('sources',[]):
        if source.get('kind')!='analysis_run' or source.get('role')!='computed_results': continue
        content=source.get('content',{})
        result[source['id']]=set(numeric_leaves({key:content[key] for key in ('statistics','overall','groups','comparisons','coefficients') if key in content}))
    return result


def _validate_generated(paragraph,base,old,facts,section_id):
    sources={source['id'] for source in base.get('sources',[])}
    if len(set(paragraph['source_ids']))!=len(paragraph['source_ids']) or not set(paragraph['source_ids'])<=sources:
        raise ValueError('Unknown or duplicate source')
    # Only exact unchanged paragraphs can carry an existing reviewed binding.
    unchanged=next((p for p in [*old,*literature_paragraphs(base)] if p['id']==paragraph['id'] and p['text']==paragraph['text']),None)
    if paragraph['citations'] and (not unchanged or paragraph['citations']!=unchanged.get('citations',[])):
        raise ValueError('Rewritten literature requires a new support review')
    bindings=paragraph['numeric_bindings']
    if any('fact_id' in binding for binding in bindings):
        if (unchanged and all(paragraph.get(key,[])==unchanged.get(key,[]) for key in ('source_ids','citations','numeric_bindings'))
            and (base.get('review_provenance') or base.get('review_history'))):
            # Preserve the complete reviewed paragraph, including its exact
            # leaf binding and permitted display precision. This is not a
            # license to generate new text or transfer the old review.
            return
        raise ValueError('Reviewed fact bindings require an exact unchanged paragraph; changed text needs a new material review')
    if section_id in ('introduction','discussion') and not paragraph['source_ids'] and not paragraph['citations'] and not MISSING.search(paragraph['text']):
        raise ValueError('Substantive prose requires frozen source trace')
    for binding in bindings:
        if binding['source_id'] not in paragraph['source_ids'] or binding['value'] not in facts.get(binding['source_id'],set()):
            raise ValueError('Numeric binding is not a frozen statistical fact')
    if not unchanged:
        from app.domain.manuscripts.illustrations import BODY_REFERENCE, check_references, rendered_groups
        # Figure/table ordinals are identities, not statistical observations.
        # Validate against the frozen targets before excluding their digits.
        checked={**paragraph,'origin':'model_generated'}
        issues=check_references(rendered_groups(base,[checked]),base['output_language'])
        if any(issue['field']==paragraph['id'] for issue in issues):
            raise ValueError('Generated body references an unknown figure, table or panel')
        numbers=set(NUMBER.findall(BODY_REFERENCE.sub('',paragraph['text'])))
        if numbers != {b['value'] for b in bindings}:
            raise ValueError('Every numeric expression requires its exact frozen fact binding')


def compose_candidate(output,snapshot,model_call_id=None):
    parsed=WritingOutput.model_validate(output).model_dump(mode='json',exclude_none=True)
    base=snapshot['base_snapshot'];request=snapshot['input'];original=normalize_sections(base)
    expected=[request['target_section']] if request['mode']=='rewrite_section' else list(SECTION_IDS)
    if [s['id'] for s in parsed['sections']]!=expected:
        raise ValueError('Unexpected or missing target sections')
    selected={s['id']:s for s in parsed['sections']};sections=deepcopy(original);facts=numeric_facts(base)
    all_ids=set()
    for section in sections:
        if section['id'] not in selected: continue
        proposed=selected[section['id']]['paragraphs'];old=section['paragraphs']
        if request['mode']=='rewrite_section' and len(proposed)==len(old) and [p['id'] for p in proposed]!=[p['id'] for p in old]:
            raise ValueError('Corresponding rewritten paragraphs must retain stable identities')
        if section['id']=='title' and len(proposed)!=1:
            raise ValueError('Title requires exactly one paragraph')
        if section['id']=='references':
            if any((p['id'],p['text']) not in [(p['id'],p['text']) for p in old] for p in proposed):
                raise ValueError('Frozen references must remain exact')
            continue
        for paragraph in proposed:
            _validate_generated(paragraph,base,old,facts,section['id'])
            previous=next((p for p in [*old,*literature_paragraphs(base)] if p['id']==paragraph['id'] and p['text']==paragraph['text']),None)
            if previous and paragraph['text']==previous['text']:
                paragraph.clear();paragraph.update(deepcopy(previous))
            else: paragraph['origin']='model_generated'
        section['paragraphs']=proposed
    for section in sections:
        for p in section['paragraphs']:
            if p['id'] in all_ids: raise ValueError('Duplicate paragraph identity')
            all_ids.add(p['id'])
    citation_order=list(dict.fromkeys(binding['project_reference_id'] for section in sections if section['id']!='references' for p in section['paragraphs'] for binding in p.get('citations',[]) if 'project_reference_id' in binding))
    cited=set(citation_order)
    references=[deepcopy(r) for r in base.get('references',[]) if r['project_reference_id'] in cited]
    if cited!={r['project_reference_id'] for r in references}: raise ValueError('Citation lacks frozen reference metadata')
    if [r.get('number') for r in references]!=list(range(1,len(references)+1)) or citation_order!=[r['project_reference_id'] for r in references]:
        raise WritingCitationScopeError('Frozen citation numbering must remain contiguous and follow first appearance; a new reviewed citation draft is required')
    frozen_reference_paragraphs=original[6]['paragraphs']
    reference_paragraphs=[deepcopy(p) for p in frozen_reference_paragraphs if p['text'] in {r['text'] for r in references}]
    if request['mode']=='rewrite_section' and request['target_section']!='references' and reference_paragraphs!=sections[6]['paragraphs']:
        raise WritingCitationScopeError('Changing citation coverage requires a full draft; non-target references cannot change')
    sections[6]['paragraphs']=reference_paragraphs
    candidate=deepcopy(base);candidate['sections']=sections;candidate['references']=references
    if candidate.get('review_provenance'):
        # A report about the base cannot certify newly written prose. Keep its
        # exact history, and let this candidate use its own writing provenance.
        candidate.setdefault('review_history',[]).append(dict(
            provenance=candidate.pop('review_provenance'),review=candidate.pop('review'),
            applies_to_current_text=False,status='historical_requires_recheck'))
    candidate['title']=sections[0]['paragraphs'][0]['text']
    if request['mode']=='full_draft':
        candidate['keywords']=deepcopy(request.get('keywords',[]));candidate['acknowledgements']=request.get('acknowledgements','')
    candidate['notice']='Synthetic model candidate; seven SCI sections; scientific content and real model writing remain unverified.' if base.get('output_language')=='en' else '合成模型候选，含SCI七部分；科研内容及真实模型写作效果未经验证。'
    if request['mode']=='full_draft':
        candidate['issues']=[deepcopy(i) for i in base.get('issues',[]) if i.get('id')!='scope']
        if any(i.get('id')=='scope' for i in base.get('issues',[])):
            candidate['issues'].append(dict(id='scope',kind='limitation',field='scope',message=candidate['notice'],values=[]))
    candidate['writing_provenance']=dict(request_id=snapshot['request_id'],task_id=snapshot['request_id'],base_version_id=snapshot['base_version_id'],
        base_revision=request['base_revision'],mode=request['mode'],target_section=request.get('target_section'),
        prompt_version=snapshot.get('prompt_version',PROMPT_VERSION),policy_version=snapshot.get('policy_version',POLICY_VERSION),
        provider_provenance='synthetic_fixture',verification_status='not_verified',model_call_id=model_call_id,input_digest=digest(snapshot))
    return candidate


def validate_candidate(candidate,frozen_snapshot):
    request=frozen_snapshot['input'];targets=[request['target_section']] if request['mode']=='rewrite_section' else list(SECTION_IDS)
    output={'sections':[dict(id=s['id'],paragraphs=[{k:v for k,v in p.items() if k in ('id','text','source_ids','citations','numeric_bindings','origin')} for p in s['paragraphs']]) for s in candidate['sections'] if s['id'] in targets]}
    expected=compose_candidate(output,frozen_snapshot,candidate['writing_provenance'].get('model_call_id'))
    if candidate!=expected: raise ValueError('Candidate modified frozen material or provenance')
    return candidate
