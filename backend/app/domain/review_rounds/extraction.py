"""Lossless local document extraction; unsupported package content is blocked."""
from io import BytesIO
from zipfile import ZipFile
from lxml import etree
from app.domain.documents.service import DocumentService
from .planning import split_text,invalid

def preview(service,project,source):
    source=source.model_dump() if hasattr(source,'model_dump') else source
    text=source.get('text');warnings=[];locations=[];supported=True
    if source['format']=='text':
        if source.get('file_id') or source.get('document_version_id'):raise invalid('纯文本意见不能混入文档版本。')
    else:
        if not source.get('file_id') or not source.get('document_version_id') or source.get('text'):raise invalid('文档意见必须选择固定公共解析版本。')
        docs=DocumentService(service.assets);row=docs.load(project,source['file_id'],source['document_version_id'],True)
        _,document=docs.read(row)
        if document.kind not in ('docx_document','pdf_document'):raise invalid('不支持OCR意见，请核对后粘贴干净原文。')
        material=service.material(project,dict(kind='document_version',file_id=source['file_id'],id=source['document_version_id']))
        items=material['content']['items'];parts=[];position=0
        for item in items:
            value=item.get('text') or ''
            if not value.strip():continue
            parts.append(value);locations.append(dict(start=position,end=position+len(value),location=item.get('location') or dict(id=item.get('id'))));position+=len(value)+1
        text='\n'.join(parts)
        if document.kind=='docx_document':
            # These parser warnings prove omitted content, unlike formatting-only
            # notices such as fields not being recalculated.
            incomplete={'unsupported_blocks','equations','other_parts','revisions','textboxes'}
            for warning in document.warnings:
                if warning.code in incomplete:
                    warnings.append(f'DOCX提取不完整：{warning.message} 请清理后重新上传或粘贴完整原文。')
                    supported=False
            raw=service.assets.original(row['input_snapshot']['file'])
            if not isinstance(raw,bytes):raw=raw.read_bytes() if hasattr(raw,'read_bytes') else open(raw,'rb').read()
            with ZipFile(BytesIO(raw)) as package:
                for name in package.namelist():
                    if name.startswith('word/') and name.endswith('.xml'):
                        xml=etree.fromstring(package.read(name),parser=etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False))
                        if any(etree.QName(n).localname in ('ins','del','moveFrom','moveTo','commentReference','commentRangeStart','commentRangeEnd','txbxContent') for n in xml.iter()) or 'comments' in name.lower():
                            warnings.append('DOCX含修订、批注或文本框，无法保证完整提取；请接受/清理后重新上传或粘贴完整原文。');supported=False;break
        if not text.strip():warnings.append('未提取到完整文字；扫描PDF请核对后粘贴原文。');supported=False
        if document.kind=='pdf_document':
            data=document.model_dump();pages=data.get('pages',[])
            if any(not any(str(b.get('text','')).strip() for b in p.get('text_blocks',[])) for p in pages):warnings.append('PDF存在无可提取文字页面；请提供完整清洁文本。');supported=False
    if not isinstance(text,str) or not text.strip():return dict(original_text=text or '',segments=[],warnings=warnings,supported=False)
    return dict(original_text=text,segments=split_text(text,source.get('segments'),locations),warnings=warnings,supported=supported)
