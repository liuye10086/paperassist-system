"""Finite local operations consuming frozen prose and evidence, never free generation."""
from copy import deepcopy
import re
from app.domain.literature.service import digest
from app.domain.manuscript_writing.context import normalize_sections,literature_paragraphs
from app.domain.manuscript_review.checks import issue
from .planning import invalid


def evidence_for(snapshot,materials):
    values=[]
    for source in [*snapshot.get('sources',[]),*materials]:
        if source['id'] in {v['id'] for v in values}:continue
        values.append(dict(id=source['id'],kind=source['kind'],sha256=digest(source),content=deepcopy(source.get('content',source))))
    return values


def locations_for(snapshot):
    locations=[]
    for section in normalize_sections(snapshot):
        title=section.get('title') or section.get('display_name') or section['id']
        locations.append(dict(kind='section',id=section['id'],section_id=section['id'],section_title=title,text='\n'.join(p['text'] for p in section['paragraphs'])))
        locations.extend(dict(kind='paragraph',id=p['id'],section_id=section['id'],section_title=title,text=p['text']) for p in section['paragraphs'])
    for group in snapshot.get('results_groups',[]):
        for kind in ('figure','table'):
            locations.extend(dict(kind=kind,id=f['id'],section_id=group['id'],section_title=group.get('title',group['id']),text=f.get('caption') or f.get('title','')) for f in group.get(kind+'s',[]))
    return locations


def evidence_summary(entry):
    """Describe finite known facts/text, never stringify IDs or parser metadata."""
    content=entry['content'];parts=[]
    if entry['kind']=='analysis_run':
        for key in ('numeric_name','group_name','unit'):
            if content.get(key):parts.append(key+'='+str(content[key]))
        for name in ('overall','statistics'):
            value=content.get(name,{})
            if isinstance(value,dict):
                facts=[key+'='+str(value[key]) for key in ('n','mean','std','median','min','max','p_value') if key in value]
                if facts:parts.append(name+': '+', '.join(facts))
        for group in content.get('groups',[])[:8]:
            facts=group.get('statistics',{})
            if isinstance(facts,dict):parts.append('group '+str(group.get('label',''))+': '+', '.join(k+'='+str(facts[k]) for k in ('n','mean','std','median') if k in facts))
        if not content.get('unit'):parts.append('单位未提供，保持待核，不推断换算。')
    else:
        def texts(value,depth=0):
            if depth>6:return
            if isinstance(value,dict):
                for key,child in value.items():
                    if key in ('text','normalized_text','claim_text','caption','description','title') and isinstance(child,str) and child.strip():yield child.strip()
                    elif isinstance(child,(dict,list)):yield from texts(child,depth+1)
            elif isinstance(value,list):
                for child in value:yield from texts(child,depth+1)
        parts=list(dict.fromkeys(texts(content)))[:8]
    return '；'.join(parts)[:3000] if parts else '固定资料未提供可用于本项的明确文本/统计字段；需人工核对原材料。'


def grounded_plans(snapshot,items,materials):
    locations=locations_for(snapshot);evidence=evidence_for(snapshot,materials);result=[]
    sections=normalize_sections(snapshot)
    roles={'method':'materials_and_methods','statistics':'results','expression':'discussion','structure':'materials_and_methods'}
    for item in items:
        selected=[loc for loc in locations if loc['id'] in {x['id'] for x in item['locations']}]
        if not selected and item['category']=='figure':selected=[loc for loc in locations if loc['kind'] in ('figure','table')][:2]
        role=roles.get(item['category'],'materials_and_methods')
        section_ids={s['id'] for s in sections if s.get('purpose',s['id'])==role}
        if not selected:selected=[loc for loc in locations if loc['kind']=='paragraph' and loc['section_id'] in section_ids][:2]
        if not selected:selected=[loc for loc in locations if loc['kind']=='paragraph'][:2]
        selected_sources={sid for section in sections for paragraph in section['paragraphs'] if paragraph['id'] in {loc['id'] for loc in selected} for sid in paragraph.get('source_ids',[])}
        used=[e for e in evidence if e['id'] in set(item['evidence_ids'])|selected_sources] or evidence[:3]
        excerpts=[dict(e,summary=evidence_summary(e)) for e in used]
        existing='\n'.join(loc['text'] for loc in selected)
        missing=[n['description'] for n in item['needs']]
        if not selected:missing.append('固定稿件没有可定位段落，需补明确位置。')
        if not used:missing.append('没有可反查既有材料，不自动生成新事实。')
        summary='\n'.join(e['id']+'：'+e['summary'] for e in excerpts)
        positions='；'.join(loc['section_title']+'/'+loc['id'] for loc in selected)
        specific='按上述现文提供明确替换文本，逐句保留已有事实、引用及局限性。'
        if item['category'] in ('statistics','method'):
            specific='以列出的固定变量和统计记录核对 '+positions+' 中的样本口径及方法说明；已有结果保持原值，明确采用新分析时使用其公共事实ID及逐值绑定更新所有受影响段落，缺失单位或结果继续待核，不推断。'
        elif item['category']=='structure':
            order='；'.join(s['id']+': '+', '.join(p['id'] for p in s['paragraphs']) for s in sections if s['id'] in {loc['section_id'] for loc in selected})
            specific='当前段落顺序 '+order+'。可对上述现文按空行拆段或明确重排完整段落ID列表；数值和核验引用保持原绑定。'
        elif item['category']=='figure':specific='核对 '+positions+' 当前图注「'+existing+'」与列出的图表/统计资料；只提交已有单位和对象支持的具体图注，未知误差线/实验信息列待补。'
        elif item['category']=='literature':specific='固定稿含 '+str(len(snapshot.get('references',[])))+' 条参考记录。仅可将已经核验的原陈述及其支持绑定原样采用；新陈述/新文献支持仍待核验。'
        elif item['category']=='experiment':specific='独立实验没有在本批执行。列明原意见中的实验要求并等待可验证材料；不能生成实验完成或新增结果表述。'
        elif item['category']=='format':specific='保留固定章节与身份映射，使用本轮选定学校确认/期刊指南检查上述实际候选；只执行明确支持的章名显示调整。'
        plan=f"意见：{item['original_text'].strip()}\n固定位置：{positions}\n固定现文：{existing}\n已读取具体资料：{summary}\n具体处理：{specific}\n缺口：{'；'.join(missing) if missing else '尚需用户提供具体改文；语义与科研合理性仍需人工核验。'}"
        result.append(dict(item_id=item['id'],original_text=item['original_text'],existing_content=existing,locations=selected,evidence=excerpts,plan=plan,missing=missing))
    return result


def apply_operations(snapshot,items,materials,operations,*,writing_context=None,target=None):
    candidate=deepcopy(snapshot);candidate['sections']=normalize_sections(snapshot)
    candidate.pop('user_return_provenance',None)
    if candidate.get('review_provenance'):
        candidate.setdefault('review_history',[]).append(dict(provenance=candidate.pop('review_provenance'),review=candidate.pop('review'),applies_to_current_text=False,status='historical_requires_recheck'))
    locations={loc['id']:loc for loc in locations_for(snapshot)};item_map={i['id']:i for i in items}
    evidence={e['id']:e for e in evidence_for(snapshot,materials)};changes=[];unexecuted=[];issues=[];strict=[];seen=set()
    for op in operations:
        op=op.model_dump() if hasattr(op,'model_dump') else op
        item=item_map.get(op['item_id']);loc=locations.get(op['location_id'])
        if not item or not loc:raise invalid('具体操作必须属于本轮意见和固定稿件位置。')
        if op['location_id'] in seen:raise invalid('同一位置一次只能提交一个明确操作。')
        seen.add(op['location_id'])
        if not set(op['evidence_ids'])<=set(evidence):raise invalid('依据必须来自固定资料版本。')
        reason=None
        if item['category']=='experiment' or re.search(r'\bexperiments?\b|实验|试验',item['original_text'],re.I):reason='实验事项需提供真实独立实验材料，不能用文字采用完成。'
        elif item['needs']:reason='；'.join(n['description'] for n in item['needs'])
        elif item.get('decision',{} ) and item['decision']['action'] in ('not_adopt','defer'):reason=item['decision']['reason'] or '用户未采纳/延期。'
        elif item['flags'] and (not item.get('decision') or item['decision']['action'] not in ('accept','clarify')):reason='重要决定尚未确认。'
        elif 'conclusion_change' in item['flags']:reason='结论变化须提供可核验科学审核；本批具体改文不能把相关改为因果。'
        elif not op['evidence_ids']:reason='缺少固定材料依据。'
        text=(op.get('text') or '').strip()
        if not reason and re.search(r'\b(?:cause[ds]?|causal(?:ity)?|causation|proves?)\b|导致|因果|实验已完成|experiment.{0,20}completed',text,re.I) and text!=loc['text']:reason='新增因果或实验完成表述没有独立科学执行依据。'
        if reason:
            unexecuted.append(dict(item_id=item['id'],reason=reason,status='waiting_material' if item['needs'] or '依据' in reason else item['status']));continue
        before=None;after=None;additional_evidence=[]
        section=next((s for s in candidate['sections'] if s['id']==loc['section_id']),None)
        paragraph=next((p for s in candidate['sections'] for p in s['paragraphs'] if p['id']==op['location_id']),None)
        if op['kind'] in ('replace_paragraph','split_paragraph','bind_citation'):
            if loc['kind']!='paragraph' or not paragraph or section.get('purpose',section['id']) in ('manual','references','title'):raise invalid('请选择可修改的正文段落；固定标题、身份章节和参考表不可自由替换。')
            before=paragraph['text']
            if op['kind']=='bind_citation':
                saved=next((p for p in literature_paragraphs(snapshot) if p['id']==text or p['id']=='literature:'+text),None)
                if not saved or paragraph['text']!=saved['text']:raise invalid('引用绑定只允许完全相同且已经核验的具体陈述。')
                before=deepcopy(paragraph.get('citations',[]));paragraph['citations']=deepcopy(saved['citations']);after=deepcopy(paragraph['citations'])
            elif not text:raise invalid('明确改文不能为空。')
            elif text==before:after=text
            elif paragraph.get('citations'):raise invalid('带核验引用的陈述不能自由改写后沿用旧支持决定。')
            else:
                # Convert only authoritative unchanged study bindings into the public
                # checker's exact fact paths. New prose is checked in strict mode.
                if op.get('numeric_bindings') is not None:
                    from app.domain.manuscript_review.facts import extract_facts
                    known={f['id']:f for f in extract_facts(snapshot)}
                    bound=op['numeric_bindings']
                    if any(b['fact_id'] not in known or known[b['fact_id']]['source_id'] not in op['evidence_ids'] for b in bound):raise invalid('逐值绑定必须来自所选固定统计证据。')
                    paragraph['numeric_bindings']=deepcopy(bound)
                elif writing_context and paragraph['id'] in writing_context.paragraphs:
                    _,bindings,literature=writing_context.paragraph(paragraph,{s['id']:s for s in snapshot['sources']})
                    if literature:raise invalid('文献数值陈述需新的支持核验，本批不可沿用旧审核改写。')
                    paragraph['numeric_bindings']=bindings
                adopted=[p for p in snapshot.get('review_analysis_provenance',[]) if p['source_id'] in op['evidence_ids']]
                if adopted:
                    superseded={sid for p in adopted for sid in p['supersedes_source_ids']}
                    selected=[sid for sid in op['evidence_ids'] if any(s['id']==sid for s in snapshot['sources'])]
                    paragraph['source_ids']=list(dict.fromkeys([sid for sid in paragraph.get('source_ids',[]) if sid not in superseded]+selected))
                paragraph['text']=text;strict.append(paragraph['id']);after=text
                if op['kind']=='split_paragraph':
                    chunks=[x.strip() for x in text.split('\n\n') if x.strip()]
                    if len(chunks)<2:raise invalid('拆段需要至少两个以空行分隔的段落。')
                    if paragraph.get('numeric_bindings') or paragraph.get('citations'):raise invalid('含逐数值/引用绑定的段落须保留整体，避免错误重分配依据。')
                    index=section['paragraphs'].index(paragraph)
                    pieces=[dict(deepcopy(paragraph),id=paragraph['id'] if n==0 else paragraph['id']+':split:'+str(n+1),text=chunk) for n,chunk in enumerate(chunks)]
                    section['paragraphs'][index:index+1]=pieces;strict.extend(p['id'] for p in pieces)
        elif op['kind']=='reorder_paragraphs':
            if loc['kind']!='section' or not section:raise invalid('段落排序必须选择固定章节。')
            before=[p['id'] for p in section['paragraphs']];after=op['paragraph_ids']
            if len(after)!=len(before) or set(after)!=set(before):raise invalid('排序必须包含该章全部段落且不能重复。')
            section['paragraphs']=[next(p for p in section['paragraphs'] if p['id']==pid) for pid in after]
        elif op['kind']=='figure_caption':
            figure=next((f for g in candidate['results_groups'] for f in g.get('figures',[]) if f['id']==loc['id']),None)
            if not figure or not text:raise invalid('图注需要固定图和明确文字。')
            before=figure.get('caption','');after=text
            if before!=after:
                figure.update(caption=text,caption_status='supplied',caption_origin='user_provided')
                strict.append('caption:'+figure['id'])
        elif op['kind']=='remove_figure':
            group=next((g for g in candidate['results_groups'] if any(f['id']==loc['id'] for f in g.get('figures',[]))),None)
            if loc['kind']!='figure' or group is None:raise invalid('只能明确移出固定稿件中存在的图。')
            before=deepcopy(next(f for f in group['figures'] if f['id']==loc['id']));after=None
            group['figures']=[f for f in group['figures'] if f['id']!=loc['id']]
        elif op['kind']=='section_title':
            if not target or snapshot.get('thesis_context'):raise invalid('显示调整须有本轮固定且支持的期刊规范。')
            from app.domain.journals.display import plan,apply
            options=plan(candidate,target,target['warnings'])['actions']
            action=next((a for a in options if a['key']=='section_display_names' and a['after'].get(loc['id'])==text),None)
            if not action:raise invalid('章名不匹配固定已知规范支持的显示要求。')
            before=action['before'][loc['id']];after=text
            narrow=dict(action,after=dict(action['before'])|{loc['id']:text})
            candidate=apply(candidate,[narrow])
            additional_evidence=[dict(id=r['id'],kind='journal_requirement',sha256=digest(r),content=r) for r in action['evidence']]
        if before==after:
            unexecuted.append(dict(item_id=item['id'],reason='没有实际差异，不生成完成事实。',status=item['status']));continue
        changes.append(dict(item_id=item['id'],kind=op['kind'],location={k:v for k,v in loc.items() if k!='text'},before=before,after=after,reason=op['reason'],evidence=[evidence[e] for e in op['evidence_ids']]+additional_evidence))
    removed={c['location']['id']:c['before']['number'] for c in changes if c['kind']=='remove_figure'}
    if removed:
        from app.domain.manuscripts.illustrations import BODY_REFERENCE
        for section in candidate['sections']:
            for paragraph in section['paragraphs']:
                if paragraph['id'] not in strict:continue
                mentioned={int(m['number']) for m in BODY_REFERENCE.finditer(paragraph['text']) if m['kind'].lower() not in ('table','表')}
                references=paragraph.get('cross_references',[])
                kept=[r for r in references if not (r.get('kind')=='figure' and r.get('target_id') in removed and removed[r['target_id']] not in mentioned)]
                if kept==references:continue
                paragraph['cross_references']=kept
                for group in candidate.get('results_groups',[]):
                    group['paragraphs']=[deepcopy(paragraph) if p['id']==paragraph['id'] else p for p in group.get('paragraphs',[])]
    changed={a['item_id'] for a in changes};skipped={a['item_id'] for a in unexecuted}
    for item in items:
        if item['id'] not in changed|skipped:unexecuted.append(dict(item_id=item['id'],reason=item['uncompleted_reason'] or '本次未选择具体修改。',status=item['status']))
    if snapshot.get('thesis_context'):
        from app.domain.manuscript_review.checks import check_snapshot
        from app.domain.manuscript_review.contracts import RULES_VERSION
        previous=snapshot.get('review') or (snapshot.get('review_history') or [{}])[-1].get('review',{})
        checks=check_snapshot(candidate,metadata=previous.get('metadata',[]),strict_locations=strict,writing_context=writing_context)
        candidate['school_content_report']=dict(rules_version=RULES_VERSION,issues=checks,can_publish=not any(i['severity']=='error' for i in checks),scientifically_verified=False)
    return candidate,changes,unexecuted,strict,issues
