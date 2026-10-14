"""Frozen Word structure and bounded transport contracts."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

PARSER_VERSION = 'openxml-docx-v1'
PROCESS_SETTINGS = dict(timeout_seconds=60,cpu_seconds=30,memory_bytes=536870912,max_output_bytes=33554432)
class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
class DocxSettings(Model):
    max_upload_bytes:int = Field(default=10485760,gt=0,le=10485760)
    max_uncompressed_bytes:int = Field(default=67108864,gt=0,le=67108864)
    max_json_bytes:int = Field(default=4194304,gt=0,le=4194304)
    max_image_bytes:int = Field(default=16777216,gt=0,le=16777216)
    max_images:int = Field(default=100,gt=0,le=100)
    max_blocks:int = Field(default=20000,gt=0,le=20000)
    max_cells:int = Field(default=100000,gt=0,le=100000)
    max_depth:int = Field(default=20,gt=0,le=20)
DOCX_SETTINGS = {'docx':DocxSettings().model_dump(),'process':PROCESS_SETTINGS.copy()}
class Source(Model):
    part:str
    path:str
    label:str
class Run(Model):
    text:str
    style_id:str|None = None
    properties:dict[str,str] = Field(default_factory=dict)
class Paragraph(Model):
    kind:Literal['paragraph'] = 'paragraph'
    id:str
    source:Source
    text:str
    style_id:str|None = None
    heading_level:int|None = None
    properties:dict[str,str] = Field(default_factory=dict)
    runs:list[Run] = Field(default_factory=list)
    image_ids:list[str] = Field(default_factory=list)
class Cell(Model):
    row:int
    column:int
    row_span:int = 1
    column_span:int = 1
    source:Source
    blocks:list['Paragraph|Table'] = Field(default_factory=list)
class Table(Model):
    kind:Literal['table'] = 'table'
    id:str
    source:Source
    rows:int
    columns:int
    cells:list[Cell]
    style_id:str|None = None
    properties:dict[str,str] = Field(default_factory=dict)
class Style(Model):
    id:str
    name:str
    type:str
    based_on:str|None = None
    properties:dict[str,str] = Field(default_factory=dict)
class Section(Model):
    source:Source
    properties:dict[str,str] = Field(default_factory=dict)
class Image(Model):
    id:str
    part:str
    mime:str
    size_bytes:int
    sha256:str
    inline_preview:bool
class Warning(Model):
    code:str
    message:str
    count:int
class Counts(Model):
    paragraphs:int
    tables:int
    cells:int
    images:int
class DocxDocument(Model):
    schema_version:Literal[1] = 1
    kind:Literal['docx_document'] = 'docx_document'
    filename:str
    parser_version:str
    blocks:list[Paragraph|Table]
    styles:list[Style]
    sections:list[Section]
    images:list[Image]
    warnings:list[Warning]
    counts:Counts
class DocxParseResult(Model):
    document:DocxDocument
    image_payloads:dict[str,str]
Cell.model_rebuild()
Table.model_rebuild()
