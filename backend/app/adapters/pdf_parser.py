"""Local text and ruled-table extraction; never renders or performs OCR."""
import io
import re
import pdfplumber
from pdfminer.pdfparser import PDFParser
from pdfminer.pdfdocument import PDFDocument, PDFPasswordIncorrect
from app.core.exceptions import StorageError
from app.domain.documents.pdf_contracts import (
    PDF_SETTINGS, PROCESS_SETTINGS, PARSER_VERSION, PdfSettings, PdfWarning,
    PdfSource, PdfText, PdfCell, PdfTable, PdfPage, PdfCounts, PdfDocument, PdfParseResult,
    LEGACY_PARSER_VERSION, PdfEmbeddedImage, PdfPageV2, PdfCountsV2, PdfDocumentV2,
)

def validate_inputs(content,filename,settings):
    try:
        if type(settings) is not dict or set(settings)!={'pdf','process'} or settings['process']!=PROCESS_SETTINGS or any(type(v) is not int for v in settings['process'].values()):raise ValueError()
        if type(settings['pdf']) is not dict or set(settings['pdf'])!=set(PdfSettings.model_fields):raise ValueError()
        limits=PdfSettings.model_validate(settings['pdf'])
        if type(content) is not bytes or type(filename) is not str or not 0<len(filename)<=1024:raise ValueError()
    except Exception:raise StorageError('parse_environment_unavailable','PDF解析设置无效。') from None
    if not content:raise StorageError('empty_file','上传的文件为空。',422)
    if len(content)>limits.max_upload_bytes:raise StorageError('file_too_large','上传文件超过大小限制。',422)
    return limits

def warning(code,message,count=1):return PdfWarning(code=code,message=message,count=count)
def bbox(value):return [float(v) for v in value]

def parse_pdf(content:bytes,filename:str,settings:dict,*,parser_version=PARSER_VERSION)->PdfParseResult:
    limits=validate_inputs(content,filename,settings)
    if parser_version not in (PARSER_VERSION,LEGACY_PARSER_VERSION):
        raise StorageError('parse_environment_unavailable','PDF解析器版本无效。')
    evidence=parser_version==PARSER_VERSION
    try:
        # Inspect the real trailer before password handling: even empty-password PDFs are out of scope.
        parser=PDFParser(io.BytesIO(content))
        try:raw=PDFDocument(parser)
        except PDFPasswordIncorrect:raise StorageError('encrypted_document','暂不支持加密PDF。',422) from None
        if raw.encryption:raise StorageError('encrypted_document','暂不支持加密PDF。',422)
        pages=[];json_size=0;image_count=0
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            if len(pdf.pages)>limits.max_pages:raise StorageError('document_too_large','PDF页数超过限制。',422)
            for number,page in enumerate(pdf.pages,1):
                texts=[];tables=[];warnings=[]
                for index,line in enumerate(page.extract_text_lines(layout=False,strip=False),1):
                    texts.append(PdfText(id=f'p{number}-text{index}',text=line['text'],source=PdfSource(page_number=number,bbox=bbox([line['x0'],line['top'],line['x1'],line['bottom']]),label=f'第{number}页文本块{index}')))
                if texts:
                    warnings.append(warning('reading_order_candidate','文字为本地几何阅读顺序候选，多栏顺序请核对原件。'))
                    undecoded=sum(len(re.findall(r'\(cid:\d+\)|\ufffd',t.text)) for t in texts)
                    if undecoded:warnings.append(warning('undecoded_characters','存在未解码字符，文字内容请核对原件。',undecoded))
                else:warnings.append(warning('no_extractable_text','本页无可提取文字；可能为空白、图像或字体映射问题。'))
                for index,table in enumerate(page.find_tables({'vertical_strategy':'lines','horizontal_strategy':'lines'}),1):
                    values=table.extract();rows=table.rows;columns=max((len(r.cells) for r in rows),default=0)
                    cells=[PdfCell(row=r+1,column=c+1,text=values[r][c],bbox=bbox(region) if region is not None else None) for r,row in enumerate(rows) for c,region in enumerate(row.cells)]
                    tables.append(PdfTable(id=f'p{number}-table{index}',source=PdfSource(page_number=number,bbox=bbox(table.bbox),label=f'第{number}页候选表格{index}'),rows=len(rows),columns=columns,cells=cells))
                if tables:warnings.append(warning('table_candidate','有边框表格为结构候选；表格与页文字是重叠读取视图，请核对合并及行列。',len(tables)))
                images=[]
                if evidence:
                    for index,image in enumerate(page.images,1):
                        image_count+=1
                        if image_count>100:raise StorageError('document_too_large','PDF内嵌图片位置超过数量限制。',422)
                        images.append(PdfEmbeddedImage(id=f'p{number}-image{index}',
                            source=PdfSource(page_number=number,bbox=bbox([image['x0'],image['top'],image['x1'],image['bottom']]),label=f'第{number}页内嵌图片{index}'),
                            pixel_width=int(image['srcsize'][0]),pixel_height=int(image['srcsize'][1])))
                    warnings.append(warning('image_pixels_not_saved','仅提取内嵌图片位置；像素与矢量图内容未提取，请核对原件。'))
                value=(PdfPageV2 if evidence else PdfPage)(page_number=number,width=float(page.width),height=float(page.height),rotation=page.rotation,bbox=bbox(page.bbox),text_status='text' if texts else 'no_extractable_text',text_blocks=texts,tables=tables,warnings=warnings,**({'embedded_images':images} if evidence else {}))
                json_size+=len(value.model_dump_json().encode('utf-8'))
                if json_size>limits.max_json_bytes:raise StorageError('document_too_large','PDF解析结果超过大小限制。',422)
                pages.append(value);page.close()
        counts=(PdfCountsV2 if evidence else PdfCounts)(pages=len(pages),text_blocks=sum(len(p.text_blocks) for p in pages),tables=sum(len(p.tables) for p in pages),cells=sum(len(t.cells) for p in pages for t in p.tables),pages_without_text=sum(p.text_status=='no_extractable_text' for p in pages),**({'embedded_images':image_count} if evidence else {}))
        doc=(PdfDocumentV2 if evidence else PdfDocument)(filename=filename,parser_version=parser_version,pages=pages,warnings=[],counts=counts)
        if len(doc.model_dump_json().encode('utf-8'))>limits.max_json_bytes:raise StorageError('document_too_large','PDF解析结果超过大小限制。',422)
        return PdfParseResult(document=doc)
    except StorageError:raise
    except MemoryError:raise StorageError('parse_resource_limit','PDF解析达到资源限制。') from None
    except Exception:raise StorageError('invalid_document','PDF损坏或无法提取，请核对原件。',422) from None
