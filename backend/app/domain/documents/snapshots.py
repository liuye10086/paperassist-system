"""Strict frozen Word input; Excel snapshots remain unchanged."""
from typing import Literal
from pydantic import Field, field_validator
from app.domain.file_parsing import StrictModel, ParseProject
from app.domain.documents.contracts import DocxSettings, DOCX_SETTINGS

class DocxFile(StrictModel):
    id: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    size_bytes: int = Field(ge=1, le=10485760)
    file_type: Literal['docx']
    storage_backend: Literal['local']
    object_key: str = Field(min_length=1)

class DocxProcess(StrictModel):
    timeout_seconds: Literal[60]
    cpu_seconds: Literal[30]
    memory_bytes: Literal[536870912]
    max_output_bytes: Literal[33554432]
    @field_validator('*', mode='before')
    @classmethod
    def integer_limit(cls, value):
        if type(value) is not int:
            raise ValueError('Integer limits required')
        return value

class DocxParseSettings(StrictModel):
    docx: DocxSettings
    process: DocxProcess

class DocxFileSnapshot(StrictModel):
    schema_version: Literal[1]
    kind: Literal['docx_document']
    project: ParseProject
    file: DocxFile
    parse_id: str = Field(min_length=1)
    parse_version: int = Field(ge=1, strict=True)
    parser_version: Literal['openxml-docx-v1']
    settings: DocxParseSettings
    @field_validator('settings', mode='before')
    @classmethod
    def frozen_settings(cls, value):
        if not isinstance(value,dict) or value != DOCX_SETTINGS:
            raise ValueError('Exact frozen Word settings required')
        return value

    @field_validator('schema_version', mode='before')
    @classmethod
    def integer_schema(cls, value):
        if type(value) is not int:
            raise ValueError('Integer schema required')
        return value


class PdfFile(DocxFile):
    file_type: Literal['pdf']

class PdfProcess(DocxProcess):
    max_output_bytes: Literal[8388608]

from app.domain.documents.pdf_contracts import PdfSettings, PDF_SETTINGS

class PdfParseSettings(StrictModel):
    pdf: PdfSettings
    process: PdfProcess

class PdfFileSnapshot(DocxFileSnapshot):
    kind: Literal['pdf_document']
    file: PdfFile
    parser_version: Literal['pdfplumber-0.11.10-text-v1', 'pdfplumber-0.11.10-evidence-v2']
    settings: PdfParseSettings

    @field_validator('settings', mode='before')
    @classmethod
    def frozen_settings(cls, value):
        if not isinstance(value,dict) or value != PDF_SETTINGS:
            raise ValueError('Exact frozen PDF settings required')
        return value
