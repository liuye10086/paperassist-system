"""Explicit versions for independent comparison and SCI response documents."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

WORKFLOW = 'review_document_export_v1'

class Request(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

class DocumentCreate(Request):
    kind: Literal['comparison', 'reply']
    language: Literal['zh-CN', 'en']

class TextEdit(Request):
    item_id: str = Field(min_length=1, max_length=256)
    text: str = Field(min_length=1, max_length=30000)

class DocumentVersion(Request):
    expected_version: int = Field(ge=1)
    items: list[TextEdit] = Field(min_length=1, max_length=500)
    language: Literal['zh-CN', 'en'] | None = None

class DocumentConfirm(Request):
    expected_version: int = Field(ge=1)

class DocumentExport(Request):
    pass

class ReviewDocumentInputVersion(Request):
    kind: Literal['review_document_export'] = 'review_document_export'
    export_id: str
    document_id: str
    document_sha256: str
    revision_id: str
    round_id: str
    workflow_version: Literal['review_document_export_v1'] = WORKFLOW
