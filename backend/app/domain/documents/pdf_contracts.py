"""Frozen physical-page PDF contract."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
LEGACY_PARSER_VERSION='pdfplumber-0.11.10-text-v1'
PARSER_VERSION='pdfplumber-0.11.10-evidence-v2'
PROCESS_SETTINGS=dict(timeout_seconds=60,cpu_seconds=30,memory_bytes=536870912,max_output_bytes=8388608)
class Model(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,allow_inf_nan=False)
class PdfSettings(Model):
    max_upload_bytes:int=Field(default=10485760,gt=0,le=10485760)
    max_pages:int=Field(default=100,gt=0,le=100)
    max_json_bytes:int=Field(default=4194304,gt=0,le=4194304)
PDF_SETTINGS={'pdf':PdfSettings().model_dump(),'process':PROCESS_SETTINGS.copy()}
class PdfWarning(Model):
    code:str
    message:str
    count:int
class PdfSource(Model):
    page_number:int
    bbox:list[float]=Field(min_length=4,max_length=4)
    label:str
class PdfText(Model):
    kind:Literal['text']='text'
    id:str
    text:str
    source:PdfSource
class PdfCell(Model):
    row:int
    column:int
    text:str|None
    bbox:list[float]|None=Field(min_length=4,max_length=4)
class PdfTable(Model):
    kind:Literal['table']='table'
    id:str
    source:PdfSource
    rows:int
    columns:int
    cells:list[PdfCell]
    candidate:Literal[True]=True
class PdfPage(Model):
    page_number:int
    width:float
    height:float
    rotation:int
    bbox:list[float]=Field(min_length=4,max_length=4)
    text_status:Literal['text','no_extractable_text']
    text_blocks:list[PdfText]
    tables:list[PdfTable]
    warnings:list[PdfWarning]
class PdfCounts(Model):
    pages:int
    text_blocks:int
    tables:int
    cells:int
    pages_without_text:int
class PdfDocument(Model):
    schema_version:Literal[1]=1
    kind:Literal['pdf_document']='pdf_document'
    filename:str
    parser_version:Literal['pdfplumber-0.11.10-text-v1']
    pages:list[PdfPage]
    warnings:list[PdfWarning]
    counts:PdfCounts
class PdfEmbeddedImage(Model):
    id:str
    source:PdfSource
    pixel_width:int=Field(ge=0)
    pixel_height:int=Field(ge=0)

class PdfPageV2(PdfPage):
    embedded_images:list[PdfEmbeddedImage]=Field(max_length=100)

class PdfCountsV2(PdfCounts):
    embedded_images:int=Field(ge=0,le=100)

class PdfDocumentV2(PdfDocument):
    parser_version:Literal['pdfplumber-0.11.10-evidence-v2']
    pages:list[PdfPageV2]
    counts:PdfCountsV2

    @model_validator(mode='after')
    def coherent_evidence(self):
        expected=dict(pages=len(self.pages),text_blocks=sum(len(p.text_blocks) for p in self.pages),
            tables=sum(len(p.tables) for p in self.pages),cells=sum(len(t.cells) for p in self.pages for t in p.tables),
            pages_without_text=sum(p.text_status=='no_extractable_text' for p in self.pages),
            embedded_images=sum(len(p.embedded_images) for p in self.pages))
        if self.counts.model_dump()!=expected or [p.page_number for p in self.pages]!=list(range(1,len(self.pages)+1)):
            raise ValueError('PDF evidence counts or physical pages differ')
        ids=[]
        for page in self.pages:
            for block in [*page.text_blocks,*page.tables,*page.embedded_images]:
                ids.append(block.id)
                x0,y0,x1,y1=block.source.bbox
                if block.source.page_number!=page.page_number or x0>x1 or y0>y1:
                    raise ValueError('PDF source geometry differs from its page')
        if len(set(ids))!=len(ids):raise ValueError('Duplicate PDF evidence identity')
        return self

class PdfParseResult(Model):
    document:PdfDocumentV2|PdfDocument
