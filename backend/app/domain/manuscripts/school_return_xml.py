"""Finite Word SaveAs equivalences, used only against a fixed school export."""
import posixpath
import re
from lxml import etree
from app.adapters.docx_parser import NS, W
from app.domain.literature.service import digest

R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def xml(raw):
    return etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False))


def command(value):
    return ' '.join(value.split())


def paragraph_content(p):
    """Ignore run formatting and PAGE cache, retaining unknown content tokens."""
    output=[];stack=[]
    def emit(item):
        target=stack[-1]['result'] if stack else output
        if isinstance(item,str) and target and isinstance(target[-1],str):target[-1]+=item
        else:target.append(item)
    def field(instr,result):
        instr=command(instr)
        if re.fullmatch(r'PAGE(?: \\\* MERGEFORMAT)?',instr,re.I) and all(isinstance(item,str) for item in result) and re.fullmatch(r'[0-9IVXLCDMivxlcdm\s]*',''.join(result)):
            return ('field','PAGE')
        return ('field',instr,result)
    def walk(n):
        if n.tag in ('{'+W+'}pPr','{'+W+'}rPr','{'+W+'}proofErr','{'+W+'}lastRenderedPageBreak'):return
        if n.tag in ('{'+W+'}bookmarkStart','{'+W+'}bookmarkEnd'):return
        if n.tag=='{'+W+'}fldSimple':
            emit(field(n.get('{'+W+'}instr',''),paragraph_content(n)));return
        if n.tag=='{'+W+'}fldChar':
            kind=n.get('{'+W+'}fldCharType')
            if kind=='begin':stack.append(dict(instr='',result=[]))
            elif kind=='end' and stack:
                item=stack.pop();emit(field(item['instr'],item['result']))
            elif kind!='separate':emit(('unmatched_field',kind))
            return
        if n.tag=='{'+W+'}instrText':
            if stack:stack[-1]['instr']+=n.text or ''
            else:emit(('instruction',command(n.text or '')))
            return
        if n.tag=='{'+W+'}t':emit(n.text or '');return
        if n.tag in ('{'+W+'}p','{'+W+'}r'):
            for child in n:walk(child)
            return
        # Unknown structures, references, hyperlinks and embedded objects are
        # evidence, never silently discarded as formatting.
        emit(('open',n.tag,sorted(n.attrib.items()),n.text or ''))
        for child in n:walk(child)
        emit(('close',n.tag))
    for child in p:walk(child)
    if stack:output.append(('unclosed_fields',stack))
    return [item.strip() if isinstance(item,str) else item for item in output if not isinstance(item,str) or item.strip()]


def protected_content(root):
    def visit(n):
        if n.tag=='{'+W+'}p':return ('paragraph',paragraph_content(n))
        attrs=[(k,v) for k,v in n.attrib.items() if not etree.QName(k).localname.startswith('rsid') and etree.QName(k).localname not in ('Ignorable','paraId','textId')]
        return (n.tag,sorted(attrs),[visit(child) for child in n])
    return visit(root)


def protected_parts(package,document):
    # Word renumbers header filenames. Resolve each actual section/role first.
    relroot=xml(package.read('word/_rels/document.xml.rels')) if 'word/_rels/document.xml.rels' in package.namelist() else []
    rels={n.get('Id'):posixpath.normpath(posixpath.join('word',n.get('Target',''))).lstrip('/') for n in relroot}
    names=[n for n in package.namelist() if n.startswith(('word/footnotes','word/endnotes','word/header','word/footer','word/comments')) and n.endswith('.xml')]
    content={name:xml(package.read(name)) for name in names};used=set();roles=[]
    for section in document.findall('.//w:sectPr',NS):
        current=[]
        for ref in section:
            if ref.tag not in ('{'+W+'}headerReference','{'+W+'}footerReference'):continue
            name=rels.get(ref.get('{'+R+'}id'));used.add(name)
            current.append((etree.QName(ref).localname,ref.get('{'+W+'}type',''),protected_content(content[name]) if name in content else ('missing',name)))
        roles.append(sorted(current,key=lambda item:item[:2]))
    notes=[];other=[]
    for name,root in content.items():
        if name.startswith(('word/footnotes','word/endnotes')):
            for note in root:
                # Word may add its two empty separator definitions on SaveAs.
                kind=note.get('{'+W+'}type')
                allowed={'footnote','endnote','p','pPr','r','rPr','spacing','ind','separator','continuationSeparator'}
                if kind in ('separator','continuationSeparator') and not note.xpath('.//w:t',namespaces=NS) and all(etree.QName(n).localname in allowed for n in note.iter()):continue
                notes.append(protected_content(note))
        elif name not in used:other.append(protected_content(root))
    return dict(roles=roles,notes=sorted(notes,key=digest),other=sorted(other,key=digest))


def toc_cache(root):
    """Recognize complete TOC fields whose entry links resolve to same headings.

    Only numeric page caches and generated PAGEREF wrappers may vary. Unknown
    text, targets, nested fields, images and references make the range ineligible.
    """
    paragraphs=root.findall('.//w:p',NS);anchors={}
    for p in paragraphs:
        for mark in p.findall('.//w:bookmarkStart',NS):
            anchors.setdefault(mark.get('{'+W+'}name'),[]).append(p)
    stack=[];ranges=[]
    for index,p in enumerate(paragraphs):
        for n in p.iter():
            if n.tag=='{'+W+'}fldChar':
                kind=n.get('{'+W+'}fldCharType')
                if kind=='begin':stack.append(dict(start=index,instr='',nested=[]))
                elif kind=='end' and stack:
                    field=stack.pop();field['end']=index
                    if stack:stack[-1]['nested'].append(field)
                    elif command(field['instr']).startswith('TOC '):ranges.append(field)
            elif n.tag=='{'+W+'}instrText' and stack:stack[-1]['instr']+=n.text or ''
    result=[]
    for field in ranges:
        group=paragraphs[field['start']:field['end']+1];entries=[];valid=True;nested_commands=[]
        for p in group:
            links=p.findall('.//w:hyperlink',NS)
            if len(links)>1:valid=False
            for n in p.iter():
                if any(a.tag in ('{'+W+'}pPr','{'+W+'}rPr') for a in n.iterancestors()):continue
                if n.tag not in {'{'+W+'}'+name for name in ('p','pPr','r','rPr','hyperlink','bookmarkStart','bookmarkEnd','t','tab','fldChar','instrText','proofErr','lastRenderedPageBreak')}:valid=False
                if n.tag=='{'+W+'}t' and (n.text or '').strip() and not any(a.tag=='{'+W+'}hyperlink' for a in n.iterancestors()):valid=False
            for link in links:
                anchor=link.get('{'+W+'}anchor');targets=anchors.get(anchor,[])
                if len(targets)!=1 or link.get('{'+R+'}id'):valid=False;continue
                target=targets[0]
                # A cache may point only outside itself, to a heading paragraph.
                style=target.find('./w:pPr/w:pStyle',NS)
                style_id=style.get('{'+W+'}val','') if style is not None else ''
                if target in group or not (re.fullmatch(r'(?:Heading)?[1-9]',style_id) or style_id in ('SchoolReferences','SchoolAcknowledgements') or target.find('./w:pPr/w:outlineLvl',NS) is not None):valid=False;continue
                text='';page='';after_tab=False
                for n in link.iter():
                    if n.tag=='{'+W+'}tab':after_tab=True
                    elif n.tag=='{'+W+'}t':
                        if after_tab:page+=n.text or ''
                        else:text+=n.text or ''
                title=re.sub(r'\s+','',''.join(target.xpath('.//w:t/text()',namespaces=NS)))
                if re.sub(r'\s+','',text)!=title or not re.fullmatch(r'[0-9IVXLCDMivxlcdm]+',page.strip()):valid=False
                instr=command(''.join(link.xpath('.//w:instrText/text()',namespaces=NS)))
                if instr and instr!='PAGEREF '+anchor+' \\h':valid=False
                if instr:nested_commands.append(instr)
                # Word rewrites PATOC/_Toc links, but retains the renderer's PA
                # heading bookmark. Equal titles alone do not identify a target.
                stable=sorted(n.get('{'+W+'}name','') for n in target.findall('.//w:bookmarkStart',NS) if re.fullmatch(r'PA\d{8}',n.get('{'+W+'}name','')))
                if any(len(anchors.get(name,[]))!=1 for name in stable):valid=False
                entries.append(dict(title=title,target=stable or [anchor]))
        if any(command(n['instr']).split(' ',1)[0]!='PAGEREF' or n['nested'] for n in field['nested']):valid=False
        if [command(n['instr']) for n in field['nested']]!=nested_commands:valid=False
        if valid and entries:
            result.append(dict(command=command(field['instr']),entries=entries,paths=[root.getroottree().getpath(p) for p in group]))
    return result
