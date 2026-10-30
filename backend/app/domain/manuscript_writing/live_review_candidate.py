"""Deterministic science checks and server-owned citation rendering."""
from copy import deepcopy
import json
from app.domain.literature.service import digest
from app.domain.manuscripts.illustrations import BODY_REFERENCE, check_references, rendered_groups
from .context import NUMBER, WritingCitationScopeError
from .live_notice import COMPOSITION_VERSION, update_notice
from .numeric_review import NUMERIC_VERSION,validation_version,numbers as signed_numbers,value as numeric_value
from .numeric_contract import is_numeric_v2,context_facts

def body_digest(candidate):
    """JSON digest of exact pre-citation prose, including title and abstract."""
    from .school_live import WRITABLE
    return digest([dict(id=s['id'],paragraphs=[dict(id=p['id'],text=p['text']) for p in s['paragraphs']])
                   for s in candidate['sections'] if (s.get('purpose') in WRITABLE if candidate.get('thesis_context') else s['id']!='references')])

def claim_context(request_id,candidate_sha256,paragraph_id):
    return 'writing-v2:'+digest(dict(request_id=request_id,candidate_sha256=candidate_sha256,paragraph_id=paragraph_id))

def target_ids(raw,snapshot):
    from .school_live import WRITABLE
    return {p['id'] for s in raw['sections'] if (s.get('purpose') in WRITABLE if raw.get('thesis_context') else s['id']!='references') and
            (snapshot['input']['mode']=='full_draft' or s['id']==snapshot['input']['target_section']) for p in s['paragraphs']}

def prepare(raw,snapshot,bundle,body,resolve_claim,*,numeric_version=NUMERIC_VERSION):
    strict=validation_version(numeric_version)==NUMERIC_VERSION
    if digest(raw)!=body['candidate_sha256']: raise ValueError('Raw candidate SHA changed')
    from .school_live import is_school,validate_preservation,chapter_language,allowed_sources
    school=is_school(bundle)
    if school:
        if body['schema_version']!=3:raise ValueError('School science requires explicit per-chapter decisions')
        validate_preservation(raw,snapshot['base_snapshot'],bundle)
    elif body['schema_version']!=2:raise ValueError('SCI science requires its frozen request version')
    candidate=deepcopy(raw);targets=target_ids(raw,snapshot)
    decisions={p['paragraph_id']:p for p in body['paragraphs']}
    if len(decisions)!=len(body['paragraphs']) or decisions.keys()!=targets: raise ValueError('Every changed paragraph requires a manual science decision')
    payload=json.loads(json.loads(bundle['wire_json'])['input'])
    facts={s['alias']:{(f['fact_path'],numeric_value(f['value']) if strict else f['value']) for f in s['facts']} for s in payload['sources']}
    contextual=is_numeric_v2(bundle)
    contexts={alias:{(path,numeric_value(value) if strict else value) for path,value in values}
              for alias,values in context_facts(bundle).items()} if contextual else {}
    fragments={}
    for section in candidate['sections']:
        for paragraph in section['paragraphs']:
            pid=paragraph['id']
            if pid not in targets: continue
            decision=decisions[pid]
            if not contextual and (decision['classification']=='context_claim' or any(b['kind']=='context' for b in decision['numeric_bindings'])):
                raise ValueError('Provided-context decisions require the frozen numeric contract')
            text=decision['corrected_text'] if decision['corrected_text'] is not None else paragraph['text']
            if digest(text)!=decision['text_sha256']: raise ValueError('Decision does not bind exact corrected text')
            paragraph['text']=text
            literature=decision['classification'] in ('literature_claim','mixed_claim')
            if literature!=(decision['claim'] is not None): raise ValueError('Literature classification requires a new exact claim')
            fragment=resolve_claim(decision,text) if literature else dict(kind='text',text=text)
            if fragment['text']!=text: raise ValueError('Claim differs from exact paragraph text')
            fragments[pid]=[fragment]
            issues=check_references(rendered_groups(snapshot['base_snapshot'],[dict(id=pid,text=text,origin='model_generated')]),chapter_language(candidate,pid) if school else candidate['output_language'])
            if any(i['field']==pid for i in issues): raise ValueError('Unknown figure or table')
            numbers=(signed_numbers if strict else NUMBER.findall)(BODY_REFERENCE.sub('',text));bindings=decision['numeric_bindings']
            if sorted(b['occurrence'] for b in bindings)!=list(range(len(numbers))): raise ValueError('Every numeric occurrence must be classified exactly once')
            for bound in bindings:
                value=numeric_value(bound['value']) if strict else bound['value']
                if numbers[bound['occurrence']]!=value: raise ValueError('Numeric text mismatch')
                if bound['kind']=='study':
                    if decision['classification'] not in ('study_claim','mixed_claim','context_claim') or bound['evidence_id'] is not None or (bound['fact_path'],value) not in facts.get(bound['source_alias'],set()): raise ValueError('Study number lacks an exact frozen fact')
                    if school and bound['source_alias'] not in allowed_sources(candidate,bundle['local_manifest'],section):raise ValueError('Study number belongs to another school chapter')
                elif bound['kind']=='context':
                    if decision['classification'] not in ('context_claim','mixed_claim') or bound['evidence_id'] is not None or (bound['fact_path'],value) not in contexts.get(bound['source_alias'],set()): raise ValueError('Context number lacks an explicit exact frozen-context decision')
                    if school:
                        frozen_chapter=next(c for c in bundle['local_manifest']['school']['chapters'].values() if c['chapter_id']==section['id'])
                        if bound['source_alias'] not in frozen_chapter['allowed_context_aliases']:raise ValueError('Context belongs to another school chapter')
                elif bound['kind']=='literature':
                    evidence=[e for b in fragment.get('bindings',[]) for e in b['evidence'] if e['id']==bound['evidence_id']]
                    if not literature or bound['source_alias'] is not None or bound['fact_path'] is not None or not evidence or value not in (signed_numbers if strict else NUMBER.findall)(evidence[0]['quote']): raise ValueError('Literature number lacks exact new-claim reviewed evidence')
                else:
                    raise ValueError('Unknown numeric decision kind')
            paragraph.update(verification_status='scientific_reviewed',numeric_bindings=deepcopy(bindings),
                citations=deepcopy(fragment.get('bindings',[])),science_review=dict(classification=decision['classification'],basis=decision['scientific_basis'],text_sha256=digest(text)),
                source_ids=list(dict.fromkeys(bundle['local_manifest']['sources'][b['source_alias']] for b in bindings if b['kind']=='study')))
    if body_digest(candidate)!=body['consistency']['body_sha256']: raise ValueError('Title and abstract decisions bind a different body')
    if school:
        abstracts={s['id'] for s in candidate['sections'] if s['purpose']=='abstract'}
        if set(body['consistency']['abstracts'])!=abstracts:raise ValueError('Every school abstract requires an exact consistency decision')
        approvals=[body['consistency']['title'],*body['consistency']['abstracts'].values()]
    else:approvals=[body['consistency'][name] for name in ('title','abstract')]
    for checks in approvals:
        if not checks['basis'].strip() or any(v is not True for k,v in checks.items() if k!='basis'): raise ValueError('Explicit title/abstract consistency approval required')
    if not school:candidate['title']=candidate['sections'][0]['paragraphs'][0]['text']
    return candidate,fragments

def citation_body(candidate,fragments):
    """Retain untouched bindings; refuse any non-target rendering ambiguity."""
    old=candidate.get('citation_snapshot') or {}
    old_paragraphs={p['id']:p for p in old.get('paragraphs',[])}
    paragraphs=[];mapping={}
    for s in candidate['sections']:
        if s.get('purpose',s['id'])=='references': continue
        for p in s['paragraphs']:
            pid=p['id'];parts=fragments.get(pid)
            if parts is None and p.get('citations'):
                prior=old_paragraphs.get(pid.removeprefix('literature:')) or old_paragraphs.get('p_'+digest(pid))
                if prior is None: raise WritingCitationScopeError('Unmapped preserved citation; process full manuscript')
                parts=deepcopy(prior['fragments'])
            if not parts or not any(f['kind']=='claim' for f in parts): continue
            stable='p_'+digest(pid);mapping[stable]=pid
            paragraphs.append(dict(id=stable,fragments=[dict(kind='text',text=f['text']) if f['kind']=='text' else
                dict(kind='claim',claim_id=f['claim_id'],claim_revision=f['claim_revision'],bindings=[{k:b[k] for k in ('review_id','metadata_version_id')} for b in f['bindings']]) for f in parts]))
    return dict(title=candidate['title'],output_language=candidate['output_language'],format='nlm_numeric_journal_v1',paragraphs=paragraphs),mapping

def finish(candidate,raw,snapshot,body,citation,mapping,review_id,*,numeric_version=NUMERIC_VERSION,school_bundle=None,inherited_context=None):
    candidate=deepcopy(candidate)
    if citation:
        outputs={mapping[p['id']]:p['text'] for p in citation['output']['paragraphs']}
        bindings={mapping[p['id']]:[deepcopy(b) for f in p['fragments'] if f['kind']=='claim' for b in f['bindings']] for p in citation['paragraphs']}
        for s in candidate['sections']:
            for p in s['paragraphs']:
                if p['id'] in outputs: p.update(text=outputs[p['id']],citations=bindings[p['id']])
    references=deepcopy(citation['output']['references']) if citation else []
    candidate.update(citation_snapshot=deepcopy(citation),references=references)
    school=bool(candidate.get('thesis_context'))
    reference=next((s for s in candidate['sections'] if s.get('purpose')=='references'),None) if school else candidate['sections'][-1]
    if reference is None and references:raise ValueError('Cited literature requires a confirmed references chapter')
    if reference is not None:reference['paragraphs']=[dict(id='reference:'+str(r['number']),text=r['text'],origin='literature',source_ids=[],citations=[]) for r in references]
    if snapshot['input']['mode']=='rewrite_section':
        target=snapshot['input']['target_section']
        if any(s!=old for s,old in zip(candidate['sections'],raw['sections']) if s['id']!=target) or references!=raw['references']: raise WritingCitationScopeError('Citation or non-target changes require full manuscript processing')
    if not school:candidate['title']=candidate['sections'][0]['paragraphs'][0]['text']
    if not candidate['title'].strip() or len(candidate['title'])>200: raise ValueError('Reviewed title exceeds immutable manuscript contract')
    candidate['writing_provenance'].update(review_id=review_id,raw_candidate_sha256=digest(raw),verification_status='scientific_reviewed_language_pending')
    if school:
        from .school_live import update_notice as school_notice
        from app.domain.manuscripts.school import school_content_report
        school_notice(candidate,snapshot['input'],reviewed=True)
        if school_bundle:
            from .school_live import science_report
            candidate['school_content_report']=science_report(candidate,school_bundle,body,raw,inherited_context)
        else:candidate['school_content_report']=school_content_report(candidate)
    elif raw['writing_provenance'].get('composition_version')==COMPOSITION_VERSION:update_notice(candidate,snapshot['input'],reviewed=True)
    report=dict(schema_version=3 if school else 2,review_kind='explicit_human_scientific',raw_candidate_sha256=digest(raw),
        body_sha256=body['consistency']['body_sha256'],decisions=deepcopy(body['paragraphs']),consistency=deepcopy(body['consistency']),
        citation_paragraph_mapping=mapping,language_status='pending',non_target_sections_preserved=True)
    if validation_version(numeric_version)==NUMERIC_VERSION:report['numeric_validation_version']=NUMERIC_VERSION
    return candidate,report
