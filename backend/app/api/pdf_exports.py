from typing import Literal
from urllib.parse import quote
from fastapi import APIRouter
from fastapi.responses import Response as RawResponse
from app.api.dataset_preparation import Store
from app.domain.pdf_exports.service import PdfExportService
router=APIRouter(prefix='/api/v1/projects/{project_id}/pdf-exports',tags=['历史PDF导出'])
@router.get('')
def listing(project_id:str,store:Store,source_kind:Literal['report','collection_report','manuscript_export','layout_export','review_document_export','research_report']|None=None,source_id:str|None=None): return PdfExportService(store).list(project_id,source_kind,source_id)
@router.get('/{export_id}')
def get(project_id:str,export_id:str,store:Store): return PdfExportService(store).get(project_id,export_id)
@router.get('/{export_id}/download')
def download(project_id:str,export_id:str,store:Store):
    meta,raw=PdfExportService(store).download(project_id,export_id)
    return RawResponse(raw,media_type='application/pdf',headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(meta['filename'],safe='')})
