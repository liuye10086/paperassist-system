from typing import Literal
from urllib.parse import quote
from fastapi import APIRouter,Response
from fastapi.responses import Response as RawResponse
from app.api.dataset_preparation import Store
from app.domain.pdf_exports.contracts import PdfCreateRequest,PdfRetryRequest
from app.domain.pdf_exports.service import PdfExportService
router=APIRouter(prefix='/api/v1/projects/{project_id}/pdf-exports',tags=['PDF导出'])
@router.get('')
def listing(project_id:str,store:Store,source_kind:Literal['report','collection_report','manuscript_export','layout_export']|None=None,source_id:str|None=None): return PdfExportService(store).list(project_id,source_kind,source_id)
@router.post('',status_code=201)
def create(project_id:str,request:PdfCreateRequest,response:Response,store:Store):
    result,response.status_code=PdfExportService(store).create(project_id,request)
    return result
@router.get('/{export_id}')
def get(project_id:str,export_id:str,store:Store): return PdfExportService(store).get(project_id,export_id)
@router.post('/{export_id}/retry',status_code=201)
def retry(project_id:str,export_id:str,request:PdfRetryRequest,response:Response,store:Store):
    result,response.status_code=PdfExportService(store).retry(project_id,export_id,request.request_key)
    return result
@router.get('/{export_id}/download')
def download(project_id:str,export_id:str,store:Store):
    meta,raw=PdfExportService(store).download(project_id,export_id)
    return RawResponse(raw,media_type='application/pdf',headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(meta['filename'],safe='')})
