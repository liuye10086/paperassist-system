from typing import Literal
from urllib.parse import quote
from fastapi import APIRouter,Response
from fastapi.responses import Response as RawResponse
from app.api.dataset_preparation import Store
from app.domain.layout_exports.contracts import LayoutCreateRequest,LayoutRetryRequest
from app.domain.layout_exports.service import LayoutExportService
router=APIRouter(prefix='/api/v1/projects/{project_id}/layout-exports',tags=['排版导出'])
@router.get('')
def listing(project_id:str,store:Store,source_kind:Literal['report','collection_report','manuscript_export']|None=None,source_id:str|None=None): return LayoutExportService(store).list(project_id,source_kind,source_id)
@router.post('',status_code=201)
def create(project_id:str,request:LayoutCreateRequest,response:Response,store:Store):
    result,response.status_code=LayoutExportService(store).create(project_id,request)
    return result
@router.get('/config')
def config(project_id:str,store:Store): return LayoutExportService(store).config(project_id)
@router.get('/sources')
def sources(project_id:str,store:Store): return LayoutExportService(store).sources(project_id)
@router.get('/sources/{source_kind}/{source_id}/catalog')
def catalog(project_id:str,source_kind:Literal['report','collection_report','manuscript_export'],source_id:str,store:Store):
    return LayoutExportService(store).catalog(project_id,source_kind,source_id)
@router.get('/{export_id}')
def get(project_id:str,export_id:str,store:Store): return LayoutExportService(store).get(project_id,export_id)
@router.post('/{export_id}/retry',status_code=201)
def retry(project_id:str,export_id:str,request:LayoutRetryRequest,response:Response,store:Store):
    result,response.status_code=LayoutExportService(store).retry(project_id,export_id,request.request_key)
    return result
@router.get('/{export_id}/download')
def download(project_id:str,export_id:str,store:Store):
    meta,raw=LayoutExportService(store).download(project_id,export_id)
    return RawResponse(raw,media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(meta['filename'],safe='')})
