"""Compose a review candidate without mutating its base or scientific provenance."""
from copy import deepcopy
from app.domain.literature.service import digest
from app.domain.manuscripts.contracts import METHOD_FIELDS
from .contracts import RULES_VERSION, ReviewRequest
from .facts import extract_facts, relationships, displayed_paragraphs
from .checks import check_snapshot, issue
from .impacts import affected_locations
from .writing_context import has_review_edits,V2_WORKFLOW_MESSAGE


def compose(frozen,*,writing_context=None):
    request=ReviewRequest.model_validate(frozen['input']).model_dump(mode='json')
    if frozen.get('writing_check_version') in (1,2) and (writing_context is None or has_review_edits(request)):
        raise ValueError(V2_WORKFLOW_MESSAGE)
    base=frozen['base_snapshot'];candidate=deepcopy(base)
    previous=base.get('review') or (base.get('review_history') or [{}])[-1].get('review',{})
    paragraphs={p['id']:(section,p) for section,p in displayed_paragraphs(candidate)}
    figures={f['id']:f for g in candidate['results_groups'] for f in g['figures']}
    facts=extract_facts(base);source_ids={s['id'] for s in base['sources']}
    targets=set(paragraphs)|set(figures)|source_ids|{f['id'] for f in facts}
    for metadata in request['metadata']:
        if metadata['target_id'] not in targets: raise ValueError('Metadata target is not frozen in the base')
        if metadata['field']=='display_precision' and metadata['target_id'] not in {f['id'] for f in facts}: raise ValueError('Display precision requires exact fact_id')
    for association in request['associations']:
        if (not set(association['paragraph_ids'])<=set(paragraphs) or not set(association['method_ids'])<={k for k,(s,p) in paragraphs.items() if s=='materials_and_methods'}
            or not set(association['figure_ids'])<=set(figures) or not set(association['source_ids'])<=source_ids): raise ValueError('Association target outside frozen base')
    inherited_metadata=deepcopy(previous.get('metadata',[]))
    changed_ids={c['id'] for c in frozen['source_state']['changes']}
    for item in inherited_metadata:
        affected=item['target_id'] in changed_ids or any(f['id']==item['target_id'] and f['source_id'] in changed_ids for f in facts)
        if affected: item['stale']=True
    new_keys={(m['target_id'],m['field']) for m in request['metadata']}
    metadata=[m for m in inherited_metadata if (m['target_id'],m['field']) not in new_keys]
    metadata += [deepcopy(m)|dict(created_by=frozen['created_by'],created_at=frozen['created_at'],base_version_id=frozen['base_version_id'],stale=False) for m in request['metadata']]
    new_associations={a['id'] for a in request['associations']}
    associations=[deepcopy(a) for a in previous.get('relationships',{}).get('associations',[]) if a['id'] not in new_associations]+deepcopy(request['associations'])
    strict=[]
    for correction in request['corrections']:
        target=paragraphs.get(correction['paragraph_id'])
        if not target or target[0] in ('title','references'): raise ValueError('Correction must target an editable displayed paragraph')
        paragraph=target[1]
        if paragraph.get('citations') or paragraph.get('origin')=='literature': raise ValueError('Literature prose requires renewed citation support review')
        if not set(correction['source_ids'])<=source_ids: raise ValueError('Correction source not in frozen base')
        paragraph.update(text=correction['text'],source_ids=correction['source_ids'],numeric_bindings=correction['numeric_bindings'],origin='user_provided')
        strict.append(paragraph['id'])
    records=deepcopy(previous.get('decisions',[]));addendum=deepcopy(previous.get('addendum',[]));resolved=set()
    original_issues={i['id']:i for i in base['issues']}
    for decision in request['decisions']:
        target=decision['target_id']
        if target not in original_issues and not (target.startswith('caption:') and target[8:] in figures): raise ValueError('Decision target is not a frozen issue/caption')
        if decision['status']=='selected' and target.startswith('conflict:') and decision['value'] not in original_issues[target].get('values',[]):
            raise ValueError('Selected value must match an original conflicting record; use supplied for new evidence')
        record=deepcopy(decision)|dict(created_by=frozen['created_by'],created_at=frozen['created_at'],base_version_id=frozen['base_version_id'],base_revision=request['base_revision'],source_versions=[dict(id=s['id'],kind=s['kind'],sha256=s['sha256']) for s in base['sources']],scientifically_verified=False)
        records.append(record)
        if decision['status'] not in ('supplied','selected'): continue
        field=target.split(':',1)[-1]
        if target.startswith(('missing:','conflict:')) and field in METHOD_FIELDS:
            p=dict(id='confirmed:'+frozen['review_id']+':'+field,text=('Confirmed material (user provided; not scientific verification): ' if base['output_language']=='en' else '确认资料（用户提供，未经科研验证）：')+field+' — '+decision['value'],origin='user_provided',source_ids=[],citations=[],numeric_bindings=[])
            if 'sections' in candidate:
                method_section=next((s for s in candidate['sections'] if s.get('purpose',s['id'])=='materials_and_methods'),None)
                if method_section is None: raise ValueError('Map a school methods chapter before supplying method content')
                method_section['paragraphs'].append(p)
            else: candidate['methods'].append(p)
            # Explicit method records (approval IDs, dates, dosages, sample
            # declarations) remain user-provided, never computed facts. Their
            # numbers require human checking; image/statistical conclusions
            # are not accepted through this method-only route.
            resolved.add(target)
        elif target.startswith(('caption:','missing:caption:','verify:caption:')):
            figure_id=target.split('caption:',1)[1]
            if figure_id not in figures: raise ValueError('Caption target is not in frozen figures')
            figure=figures[figure_id];figure.update(caption=decision['value'],caption_status='supplied',caption_origin='user_provided')
            strict.append('caption:'+figure_id);resolved.update({'missing:caption:'+figure_id,'verify:caption:'+figure_id})
    # Original historical issues are retained verbatim in the immutable base.
    # A supplied correction resolves only its precise missing/conflicting field;
    # pending/NA declarations cannot waive hard checks.
    candidate['issues']=[i for i in candidate['issues'] if i['id'] not in resolved]
    for source in frozen['selected_sources']:
        addendum.append(dict(id='new-material:'+source['id'],text=('Explicitly selected newer material; impact pending review/rewrite: ' if base['output_language']=='en' else '用户显式选择的新资料，影响待核对或重写：')+source['label'],origin='user_provided',source_ids=[source['id']],citations=[],numeric_bindings=[],pending_impact=True))
    relations=relationships(candidate,associations)
    checks=check_snapshot(candidate,metadata,strict,writing_context=writing_context)
    if frozen.get('writing_check_version') in (1,2):
        checks.append(issue('workflow','v2_scientific_language_review',V2_WORKFLOW_MESSAGE,severity='error',expected='v2 scientific and language review workspace'))
    for item in metadata:
        if item.get('stale'):
            checks.append(issue('material',item['target_id'],'Previously confirmed metadata applies only to its original frozen fact; changed material requires renewed confirmation.',actual=item,expected='reconfirm against explicitly selected new source',suffix=item['field']))
    for original in candidate['issues']:
        checks.append(issue('material',original['id'],original['message'],actual=original.get('values',[]),expected='targeted material correction'))
    for change in frozen['source_state']['changes']:
        hard=(any(reason in ('source_changed','source_unavailable_or_changed') for reason in change['reasons'])
              or change.get('kind')=='citation_draft' and bool(frozen['source_state'].get('citation_integrity_changes')))
        checks.append(issue('source',change['id'],'Source changed; existing prose and numerical bindings remain frozen. Review affected locations before rewriting.',severity='error' if hard else 'human_review',actual=change['reasons']))
    report=dict(rules_version=RULES_VERSION,issues=checks,can_publish=not any(i['severity']=='error' for i in checks),scientifically_verified=False,source_changes=deepcopy(frozen['source_state']['changes']),impacts=affected_locations(frozen['source_state']['changes'],relations))
    selected_sources=deepcopy(previous.get('selected_sources',[]))+deepcopy(frozen['selected_sources'])
    candidate['review']=dict(facts=facts,selected_facts=extract_facts(dict(sources=selected_sources)),relationships=relations,decisions=records,metadata=metadata,report=report,addendum=addendum,selected_sources=selected_sources)
    candidate['review_provenance']=dict(review_id=frozen['review_id'],base_version_id=frozen['base_version_id'],base_revision=request['base_revision'],input_sha256=digest(frozen),rules_version=RULES_VERSION,created_by=frozen['created_by'],created_at=frozen['created_at'],verification_status='not_verified')
    if candidate.get('thesis_context'):
        from app.domain.manuscripts.school import school_content_report
        candidate['school_content_report']=school_content_report(candidate)
    return candidate,report
