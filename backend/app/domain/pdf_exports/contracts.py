from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
WORKFLOW='pdf_export_v1'
class PdfCreateRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    source_kind: Literal['report','collection_report','manuscript_export','layout_export']
    source_id: str=Field(min_length=1,max_length=128,pattern=r'^[A-Za-z0-9_-]+$')
    request_key: str=Field(min_length=1,max_length=128,pattern=r'^[!-~]+$')
class PdfRetryRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    request_key: str=Field(min_length=1,max_length=128,pattern=r'^[!-~]+$')
class PdfInputVersion(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    kind: Literal['pdf_export']='pdf_export'
    export_id: str
    source_kind: Literal['report','collection_report','manuscript_export','layout_export']
    source_id: str
    source_sha256: str
    workflow_version: Literal['pdf_export_v1']='pdf_export_v1'
