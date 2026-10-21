from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from app.domain.document_layout import LayoutOptions

WORKFLOW = 'layout_docx_v1'
LAYOUT_VERSION = 'document_layout_v1'
SourceKind = Literal['report', 'collection_report', 'manuscript_export']


class RequiredLayoutOptions(LayoutOptions):
    source_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class LayoutCreateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    source_kind: SourceKind
    source_id: str = Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')
    request_key: str = Field(min_length=1, max_length=128, pattern=r'^[!-~]+$')
    layout: RequiredLayoutOptions


class LayoutRetryRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    request_key: str = Field(min_length=1, max_length=128, pattern=r'^[!-~]+$')


class LayoutInputVersion(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    kind: Literal['layout_docx'] = 'layout_docx'
    export_id: str
    source_kind: SourceKind
    source_id: str
    source_sha256: str
    workflow_version: Literal['layout_docx_v1'] = WORKFLOW
