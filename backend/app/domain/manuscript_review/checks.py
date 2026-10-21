"""Local syntactic consistency, never semantic or scientific verification."""
from collections import Counter
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from app.domain.manuscripts.illustrations import check_references, rendered_groups, BODY_REFERENCE
from app.domain.manuscript_writing.context import NUMBER
from .contracts import RULES_VERSION
from .facts import extract_facts, displayed_paragraphs

METRIC_LABELS={'mean':'mean','均值':'mean','median':'median','中位数':'median',
               'n':'n','样本量':'n','std':'std','sd':'std','标准差':'std',
               'min':'min','最小值':'min','max':'max','最大值':'max','p':'p_value','p值':'p_value'}
METRIC_PREFIX=re.compile(r'(?<![A-Za-z])('+'|'.join(METRIC_LABELS)+r')\s*[=:：]?\s*$',re.I)

def issue(category,location,message,*,severity='human_review',actual=None,expected=None,evidence=(),suffix=''):
    return dict(id=category+':'+location+(':'+suffix if suffix else ''),category=category,severity=severity,location=location,message=message,actual=actual,expected=expected,source_evidence=list(evidence),rules_version=RULES_VERSION)


def check_snapshot(snapshot,metadata=(),strict_locations=(),*,writing_context=None):
    issues=[];facts={f['id']:f for f in extract_facts(snapshot)}
    sources={s['id']:s for s in snapshot.get('sources',[])}
    meta={(m['target_id'],m['field']):m for m in metadata}
    paragraphs=displayed_paragraphs(snapshot)
    ids=[p['id'] for _,p in paragraphs]
    if len(ids)!=len(set(ids)):
        issues.append(issue('structure','manuscript','Duplicate displayed paragraph identities.',severity='error',actual=ids))
    if 'sections' in snapshot:
        from app.domain.manuscript_writing.contracts import SECTION_IDS
        actual=[s['id'] for s in snapshot['sections']]
        if actual!=list(SECTION_IDS): issues.append(issue('structure','sections','Unexpected section structure.',severity='error',actual=actual,expected=list(SECTION_IDS)))
        for section in snapshot['sections']:
            if not section['paragraphs']:
                issues.append(issue('structure','section:'+section['id'],'Section is empty; material requires human review.'))
    else: issues.append(issue('structure','sections','Historical two-section fact draft; complete manuscript structure has not been supplied.'))

    def numbers(location,text,bindings,source_ids,strict=False,literature=()):
        clean=BODY_REFERENCE.sub('',text)
        # Reference markers are checked independently; never treat them as facts.
        clean=re.sub(r'\[\d+(?:\s*[,–-]\s*\d+)*\]','',clean)
        tokens=NUMBER.findall(clean)
        occurrences=list(NUMBER.finditer(clean))
        bound=[]
        for index,binding in enumerate(bindings):
            if binding in literature:
                bound.append(binding['value'])
                continue
            fact=facts.get(binding.get('fact_id'));value=binding.get('value')
            legacy=(not strict and 'fact_id' not in binding and binding.get('source_id') in source_ids
                    and any(f['source_id']==binding['source_id'] and f['value']==value for f in facts.values()))
            if legacy:
                issues.append(issue('numeric',location,'Historical source-level binding is preserved; exact metric-path association still requires human review.',actual=binding,expected='explicit fact_id',suffix='legacy:'+str(index)))
                bound.append(value)
                continue
            valid=bool(fact and fact['source_id'] in source_ids)
            expected=fact['value'] if fact else 'exact source and leaf fact_id'
            if valid:
                precision=meta.get((fact['id'],'display_precision'))
                if precision and precision.get('evidence','').strip():
                    try: expected=format(Decimal(fact['value']).quantize(Decimal(1).scaleb(-int(precision['value'])),rounding=ROUND_HALF_UP),'f')
                    except (ValueError,InvalidOperation): valid=False
                valid=valid and value==expected
                # Only explicit adjacent metric labels are checked. Ambiguous
                # prose still requires human review, never guessed semantics.
                if index<len(occurrences):
                    named=METRIC_PREFIX.search(clean[:occurrences[index].start()])
                    if named:
                        named_metric=METRIC_LABELS[named[1].lower()]
                        path_parts=fact['path'].split('/')
                        metric=path_parts[-2] if path_parts[-1]=='value' else path_parts[-1]
                        if named_metric!=metric:
                            valid=False;expected=dict(metric=named_metric,fact_path=fact['path'])
            if not valid:
                issues.append(issue('numeric',location,'Numeric binding must match its exact saved metric and explicit display precision.',severity='error',actual=binding,expected=expected,evidence=[fact] if fact else [],suffix=str(index)))
            if isinstance(value,str): bound.append(value)
        if bindings:
            exact=any('fact_id' in binding for binding in bindings) or strict
            mismatch=tokens!=bound if exact else Counter(tokens)!=Counter(bound)
            if mismatch:
                issues.append(issue('numeric',location,'Each displayed numerical occurrence must match the binding at the same position; exact fact bindings follow text order.',severity='error',actual=tokens,expected=bound,suffix='coverage'))
        elif tokens:
            # Legacy source-level bindings cannot identify an exact metric. They
            # remain visibly unverified; changed/new text requires explicit IDs.
            issues.append(issue('numeric',location,'Numerical text has no exact metric-path bindings; verify the displayed values against saved facts.',severity='error' if strict else 'human_review',actual=tokens,expected='fact_id per numeric token',evidence=[f for f in facts.values() if f['source_id'] in source_ids],suffix='unbound'))
        for binding in bindings:
            fact=facts.get(binding.get('fact_id'))
            if not fact: continue
            unit=meta.get((fact['id'],'unit'))
            if unit and unit['value'] not in text:
                issues.append(issue('unit',location,'Confirmed unit is absent from displayed text; no unit conversion is performed.',actual=text,expected=unit['value'],evidence=[unit],suffix=fact['id']))

    for section,p in paragraphs:
        if section=='title': continue
        unknown=set(p.get('source_ids',[]))-set(sources)
        if unknown: issues.append(issue('source',p['id'],'Paragraph references unknown frozen sources.',severity='error',actual=sorted(unknown)))
        if writing_context and p['id'] in writing_context.paragraphs and p['id'] not in strict_locations:
            try:
                text,bindings,literature=writing_context.paragraph(p,sources)
                numbers(p['id'],text,bindings,p.get('source_ids',[]),True,literature)
            except (ValueError,KeyError,TypeError):
                issues.append(issue('numeric',p['id'],'Displayed v2 paragraph, occurrence order or source differs from its exact reconstructed scientific artifact.',severity='error'))
        else:
            numbers(p['id'],p['text'],p.get('numeric_bindings',[]),p.get('source_ids',[]),p['id'] in strict_locations)
        issues.append(issue('uncertainty',p['id'],'Free prose meaning, claims and source support require researcher review; local checks do not establish scientific correctness.',actual=p['text'],expected='human review'))
        for field in ('acronym','object','group','statistical_mark','error_bar','unit'):
            supplied=meta.get((p['id'],field))
            if supplied and supplied['value'] not in p['text']:
                issues.append(issue('unit' if field=='unit' else 'terminology',p['id'],'Confirmed '+field+' differs from displayed terminology.',actual=p['text'],expected=supplied['value'],evidence=[supplied],suffix=field))

    groups=rendered_groups(snapshot,[p for _,p in paragraphs])
    for item in check_references(groups,snapshot['output_language']):
        recorded=any(i.get('id')==item['id'] and i.get('values',[])==item['values'] for i in snapshot.get('issues',[]))
        severity='human_review' if recorded and item['field'] not in strict_locations else 'error'
        issues.append(issue('illustration',item['field'],item['message'],severity=severity,actual=item['values'],expected='saved figure/table/panel identity',suffix=item['id']))
    for group_index,group in enumerate(snapshot.get('results_groups',[])):
        for figure in group.get('figures',[]):
            location='caption:'+figure['id']
            if figure.get('caption_status') in (None,'missing','candidate') or not figure.get('caption','').strip():
                issues.append(issue('caption',location,'Caption is missing or remains an unconfirmed source candidate.',actual=figure.get('caption'),expected='explicit supplied caption and evidence'))
            numbers(location,figure.get('caption',''),figure.get('numeric_bindings',[]),figure.get('source_ids',[]),location in strict_locations)
            for index,panel in enumerate(figure.get('panels',[])):
                numbers(f'panel:{figure["id"]}:{index}',panel['description'],panel.get('numeric_bindings',[]),figure.get('source_ids',[]))
        for table_index,table in enumerate(group.get('tables',[])):
            from app.domain.manuscripts.draft import flat_values
            expected=[];rows=table.get('rows');language=snapshot['output_language'];bound_table=True
            if writing_context:
                try: rows,language=writing_context.table(f'/results_groups/{group_index}/tables/{table_index}',table,sources)
                except (ValueError,KeyError,TypeError): bound_table=False
            for sid in table.get('source_ids',[]):
                source=sources.get(sid,{})
                if source.get('kind')=='analysis_run':
                    content=source['content'];expected+=list(flat_values({k:content[k] for k in ('check','overall','groups','statistics','variables') if k in content},en=language=='en'))
            if not bound_table or rows!=expected:
                issues.append(issue('numeric','table:'+table['id'],'Displayed table differs from exact frozen source rows; equal values from another metric cannot substitute.',severity='error',actual=table.get('rows'),expected=expected,evidence=table.get('source_ids',[])))

    refs=snapshot.get('references',[])
    if [r.get('number') for r in refs]!=list(range(1,len(refs)+1)):
        issues.append(issue('reference','references','Reference numbering is not contiguous.',severity='error',actual=[r.get('number') for r in refs]))
    by_ref={r.get('project_reference_id'):r for r in refs};order=[]
    citation=snapshot.get('citation_snapshot') or {}
    supported=[b for p in citation.get('paragraphs',[]) for f in p.get('fragments',[]) if f.get('kind')=='claim' for b in f.get('bindings',[])]
    figure_texts=[]
    for group in snapshot.get('results_groups',[]):
        for figure in group.get('figures',[]):
            figure_texts.append(dict(id='caption:'+figure['id'],text=figure.get('caption',''),citations=figure.get('citations',[])))
            figure_texts.extend(dict(id=f'panel:{figure["id"]}:{index}',text=panel['description'],citations=panel.get('citations',[])) for index,panel in enumerate(figure.get('panels',[])))
    # Match actual export order, including captions/panels placed immediately
    # after the results text, rather than treating them as non-prose metadata.
    reference_texts=[]
    if 'sections' in snapshot:
        for section in snapshot['sections']:
            if section['id']!='references': reference_texts.extend(section['paragraphs'])
            if section['id']=='results': reference_texts.extend(figure_texts)
    else:
        reference_texts=[p for section,p in paragraphs if section=='results']+figure_texts+[p for section,p in paragraphs if section!='results']
    for p in reference_texts:
        for binding in p.get('citations',[]):
            rid=binding.get('project_reference_id')
            if binding not in supported or rid not in by_ref:
                issues.append(issue('reference',p['id'],'Citation lacks its exact saved support review and reference metadata.',severity='error',actual=binding))
            if rid not in order: order.append(rid)
        markers=[]
        for group in re.findall(r'\[(\d+(?:\s*[,–-]\s*\d+)*)\]',p['text']):
            for part in group.split(','):
                bounds=re.split('[–-]',part)
                start=int(bounds[0]);end=int(bounds[-1])
                if len(bounds)==1: markers.append(start)
                elif start<=end and end-start<=len(refs):
                    markers.extend(range(start,end+1))
                else:
                    # Invalid/oversized ranges are a hard marker failure,
                    # without expanding arbitrarily large user integers.
                    markers.extend([start,end,0])
        allowed={by_ref[b['project_reference_id']]['number'] for b in p.get('citations',[]) if b.get('project_reference_id') in by_ref}
        if markers and not set(markers)<=allowed and not (p.get('origin')=='literature' and p['id'].startswith('literature:')):
            issues.append(issue('reference',p['id'],'Displayed reference marker has no exact supported binding.',severity='error',actual=markers,expected=sorted(allowed),suffix='markers'))
    if order and order!=[r.get('project_reference_id') for r in refs]:
        issues.append(issue('reference','references','Reference order must follow first appearance and preserved support coverage.',severity='error',actual=order,expected=[r.get('project_reference_id') for r in refs]))
    return issues
