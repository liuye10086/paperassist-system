"""Pure bounded OpenXML extraction. The original package remains authoritative."""
import base64
import hashlib
import io
import json
import posixpath
import zipfile
from collections import Counter
from lxml import etree
from app.core.exceptions import StorageError
from app.domain.documents.contracts import *

W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
A='http://schemas.openxmlformats.org/drawingml/2006/main'
NS={'w':W,'r':R,'a':A}
MAIN='application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'
def fail(code='invalid_document'):
    raise StorageError(code, 'Word 文件无效、损坏或不符合解析限制。' if code=='invalid_document' else 'Word 文档超过解析规模限制。',422)
def val(node,name,default=None):
    child=node.find('w:'+name,NS)
    return child.get('{'+W+'}val',default) if child is not None else default
def props(node):
    """Explicit evidence only: preserve container paths and empty OnOff values."""
    if node is None:return {}
    on_off={'b','bCs','i','iCs','caps','smallCaps','strike','dstrike','outline',
            'shadow','emboss','imprint','vanish','webHidden','rtl','cs','snapToGrid',
            'keepNext','keepLines','pageBreakBefore','widowControl','contextualSpacing',
            'suppressLineNumbers','suppressAutoHyphens','bidi','mirrorIndents',
            'noProof','specVanish','oMath','qFormat','semiHidden','unhideWhenUsed',
            'locked','autoRedefine','hidden','cantSplit','tblHeader'}
    result={}
    def visit(element,path):
        tag=etree.QName(element).localname
        for key,value in element.attrib.items():
            result[path+'.'+etree.QName(key).localname]=value
        if tag in on_off and element.get('{'+W+'}val') is None:
            result[path+'.val']='true'
        frequencies=Counter(etree.QName(c).localname for c in element)
        occurrences=Counter()
        for child in element:
            name=etree.QName(child).localname;occurrences[name]+=1
            component=name+(f'[{occurrences[name]}]' if frequencies[name]>1 else '')
            visit(child,(path+'.' if path else '')+component)
    # Run/paragraph properties are already scoped by their owner. Styles/sections
    # keep their nested pPr/rPr containers to distinguish explicit evidence.
    root_name=etree.QName(node).localname
    if root_name.endswith('Pr') and root_name not in ('sectPr',):
        for child in node:
            visit(child,etree.QName(child).localname)
    else:
        for key,value in node.attrib.items():result[root_name+'.'+etree.QName(key).localname]=value
        frequencies=Counter(etree.QName(c).localname for c in node);seen=Counter()
        for child in node:
            name=etree.QName(child).localname;seen[name]+=1
            visit(child,name+(f'[{seen[name]}]' if frequencies[name]>1 else ''))
    return result
def parse_docx(content:bytes,filename:str,settings:dict)->DocxParseResult:
    limits=DocxSettings.model_validate(settings['docx'])
    if not content: fail('empty_file')
    if len(content)>limits.max_upload_bytes: fail('file_too_large')
    if not filename.lower().endswith('.docx'):fail()
    try:
        z=zipfile.ZipFile(io.BytesIO(content)); infos=z.infolist()
        names=[i.filename for i in infos]
        if len(names)!=len(set(names)):fail()
        if any(i.flag_bits&1 or i.filename.startswith('/') or '\\' in i.filename or any(p in ('..','.') for p in i.filename.split('/')) for i in infos):fail()
        if sum(i.file_size for i in infos)>limits.max_uncompressed_bytes:fail('document_too_large')
        parts={i.filename:z.read(i) for i in infos}
        if sum(map(len,parts.values()))>limits.max_uncompressed_bytes:fail('document_too_large')
        def xml(name):
            raw=parts[name]
            if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():fail()
            return etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False,huge_tree=False))
        ct=xml('[Content_Types].xml')
        overrides={n.get('PartName').lstrip('/'):n.get('ContentType') for n in ct if etree.QName(n).localname=='Override'}
        defaults={n.get('Extension'):n.get('ContentType') for n in ct if etree.QName(n).localname=='Default'}
        if overrides.get('word/document.xml')!=MAIN or any('macro' in v.lower() for v in overrides.values()) or any('vbaproject' in n.lower() for n in names):fail()
        root=xml('word/document.xml'); tree=root.getroottree()
        rels={}
        if 'word/_rels/document.xml.rels' in parts:
            rels={n.get('Id'):n for n in xml('word/_rels/document.xml.rels')}
        counts=Counter(); warnings=Counter(); images=[]; payloads={}; image_parts={}
        def source(n,label):return Source(part='word/document.xml',path=tree.getpath(n),label=label)
        def picture(rid):
            rel=rels.get(rid)
            if rel is None:warnings['missing_image']+=1;return None
            if rel.get('TargetMode')=='External':warnings['external_images']+=1;return None
            target=rel.get('Target','')
            part=posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join('word',target))
            if not part.startswith('word/') or part not in parts:warnings['missing_image']+=1;return None
            if part in image_parts:return image_parts[part]
            raw=parts[part]; mime=overrides.get(part,defaults.get(part.rsplit('.',1)[-1],'application/octet-stream'))
            identifier='image-'+str(len(images)+1)
            images.append(Image(id=identifier,part=part,mime=mime,size_bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),inline_preview=mime in ('image/png','image/jpeg') and (raw.startswith(b'\x89PNG\r\n\x1a\n') if mime=='image/png' else raw.startswith(b'\xff\xd8\xff'))))
            payloads[identifier]=base64.b64encode(raw).decode('ascii');image_parts[part]=identifier
            if len(images)>limits.max_images or sum(i.size_bytes for i in images)>limits.max_image_bytes:fail('document_too_large')
            return identifier
        def blocks(parent,depth=0,label='正文'):
            if depth>limits.max_depth:fail('document_too_large')
            result=[]
            for n in parent:
                tag=etree.QName(n).localname
                if tag not in ('p','tbl'):continue
                counts['blocks']+=1
                if counts['blocks']>limits.max_blocks:fail('document_too_large')
                identifier='block-'+str(counts['blocks'])
                if tag=='p':
                    counts['paragraphs']+=1;pr=n.find('w:pPr',NS);style=val(pr,'pStyle') if pr is not None else None
                    runs=[];pics=[]
                    for run in n.iter('{'+W+'}r'):
                        # Do not accept tracked insertions/deletions or text box content.
                        if any(etree.QName(a).localname in ('ins','del','moveFrom','moveTo','txbxContent') for a in run.iterancestors()):continue
                        text=''.join(c.text or '' if etree.QName(c).localname=='t' else '\t' if etree.QName(c).localname=='tab' else '\n' if etree.QName(c).localname in ('br','cr') else '' for c in run)
                        rp=run.find('w:rPr',NS);runs.append(Run(text=text,style_id=val(rp,'rStyle') if rp is not None else None,properties=props(rp)))
                        for b in run.iter('{'+A+'}blip'):
                            image_id=picture(b.get('{'+R+'}embed') or b.get('{'+R+'}link'))
                            if image_id:pics.append(image_id)
                    level=val(pr,'outlineLvl') if pr is not None else None
                    if level is None and style and style.lower().startswith('heading') and style[7:].isdigit():level=str(int(style[7:])-1)
                    result.append(Paragraph(id=identifier,source=source(n,label+'段落 '+str(counts['paragraphs'])),text=''.join(r.text for r in runs),runs=runs,style_id=style,heading_level=int(level)+1 if level is not None and 0<=int(level)<=8 else None,properties=props(pr),image_ids=pics))
                else:
                    counts['tables']+=1;table_label=label+'表格 '+str(counts['tables']);cells=[];active={};rows=n.findall('w:tr',NS);maxcol=0
                    for row,tr in enumerate(rows):
                        trpr=tr.find('w:trPr',NS);col=int(val(trpr,'gridBefore','0')) if trpr is not None else 0
                        if col<0 or col>limits.max_cells:fail()
                        next_active={};horizontal=None
                        for tc in tr.findall('w:tc',NS):
                            counts['cells']+=1
                            if counts['cells']>limits.max_cells:fail('document_too_large')
                            pr=tc.find('w:tcPr',NS);span=int(val(pr,'gridSpan','1')) if pr is not None else 1
                            if span<1 or col+span>limits.max_cells:fail()
                            merge=pr.find('w:vMerge',NS) if pr is not None else None
                            hmerge=pr.find('w:hMerge',NS) if pr is not None else None
                            if hmerge is not None and hmerge.get('{'+W+'}val')!='restart':
                                if horizontal is None:fail()
                                if horizontal.row==row:horizontal.column_span+=span
                                horizontal.blocks.extend(blocks(tc,depth+1,table_label+'合并单元格'))
                                col+=span
                                continue
                            if merge is not None and merge.get('{'+W+'}val')!='restart' and col in active:
                                cell=active[col];cell.row_span+=1;next_active[col]=cell
                            else:
                                cell=Cell(row=row,column=col,column_span=span,source=source(tc,table_label+f'，第 {row+1} 行第 {col+1} 列'),blocks=blocks(tc,depth+1,table_label+'单元格'))
                                cells.append(cell)
                                if merge is not None:next_active[col]=cell
                            horizontal=cell if hmerge is not None else None
                            col+=span
                        active=next_active;maxcol=max(maxcol,col)
                    pr=n.find('w:tblPr',NS)
                    result.append(Table(id=identifier,source=source(n,table_label),rows=len(rows),columns=maxcol,cells=cells,style_id=val(pr,'tblStyle') if pr is not None else None,properties=props(pr)))
            return result
        body=root.find('w:body',NS)
        if body is None:fail()
        extracted=blocks(body)
        for n in root.iter():
            tag=etree.QName(n).localname
            if tag in ('ins','del','moveFrom','moveTo'):warnings['revisions']+=1
            if tag=='txbxContent':warnings['textboxes']+=1
            if tag=='imagedata':warnings['legacy_images']+=1
            if tag in ('oMath','oMathPara'):warnings['equations']+=1
            if tag in ('sdt','customXml','altChunk'):warnings['unsupported_blocks']+=1
            if tag in ('fldChar','fldSimple'):warnings['fields']+=1
        for part in parts:
            if part.startswith(('word/header','word/footer','word/footnotes','word/endnotes')) and part.endswith('.xml'):warnings['other_parts']+=1
        styles=[]
        if 'word/styles.xml' in parts:
            for n in xml('word/styles.xml').findall('w:style',NS):
                styles.append(Style(id=n.get('{'+W+'}styleId',''),name=val(n,'name',''),type=n.get('{'+W+'}type',''),based_on=val(n,'basedOn'),properties=props(n)))
        messages={'legacy_images':'旧式 VML 图片未提取。','revisions':'修订内容未自动接受或提取。','textboxes':'文本框内容未提取。','equations':'公式未提取或计算。','external_images':'外链图片未下载。','missing_image':'图片引用缺失。','unsupported_blocks':'存在未提取的内容容器。','fields':'域未重新计算。','other_parts':'页眉页脚或脚注尾注未提取。'}
        document=DocxDocument(filename=filename,parser_version=PARSER_VERSION,blocks=extracted,styles=styles,sections=[Section(source=source(n,'分节 '+str(i+1)),properties=props(n)) for i,n in enumerate(root.iter('{'+W+'}sectPr'))],images=images,warnings=[Warning(code=k,message=messages[k],count=v) for k,v in sorted(warnings.items())],counts=Counts(paragraphs=counts['paragraphs'],tables=counts['tables'],cells=counts['cells'],images=len(images)))
        if len(document.model_dump_json().encode())>limits.max_json_bytes:fail('document_too_large')
        return DocxParseResult(document=document,image_payloads=payloads)
    except StorageError:raise
    except (Exception,) as exc:
        raise StorageError('invalid_document','文件不是有效的未加密 .docx 文档。',422) from exc
