"""Bounded DOCX alignment; bookmarks are untrusted matching hints only."""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import re
from zipfile import ZipFile
from lxml import etree
from app.adapters.docx_parser import parse_docx,NS,W
from app.domain.documents.contracts import DOCX_SETTINGS
from app.domain.literature.service import digest
from app.domain.manuscripts.school_return_xml import protected_parts,toc_cache


def issue(code,message,location='',severity='error'):
    return dict(code=code,severity=severity,message=message,location=location)


def package_hints(raw):
    # The caller first runs the same bounded parser used by immutable document input.
    with ZipFile(BytesIO(raw)) as package:
        root=etree.fromstring(package.read('word/document.xml'),etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False))
        paragraphs=root.findall('.//w:p',NS)
        paths={root.getroottree().getpath(p):[n.get('{'+W+'}name') for n in p.findall('.//w:bookmarkStart',NS)] for p in paragraphs}
        semantics={}
        for p in paragraphs:
            references=[(etree.QName(n).localname,n.get('{'+W+'}id')) for n in p.iter() if n.tag in ('{'+W+'}footnoteReference','{'+W+'}endnoteReference')]
            fields=[' '.join(''.join(p.xpath('.//w:instrText/text()',namespaces=NS)).split())]
            fields.extend(' '.join(n.get('{'+W+'}instr','').split()) for n in p.findall('.//w:fldSimple',NS))
            semantics[root.getroottree().getpath(p)]=dict(references=references,fields=[f for f in fields if f])
        protected=protected_parts(package,root)
        toc=toc_cache(root)
    return paths,protected,semantics,toc


def normalize(text):return re.sub(r'\s+','',text)


def extract(raw,filename,base,baseline_raw=None,*,document=None,known_headings_only=False):
    document=document or parse_docx(raw,filename,DOCX_SETTINGS).document.model_dump()
    hints,protected,semantics,toc=package_hints(raw)
    original={};bookmark_sections={};by_title={}
    for section in base['sections']:
        by_title.setdefault(normalize(section['title']),[]).append(section['id'])
        for p in section['paragraphs']:
            key='pa_'+sha256(p['id'].encode()).hexdigest()[:32]
            original[key]=p;bookmark_sections.setdefault(key,set()).add(section['id'])
    problems=[]
    for warning in document['warnings']:
        if warning['code'] not in ('fields','other_parts'):
            problems.append(issue('unsupported_docx',warning['message'],warning['code']))
    baseline=None;baseline_hints={};baseline_blocks={};baseline_semantics={};baseline_toc=[];toc_paths=set();old_toc_paths=set()
    if baseline_raw:
        baseline=parse_docx(baseline_raw,'base.docx',DOCX_SETTINGS).document.model_dump()
        baseline_hints,old_protected,baseline_semantics,baseline_toc=package_hints(baseline_raw)
        baseline_blocks={b['source']['path']:b for b in baseline['blocks']}
        if old_protected!=protected:problems.append(issue('citation_changed','页眉页脚、脚注、尾注或批注发生变化，须人工核对。'))
    elif any(protected.get(k) for k in ('notes','other')) or any(protected.get('roles',[])):problems.append(issue('citation_changed','无固定导出可核对页眉页脚、脚注或尾注。'))
    if baseline_toc and [{k:v for k,v in t.items() if k!='paths'} for t in toc]==[{k:v for k,v in t.items() if k!='paths'} for t in baseline_toc]:
        toc_paths={p for t in toc for p in t['paths']};old_toc_paths={p for t in baseline_toc for p in t['paths']}
        problems.append(issue('export_cache_normalized','已核对目录域指令与逐项目标章标题；Word 的目录页码缓存和分页格式变化未当作研究正文。',severity='warning'))
    def visual(block,semantic_map=semantics):
        if block['kind']=='paragraph':return dict(text=block['text'],images=block['image_ids'],semantic=semantic_map.get(block['source']['path'],dict(references=[],fields=[])))
        return dict(rows=block['rows'],columns=block['columns'],cells=[dict(row=c['row'],column=c['column'],row_span=c['row_span'],column_span=c['column_span'],blocks=[visual(b,semantic_map) for b in c['blocks']]) for c in block['cells']])
    def is_heading(block,marks):
        return block['kind']=='paragraph' and not any(m in original for m in marks) and bool(normalize(block['text']) in by_title or not known_headings_only and (block.get('heading_level') or block.get('style_id') in ('SchoolChineseAbstract','SchoolEnglishAbstract','SchoolReferences','SchoolAcknowledgements')))
    def chapter_scopes(doc,marks):
        # Chapter content/bookmark anchors survive inserted ordinary paragraphs.
        # No matching across chapter boundaries and no absolute XML row numbers.
        result={};group=[];title='__front__'
        def flush():
            identities=set().union(*(bookmark_sections[m] for b in group for m in marks.get(b['source']['path'],[]) if m in bookmark_sections))
            candidates=by_title.get(title,[])
            scope=next(iter(identities)) if len(identities)==1 else candidates[0] if len(candidates)==1 else title
            for b in group:result[b['source']['path']]=scope
        for b in doc['blocks']:
            if is_heading(b,marks.get(b['source']['path'],[])):
                flush();group=[];title=normalize(b['text'])
            group.append(b)
        flush();return result
    scopes=chapter_scopes(document,hints);baseline_scopes=chapter_scopes(baseline,baseline_hints) if baseline else {}
    def chapter_semantics(doc,scope_map,semantic_map,cache_paths):
        result={}
        for b in (doc or {}).get('blocks',[]):
            if b['kind']!='paragraph' or b['source']['path'] in cache_paths:continue
            semantic=semantic_map.get(b['source']['path'],{})
            if semantic.get('references') or semantic.get('fields'):result.setdefault(scope_map[b['source']['path']],[]).append(semantic)
        return result
    if chapter_semantics(document,scopes,semantics,toc_paths)!=chapter_semantics(baseline,baseline_scopes,baseline_semantics,old_toc_paths):
        problems.append(issue('citation_changed','章节脚注、尾注指向或字段语义变化，不能仅靠标题或书签沿用原支持。'))
    decorations={}
    for path,old in baseline_blocks.items():
        if path in old_toc_paths or old['kind']!='paragraph' or any(m in original for m in baseline_hints.get(path,[])) or is_heading(old,baseline_hints.get(path,[])):continue
        key=(baseline_scopes[path],digest(visual(old,baseline_semantics)))
        decorations.setdefault(key,[]).append(old)
    def media(doc):return [i['sha256'] for i in doc['images']]
    baseline_by_bookmark={mark:block for block in (baseline or {}).get('blocks',[]) if block['kind']=='paragraph' for mark in baseline_hints.get(block['source']['path'],[]) if mark in original}
    if (media(document)!=media(baseline) if baseline else bool(document['images'])):
        problems.append(issue('illustration_changed','图片新增、删除或内容改变，不能沿用原图表核实状态。'))
    tables=[visual(b) for b in document['blocks'] if b['kind']=='table']
    old_tables=[visual(b,baseline_semantics) for b in (baseline or {}).get('blocks',[]) if b['kind']=='table']
    if tables!=old_tables:problems.append(issue('illustration_changed','表格新增、删除或内容改变，须独立核实。'))
    sections=[];current=None;seen_bookmarks=set();ignored=[]
    for block in document['blocks']:
        if block['kind']!='paragraph':continue
        path=block['source']['path'];text=block['text'];marks=[x for x in hints.get(path,[]) if x in bookmark_sections]
        if path in toc_paths and not marks:
            ignored.append(dict(path=path,text=text,reason='verified_toc_cache'));continue
        decoration_key=(scopes[path],digest(visual(block)))
        if not marks and not is_heading(block,hints.get(path,[])) and decorations.get(decoration_key):
            old=decorations[decoration_key].pop(0)
            ignored.append(dict(path=path,original_path=old['source']['path'],text=text));continue
        if not text.strip() and not marks:continue
        candidates=by_title.get(normalize(text),[])
        heading=is_heading(block,marks)
        if known_headings_only and block.get('heading_level') and not heading and not marks:
            problems.append(issue('unsupported_heading','回传含未匹配的额外标题；保留原件并须明确核对章节结构。',block['id']))
        if heading:
            current=dict(id=block['id'],title=text,paragraphs=[],paragraph_items=[],candidate_chapter_ids=candidates,match_method='title' if len(candidates)==1 else 'ambiguous' if candidates else 'none',suggested_chapter_id=candidates[0] if len(candidates)==1 else None)
            sections.append(current);continue
        if current is None:
            current=dict(id='unassigned-front',title='未分配正文 / front matter',paragraphs=[],paragraph_items=[],candidate_chapter_ids=[],match_method='none',suggested_chapter_id=None);sections.append(current)
        matched=set().union(*(bookmark_sections[m] for m in marks)) if marks else set()
        if marks:
            if any(m in seen_bookmarks for m in marks):problems.append(issue('duplicate_bookmark','书签重复，须重新提供无歧义原稿。',block['id']))
            seen_bookmarks.update(marks)
            combined=set(current.get('_bookmark_candidates',[]))|matched;current['_bookmark_candidates']=sorted(combined)
            current.update(candidate_chapter_ids=sorted(combined),match_method='bookmark' if len(combined)==1 else 'ambiguous',suggested_chapter_id=next(iter(combined)) if len(combined)==1 else None)
            # A renderer can replace [n] with a footnote marker. Only an exact
            # unchanged exported paragraph may reuse the parent's original text.
            if len(marks)==1 and marks[0] in baseline_by_bookmark:
                before=visual(baseline_by_bookmark[marks[0]],baseline_semantics);after=visual(block)
                if before['semantic']!=after['semantic']:problems.append(issue('citation_changed','段落脚注、尾注指向或字段语义发生变化，不能继承原支持。',block['id']))
                if before==after:text=original[marks[0]]['text']
        current['paragraphs'].append(text)
        current['paragraph_items'].append(dict(text=text,original_id=original[marks[0]]['id'] if len(marks)==1 else None))
    for remaining in decorations.values():
        for old in remaining:
            if old['text'].strip() or old['image_ids']:problems.append(issue('nonbody_changed','固定导出的封面、目录、图题、书目或人工附加内容变化；保留原件并须人工核对。',old['source']['path']))
    for section in sections:
        section.pop('_bookmark_candidates',None)
        old_section=next((s for s in base['sections'] if s['id']==section['suggested_chapter_id']),None)
        if baseline and old_section and old_section['purpose'] in ('references','manual') and not section['paragraphs']:
            section['paragraphs']=[p['text'] for p in old_section['paragraphs']]
            section['paragraph_items']=[dict(text=p['text'],original_id=p['id']) for p in old_section['paragraphs']]
    if not sections:problems.append(issue('empty_return','回传无可采用章节正文。'))
    if ignored:problems.append(issue('export_nonbody_retained','已核对固定导出中未变的封面、目录、图表说明和人工附加内容；保留在原导出与回传原件，未当作新增研究正文。',severity='warning'))
    return dict(sections=sections,issues=problems,retained_nonbody=ignored,document_sha256=sha256(raw).hexdigest())


def tokens(text):
    text=re.sub(r'\[\d+(?:[-,，]\d+)*\]','',text)
    return re.findall(r'(?<![A-Za-z])[-+]?\d+(?:[.,]\d+)*(?:\s*(?:%|％|mmol|mol|μg|ug|mg|kg|g|ml|mL|L|mm|cm|nm|μm|min|h|s|℃|°C|毫克|千克|克|毫升|升|毫米|厘米|米|小时|分钟|秒))?',text)


def apply_return(base,inputs,mappings):
    result=deepcopy(base);differences=[];problems=[];by_input={s['id']:s for s in inputs}
    assigned={m['chapter_id']:by_input[m['input_section_id']] for m in mappings}
    for section in result['sections']:
        incoming=assigned.get(section['id'])
        if incoming is None:
            problems.append(issue('chapter_missing','回传缺少原章节，须补齐或以模板迁移明确调整。',section['id']))
            differences.append(dict(kind='chapter_removed',location=section['id'],message='回传缺章',before=section['title'],after=''))
            continue
        old=section['paragraphs'];before='\n'.join(p['text'] for p in old);after='\n'.join(incoming['paragraphs'])
        if before==after:continue
        differences.append(dict(kind='text_changed',location=section['id'],message='正文改变；改变段落不继承原支持绑定。',before=before,after=after))
        if tokens(before)!=tokens(after):
            differences.append(dict(kind='numeric_changed',location=section['id'],message='数值或单位改变',before=before,after=after))
            problems.append(issue('numeric_changed','数值或单位变化须经原事实核实流程；本次输入保留。',section['id']))
        if section['purpose']=='references' or re.findall(r'\[\d+(?:[-,，]\d+)*\]',before)!=re.findall(r'\[\d+(?:[-,，]\d+)*\]',after):
            differences.append(dict(kind='citation_changed',location=section['id'],message='引用或书目变化',before=before,after=after))
            problems.append(issue('citation_changed','引用或书目变化不能继承原核实状态。',section['id']))
        new=[];used=set()
        for index,item in enumerate(incoming['paragraph_items']):
            matches=[p for p in old if p['text']==item['text'] and p['id'] not in used and (not item['original_id'] or item['original_id']==p['id'])]
            if len(matches)==1:
                p=deepcopy(matches[0]);used.add(p['id'])
            else:p=dict(id='school-return:'+incoming['id']+':'+str(index),text=item['text'],origin='user_provided',source_ids=[],citations=[],numeric_bindings=[])
            new.append(p)
        # Changed claim text cannot retain reviewed citation or numeric support.
        for p in old:
            if p['id'] not in used and (p.get('citations') or p.get('claim_bindings') or p.get('numeric_bindings')):
                problems.append(issue('bound_claim_changed','已绑定论述发生变化，不能继承原支持；请先重新核实。',section['id']))
        section['paragraphs']=new
    return result,differences,problems
