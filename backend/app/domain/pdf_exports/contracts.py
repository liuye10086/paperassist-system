from typing import Literal
from pydantic import BaseModel,ConfigDict
WORKFLOW='pdf_export_v1'
class PdfInputVersion(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    kind: Literal['pdf_export']='pdf_export'
    export_id: str
    source_kind: Literal['report','collection_report','manuscript_export','layout_export','review_document_export','research_report']
    source_id: str
    source_sha256: str
    workflow_version: Literal['pdf_export_v1']='pdf_export_v1'
