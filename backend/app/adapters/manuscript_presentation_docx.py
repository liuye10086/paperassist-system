"""Fixed-text presentation over the existing renderer; never edits manuscript versions."""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile
import re

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.core.exceptions import StorageError
from .document_layout.package import read_package, write_package, parse, NS
from .manuscript_docx import _paragraph, _save_document, _figure


def paragraphs(snapshot):
    if snapshot.get('sections'):
        return [p for s in snapshot['sections'] if s.get('purpose', s['id']) != 'references' for p in s['paragraphs']]
    return [*snapshot['methods'], *[p for g in snapshot['results_groups'] for p in g['paragraphs']]]


def _mark(identity):
    return 'pa_' + sha256(identity.encode()).hexdigest()[:32]


def _language(node, language):
    props = node.find(qn('w:pPr'))
    if props is None:
        props = OxmlElement('w:pPr'); node.insert(0, props)
    runs = props.find(qn('w:rPr'))
    if runs is None:
        runs = OxmlElement('w:rPr'); props.append(runs)
    lang = runs.find(qn('w:lang'))
    if lang is None:
        lang = OxmlElement('w:lang'); runs.append(lang)
    lang.set(qn('w:val'), language); lang.set(qn('w:eastAsia'), language)


def _insert(document, text, anchor, identity, language, style=None):
    used = [int(n.get(qn('w:id'))) for n in document.element.iter(qn('w:bookmarkStart'))]
    _paragraph(document, dict(id=identity, text=text), max(used, default=0)+1)
    paragraph = document.paragraphs[-1]
    if style: paragraph.style = style
    _language(paragraph._p, language)
    if anchor is not None: anchor.addnext(paragraph._p)
    return paragraph._p


def _translated_text(snapshot, paragraph, numbers):
    """Renumber only frozen citation fragments, never parenthesized scientific values."""
    own = {r['project_reference_id']: r['number'] for r in snapshot.get('references', [])}
    bindings = paragraph.get('citations', [])
    if not bindings or all(numbers.get(k) == v for k, v in own.items()):
        return paragraph['text']
    from app.domain.manuscript_writing.context import citation_prose, literature_paragraphs
    try:
        citation_prose(snapshot, paragraph)
        exact = next(p for p in literature_paragraphs(snapshot)
                     if p['text'] == paragraph['text'] and p['citations'] == bindings)
        source = next(p for p in snapshot['citation_snapshot']['paragraphs']
                      if p['id'] == exact['id'].removeprefix('literature:'))
        return ''.join(f['text'] if f['kind'] == 'text' else
                       f['text'] + ' (' + ', '.join(str(n) for n in sorted({numbers[b['project_reference_id']] for b in f['bindings']})) + ')'
                       for f in source['fragments'])
    except (ValueError, KeyError, StopIteration) as exc:
        raise StorageError('presentation_citation_unresolved', '双语引用重编号缺少精确冻结片段，请先补充关联依据。', 422) from exc


def _references(document, selected, peer, *, include=True):
    references = deepcopy(selected.get('references', []))
    numbers = {r['project_reference_id']: r['number'] for r in references}
    added = []
    for reference in peer.get('references', []):
        if reference['project_reference_id'] not in numbers:
            numbers[reference['project_reference_id']] = len(references)+1
            item = dict(reference, number=len(references)+1)
            references.append(item); added.append(item)
    if added and include:
        school = bool(selected.get('thesis_context'))
        def text(r): return ('['+str(r['number'])+'] ' if school else '('+str(r['number'])+') ')+r['text']
        existing = {text(r) for r in selected.get('references', [])}
        anchors = [p._p for p in document.paragraphs if p.text in existing]
        if not anchors:
            anchors = [p._p for p in document.paragraphs if p.text in ('References', '参考文献', 'Bibliography')]
        anchor = anchors[-1] if anchors else document.add_heading('参考文献 / References', 1)._p
        for item in added:
            anchor = _insert(document, text(item), anchor, 'w2:reference:'+item['project_reference_id'], 'en')
    return numbers


def _bilingual(document, selected, peer, config, peer_images, excluded_chapter_ids):
    base = {p['id']: p for p in paragraphs(selected)}
    other = {p['id']: p for p in paragraphs(peer)}
    nodes = {mark.get(qn('w:name')): p._p for p in document.paragraphs for mark in p._p.iter(qn('w:bookmarkStart'))}
    for p in paragraphs(selected):
        if p['text'] == selected['title'] and _mark(p['id']) not in nodes:
            title = next((n._p for n in document.paragraphs if n.text == selected['title']), None)
            if title is not None: nodes[_mark(p['id'])] = title
    numbers = _references(document, selected, peer, include='references' not in excluded_chapter_ids)
    inserted = {p['id'] for section in peer.get('sections',[]) if section['id'] in excluded_chapter_ids for p in section['paragraphs']}
    suppressed=set(inserted)
    for group in config['paragraph_groups']:
        zh = [nodes[_mark(i)] for i in group['zh_ids'] if _mark(i) in nodes]
        # Explicitly excluded school chapters have no output anchor.
        if group['zh_ids'] and not zh:
            inserted.update(group['en_ids'])
            continue
        anchor = zh[-1] if zh else document.add_heading('未对应的英文内容 / Unpaired English content', 2)._p
        for identity in group['en_ids']:
            if identity in suppressed:continue
            paragraph = other[identity]
            anchor = _insert(document, _translated_text(peer, paragraph, numbers), anchor, 'w2:en:'+identity, 'en')
            inserted.add(identity)
        if group['status'] != 'paired':
            _insert(document, '对应关系待人工核对 / Correspondence requires review', anchor, 'w2:pending:'+group['id'], 'zh-CN')
    # Every unmapped source paragraph remains visible, never silently discarded.
    unmatched = [p for p in other.values() if p['id'] not in inserted]
    if unmatched:
        anchor = document.add_heading('未关联的英文段落 / Unmapped English paragraphs', 1)._p
        for paragraph in unmatched:
            anchor = _insert(document, _translated_text(peer, paragraph, numbers), anchor, 'w2:unmapped:'+paragraph['id'], 'en')
    by_en = {f['id']: f for g in peer['results_groups'] for f in g['figures']}
    by_zh = {f['id']: f for g in selected['results_groups'] for f in g['figures']}
    for pair in config['figure_pairs']:
        zh, en = by_zh[pair['zh_figure_id']], by_en[pair['en_figure_id']]
        matches = [p._p for p in document.paragraphs if p.text == zh.get('caption') or
                   p.text.endswith('  '+zh['title'])]
        if not matches: continue
        anchor = matches[-1]
        if en['sha256'] != zh['sha256']:
            before = set(document.element.body)
            _figure(document, en, peer_images, True)
            for node in [n for n in document.element.body if n not in before]:
                anchor.addnext(node); anchor = node
                if node.tag == qn('w:p'): _language(node, 'en')
        else:
            anchor = _insert(document, 'Figure '+str(zh['number'])+'  '+en['title'], anchor, 'w2:figure:'+en['id'], 'en', 'Caption')
            if en.get('caption'):
                _insert(document, en['caption'], anchor, 'w2:caption:'+en['id'], 'en', 'Caption')


def _identity(paragraph):
    document=paragraph.part.document
    number=max((int(n.get(qn('w:id'))) for n in document.element.iter(qn('w:bookmarkStart'))),default=0)+1
    start=OxmlElement('w:bookmarkStart');start.set(qn('w:id'),str(number));start.set(qn('w:name'),'W2_IDENTITY_'+str(number))
    end=OxmlElement('w:bookmarkEnd');end.set(qn('w:id'),str(number));paragraph._p.append(start);paragraph._p.append(end)


def _declarations(document, config, language):
    en = language == 'en'
    document.add_heading('Authorship and declarations' if en else '作者信息与声明', 1)
    for author in sorted(config['authors'], key=lambda a: a['order']):
        text = str(author['order'])+'. '+author['name']
        if author['corresponding']: text += ' (Corresponding author)' if en else '（通讯作者）'
        _identity(document.add_paragraph(text))
        if author['affiliation_ids']:
            _identity(document.add_paragraph('; '.join(a['name'] for a in config['affiliations'] if a['id'] in author['affiliation_ids'])))
    if not config['authors']: document.add_paragraph('Authors pending' if en else '作者信息待提供')
    labels = {'funding': ('Funding', '基金'), 'ethics': ('Ethics', '伦理'), 'registration': ('Registration', '注册'),
              'conflict': ('Conflicts of interest', '利益冲突'), 'data_availability': ('Data availability', '数据可用性')}
    statements = {s['kind']: s for s in config['statements']}
    for kind, labels_pair in labels.items():
        item = statements.get(kind)
        text = ('Pending user material' if en else '待用户提供材料') if not item or item['state'] == 'pending' else (
            ('Not applicable: ' if en else '不适用：')+item['reason'] if item['state'] == 'not_applicable' else item['text'])
        document.add_paragraph(labels_pair[0 if en else 1]+': '+text)


def language_inventory(raw, language, source_map=()):
    owned = {r.get('source_bookmark'): r for r in source_map if r.get('source_bookmark')}
    items = []
    for name, data in read_package(raw).items():
        if name not in ('word/document.xml', 'word/footnotes.xml', 'word/endnotes.xml') and not re.fullmatch(r'word/(?:header|footer)\d+\.xml', name): continue
        root = parse(data)
        for index, node in enumerate(root.iter(qn('w:p'))):
            text = ''.join(n.text or '' for n in node.iter(qn('w:t')))
            if not text: continue
            lang = node.find('./'+qn('w:pPr')+'/'+qn('w:rPr')+'/'+qn('w:lang'))
            original = next((owned[m.get(qn('w:name'))] for m in node.iter(qn('w:bookmarkStart')) if m.get(qn('w:name')) in owned), {})
            items.append(dict(location=name+':paragraph:'+str(index),kind='export_text', text=text, content_sha256=sha256(text.encode()).hexdigest(),
                              target_language=lang.get(qn('w:val')) if lang is not None else original.get('target_language', language),
                              scope=original.get('scope', 'narrative'),protected_identity=original.get('protected_identity',False) or any(m.get(qn('w:name'),'').startswith('W2_IDENTITY_') for m in node.iter(qn('w:bookmarkStart'))),
                              verification='pending_manual_review'))
    return items


def actual_image_inventory(raw, records, language):
    from app.domain.literature.service import digest
    hashes={sha256(value).hexdigest() for name,value in read_package(raw).items() if name.startswith('word/media/')}
    result=[];seen=set()
    for record in records:
        record = dict(record, location=record['target_language']+':'+record['location'])
        if record['asset_sha256'] not in hashes or record['location'] in seen:continue
        result.append(record);seen.add(record['location'])
    known={r['asset_sha256'] for r in result if r['kind']=='image'}
    for value in hashes-known:
        result.append(dict(location='image:'+value,kind='image',asset_sha256=value,content_sha256=digest(dict(asset_sha256=value,manifest=None)),
                           text='',language_known=False,no_text=False,target_language=language))
    return result


def language_observations(inventory):
    """Run the existing finite rule without manufacturing a human decision."""
    from app.domain.literature.service import digest
    from app.domain.manuscript_writing.language import validate_decisions
    result=deepcopy(inventory)
    for item in result:
        if item.get('protected_identity'):
            item['finite_check']=dict(status='pending',message='身份原文需要明确逐项确认。');continue
        if item['kind']=='image' and not item['language_known']:
            item['finite_check']=dict(status='pending',message='图内文字未知；不能以自动检查或无文字决定豁免。');continue
        decision=dict(location=item['location'],content_sha256=item['content_sha256'],decision='no_text' if item.get('no_text') else 'target_language',
                      reason='自动有限脚本检查，不构成人工语言确认。',exceptions=[])
        try:
            validate_decisions([item],dict(inventory_sha256=digest([item]),decisions=[decision]),item['target_language'])
            item['finite_check']=dict(status='passed',message='有限脚本规则通过；语义和局部例外仍需明确确认。')
        except ValueError as exc:
            item['finite_check']=dict(status='conflict',message=str(exc))
        item['verification']='pending_manual_review'
    return result



def _school_display_headings(document, nodes):
    """Keep added school titles visually styled, outside Heading/outline TOCs."""
    for node in nodes:
        if node.tag != qn('w:p'): continue
        ppr = node.find(qn('w:pPr'))
        style_ref = ppr.find(qn('w:pStyle')) if ppr is not None else None
        if style_ref is None or not style_ref.get(qn('w:val'), '').startswith('Heading'): continue
        source = next(s for s in document.styles if s.style_id == style_ref.get(qn('w:val')))
        name = 'PaperAssist display ' + source.name
        if name not in document.styles:
            display = document.styles.add_style(name, source.type)
            display.base_style = document.styles['Normal']
            for tag in ('w:pPr', 'w:rPr'):
                properties = source.element.find(qn(tag))
                if properties is not None: display.element.append(deepcopy(properties))
            props = display.element.get_or_add_pPr()
            outline = props.find(qn('w:outlineLvl'))
            if outline is None:
                outline = OxmlElement('w:outlineLvl'); props.append(outline)
            outline.set(qn('w:val'), '9')
        style_ref.set(qn('w:val'), document.styles[name].style_id)
        outline = ppr.find(qn('w:outlineLvl'))
        if outline is None:
            outline = OxmlElement('w:outlineLvl'); ppr.append(outline)
        outline.set(qn('w:val'), '9')


def decorate_docx(raw, selected, peer, config, language_view, *, peer_images=None, source_map=(),
                  excluded_chapter_ids=frozenset()):
    document = Document(BytesIO(raw))
    original_nodes = set(document.element.body)
    if language_view == 'zh-CN-en':
        if selected['output_language'] != 'zh-CN' or not peer or peer['output_language'] != 'en':
            raise StorageError('presentation_language_unavailable', '中英对照需要同源的中文和英文固定版本。', 422)
        _bilingual(document, selected, peer, config, peer_images or {},excluded_chapter_ids)
    from app.domain.school_templates import bsu_gs501
    gs501 = bsu_gs501.selected(selected)
    if not gs501 or config['authors'] or config['statements']:
        _declarations(document, config, selected['output_language'])
    if selected.get('thesis_context'):
        # Added presentation headings are outside the confirmed school chapter TOC.
        _school_display_headings(document, (node for node in document.element.body if node not in original_nodes))
    content = _save_document(document)
    # python-docx drops this intentional passive, unlinked layout receipt.
    layout_path = 'customXml/paperassist-layout.xml'
    with ZipFile(BytesIO(raw)) as source:
        layout = source.read(layout_path) if layout_path in source.namelist() else None
    if layout is not None:
        with ZipFile(BytesIO(content)) as rendered:
            parts = {name: rendered.read(name) for name in rendered.namelist()}
        parts[layout_path] = layout
        content = write_package(parts)
    return content, dict(language_inventory=language_inventory(content, selected['output_language'], source_map))
