"""Exact actual-export inventory; language edits never change scientific prose."""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import re
from zipfile import ZipFile
from lxml import etree
from app.adapters.task_store import source_conflict
from app.adapters.manuscript_docx import build_manuscript_docx, RENDERER_VERSION
from app.domain.literature.service import digest
from .context import NUMBER
from .numeric_review import NUMERIC_VERSION,validation_version,language_markers


def editable_fields(candidate):
    fields=[]
    def item(path,text):
        fields.append(dict(path=path,text=text,original_sha256=digest(text)))
    for g,group in enumerate(candidate['results_groups']):
        prefix=f'/results_groups/{g}'
        item(prefix+'/title',group['title'])
        for t,table in enumerate(group['tables']):
            base=prefix+f'/tables/{t}'
            item(base+'/title',table['title'])
            for c,text in enumerate(table['columns']): item(base+f'/columns/{c}',text)
            for r,row in enumerate(table['rows']):
                for c,text in enumerate(row):
                    if isinstance(text,str) and re.search(r'[A-Za-z\u3400-\u9fff]',text): item(base+f'/rows/{r}/{c}',text)
        for f,figure in enumerate(group['figures']):
            base=prefix+f'/figures/{f}'
            for key in ('title','caption'): item(base+'/'+key,figure[key])
            for p,panel in enumerate(figure.get('panels',[])): item(base+f'/panels/{p}/description',panel['description'])
    return fields


def prepare_candidate(candidate,body,*,numeric_version=NUMERIC_VERSION):
    markers=language_markers if validation_version(numeric_version)==NUMERIC_VERSION else NUMBER.findall
    result=deepcopy(candidate);allowed={x['path']:x for x in editable_fields(candidate)};seen=set()
    for edit in body['edits']:
        path=edit['path'];old=allowed.get(path)
        if not old or path in seen or old['original_sha256']!=edit['original_sha256'] or not edit['reason'].strip() or not edit['text'].strip(): raise ValueError('Only exact bound figure/table text may be translated; scientific text requires new scientific review')
        if markers(old['text'])!=markers(edit['text']): raise ValueError('Language edits cannot change numerical facts or markers')
        seen.add(path);parts=path.strip('/').split('/');node=result
        for part in parts[:-1]: node=node[int(part)] if isinstance(node,list) else node[part]
        key=int(parts[-1]) if isinstance(node,list) else parts[-1];node[key]=edit['text']
    return result


def figure_materials(assets,db,project,candidate):
    """Load exactly the bytes subsequently consumed by DOCX, never trust preview URLs."""
    images={};items=[]
    for group in candidate['results_groups']:
        for figure in group['figures']:
            source=next(s for s in candidate['sources'] if s['id']==figure['source_ids'][0])
            version_id=figure.get('language_version_id') or (source['id'] if source['kind']=='figure_language_version' else None)
            manifest=None
            if version_id:
                from app.domain.manuscripts.figure_language import FigureLanguageService
                service=FigureLanguageService(assets);row=service.row(db,project,version_id);snap=row['snapshot_json'];raw=service.png(row)
                if snap['output_language']!=candidate['output_language']: raise ValueError('Figure language mismatch')
                manifest=snap['text_manifest']
                if not manifest and snap['mode']!='no_text_confirmation': raise ValueError('Unknown image text')
            elif source['kind']=='figure': raw=assets.figure_png(source['content'])
            elif source['kind']=='document_version':
                from app.domain.documents.service import DocumentService
                service=DocumentService(assets);row=service.load(project,source['file_id'],source['id'],True)
                raw,_=service.objects().image(row['result_json'],figure['image_id'])
            else: raw=assets.original(assets.file(project,source['file_id']))
            if sha256(raw).hexdigest()!=figure['sha256']: raise source_conflict()
            images[figure['id']]=raw
            prefix='image:'+figure['id']
            items.append(dict(location=prefix,kind='image',asset_sha256=figure['sha256'],content_sha256=digest(dict(asset_sha256=figure['sha256'],manifest=manifest)),text='',language_known=manifest is not None,no_text=manifest==[]))
            for entry in manifest or []:
                items.append(dict(location=prefix+':'+entry['location'],kind='figure_text',scope='label' if entry['location'] in ('x_label','y_label') or entry['location'].startswith(('series.','tick.','sample_count.')) else 'narrative',text=entry['text'],asset_sha256=figure['sha256'],content_sha256=digest(dict(text=entry['text'],asset_sha256=figure['sha256']))))
    return images,items


def export_semantics(candidate):
    """Retain prose boundaries even when the renderer prefixes a panel identifier."""
    narrative={p['text'] for section in candidate.get('sections',[]) if section['id']!='references' for p in section['paragraphs']}
    narrative.update(candidate.get(k,'') for k in ('title','notice','acknowledgements'))
    labels=set()
    for issue in candidate.get('issues',[]):
        narrative.add(issue['message']);narrative.update(issue.get('values',[]))
    for group in candidate['results_groups']:
        narrative.add(group['title'])
        for table in group['tables']:
            narrative.add(table['title'])
            labels.update(str(v) for v in table['columns'])
            labels.update(str(v) for row in table['rows'] for v in row)
        for figure in group['figures']:
            narrative.update((figure['title'],figure['caption']))
            narrative.update(p['description'] for p in figure.get('panels',[]))
    labels.update(s['label'] for s in candidate.get('sources',[]))
    return {text for text in narrative if text},labels


def reference_paragraphs(root,candidate):
    """Locate bibliography by the actual renderer's body/section structure.

    A same-text paragraph elsewhere, including a table cell or scientific body,
    is never a reference. Exact ordered contents additionally bind the section.
    """
    w='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    body=root.find(w+'body')
    if body is None:return set()
    expected=['('+str(ref['number'])+') '+ref['text'] for ref in candidate.get('references',[])]
    heading='References' if candidate['output_language']=='en' else '参考文献'
    result=set();active=False;index=0
    for paragraph in body:
        if paragraph.tag!=w+'p':continue
        text=''.join(paragraph.xpath('.//w:t/text()',namespaces={'w':w[1:-1]}))
        style=paragraph.find(w+'pPr/'+w+'pStyle')
        if style is not None and style.get(w+'val')=='Heading1':
            active=text==heading
            continue
        if active and index<len(expected):
            if text!=expected[index]:raise ValueError('Actual bibliography structure differs from frozen references')
            result.add(paragraph);index+=1
    if index!=len(expected):raise ValueError('Actual bibliography does not contain every frozen reference')
    return result


def inventory(candidate,images,image_items):
    raw=build_manuscript_docx(candidate,images);items=[]
    narrative,labels=export_semantics(candidate)
    with ZipFile(BytesIO(raw)) as archive:
        for name in sorted(archive.namelist()):
            if name!='word/document.xml' and not re.fullmatch(r'word/(?:header|footer)\d+\.xml',name): continue
            root=etree.fromstring(archive.read(name))
            references=reference_paragraphs(root,candidate) if name=='word/document.xml' else set()
            for index,p in enumerate(root.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p')):
                text=''.join(p.xpath('.//w:t/text()',namespaces={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}))
                if not text: continue
                spans=[] if p in references else sorted({(m.start(),m.end()) for value in narrative for m in re.finditer(re.escape(value),text)})
                scope='reference_metadata' if p in references else 'narrative' if spans or text not in labels else 'label'
                if scope=='narrative' and not spans: spans=[(0,len(text))]
                items.append(dict(location=name+f':paragraph:{index}',kind='export_text',scope=scope,narrative_ranges=[list(span) for span in spans],text=text,content_sha256=digest(text)))
    return items+image_items


def validate_decisions(items,body,language):
    if digest(items)!=body['inventory_sha256']: raise ValueError('Export inventory changed')
    by_location={i['location']:i for i in items};decisions=body['decisions']
    if len(decisions)!=len(items) or len({d['location'] for d in decisions})!=len(items): raise ValueError('Every exported item requires one explicit decision')
    for decision in decisions:
        item=by_location.get(decision['location'])
        if not item or item['content_sha256']!=decision['content_sha256'] or not decision['reason'].strip(): raise ValueError('Language decision is not bound to exact exported content')
        if item['kind']=='image':
            if not item['language_known'] or decision['exceptions'] or decision['decision']!=('no_text' if item['no_text'] else 'target_language'): raise ValueError('Unknown external image requires verified replacement or no-text version')
            continue
        if decision['decision']!='target_language': raise ValueError('Text requires language judgment')
        text=item['text'];masked=list(text);end=0
        for exc in sorted(decision['exceptions'],key=lambda x:x['start']):
            a,b=exc['start'],exc['end'];fragment=text[a:b]
            if a<end or b>len(text) or a>=b or not exc['reason'].strip() or not fragment.strip() or len(fragment)>120: raise ValueError('Invalid localized language exception')
            if len(re.findall(r'[A-Za-z]+',fragment))>5 or (a==0 and b==len(text) and len(fragment)>40): raise ValueError('Whole prose cannot be exempted')
            if exc['kind']=='unit' and not re.fullmatch(r'[A-Za-zµμ%°Ω][A-Za-z0-9µμ%°Ω/·^−+.-]{0,19}',fragment): raise ValueError('Unit exceptions must be short unit symbols')
            if exc['kind']=='reference_metadata' and (item.get('scope')!='reference_metadata' or (a==0 and b==len(text))): raise ValueError('Reference exception must be local to actual reference text')
            masked[a:b]=[' ']*(b-a);end=b
        remaining=''.join(masked)
        if decision['exceptions']:
            ranges=item.get('narrative_ranges') or ([(0,len(text))] if item.get('scope') not in ('label','reference_metadata') else [])
            if item.get('scope')=='reference_metadata' and any(exc['kind']!='reference_metadata' for exc in decision['exceptions']): raise ValueError('Bibliography exceptions require explicit reference metadata decisions')
            for a,b in ranges:
                if re.search(r'[A-Za-z\u3400-\u9fff]',text[a:b]) and not re.search(r'[A-Za-z\u3400-\u9fff]',remaining[a:b]): raise ValueError('Whole prose cannot be exempted')
            if item.get('scope')=='label' and not re.search(r'[A-Za-z\u3400-\u9fff]',remaining):
                exceptions=decision['exceptions']
                if (len(exceptions)!=1 or exceptions[0]['start']!=0 or exceptions[0]['end']!=len(text)
                    or exceptions[0]['kind'] not in ('unit','proper_name') or len(text)>40
                    or re.search(r'[。！？!?;；]',text)): raise ValueError('Only one explicitly typed short unit/name label may be retained whole')
        if language=='en' and re.search(r'[\u3400-\u9fff]',remaining): raise ValueError('Unreviewed non-target script')
        if language=='zh-CN' and re.search(r'[A-Za-z]{2,}',remaining): raise ValueError('Latin names/units need local explicit exceptions')
