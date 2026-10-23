from urllib.parse import quote
from fastapi import APIRouter,Response
from fastapi.responses import Response as RawResponse
from app.api.dataset_preparation import Store,Key
from app.domain.review_rounds.document_contracts import DocumentCreate,DocumentVersion,DocumentConfirm,DocumentExport
from app.domain.review_rounds.documents import ReviewDocumentService
from app.domain.review_rounds.document_exports import ReviewDocumentExportService

router=APIRouter(prefix='/api/v1/projects/{project_id}/reviews',tags=['独立返修文档'])

@router.get('/revisions/{revision_id}/documents')
def listing(project_id:str,revision_id:str,store:Store):return ReviewDocumentService(store).listing(project_id,revision_id)

@router.post('/revisions/{revision_id}/documents',status_code=201)
def create(project_id:str,revision_id:str,request:DocumentCreate,response:Response,store:Store,idempotency_key:Key):
    result,response.status_code=ReviewDocumentService(store).create(project_id,revision_id,request,idempotency_key);return result

@router.get('/documents/{document_id}')
def get(project_id:str,document_id:str,store:Store):return ReviewDocumentService(store).get(project_id,document_id)

@router.post('/documents/{document_id}/versions',status_code=201)
def version(project_id:str,document_id:str,request:DocumentVersion,response:Response,store:Store,idempotency_key:Key):
    result,response.status_code=ReviewDocumentService(store).version(project_id,document_id,request,idempotency_key);return result

@router.post('/documents/{document_id}/confirm')
def confirm(project_id:str,document_id:str,request:DocumentConfirm,store:Store,idempotency_key:Key):return ReviewDocumentService(store).confirm(project_id,document_id,request,idempotency_key)

@router.post('/documents/{document_id}/exports',status_code=202)
def export(project_id:str,document_id:str,request:DocumentExport,response:Response,store:Store,idempotency_key:Key):
    result,response.status_code=ReviewDocumentExportService(store).create(project_id,document_id,idempotency_key);return result

@router.get('/documents/{document_id}/exports')
def exports(project_id:str,document_id:str,store:Store):return ReviewDocumentExportService(store).listing(project_id,document_id)

@router.get('/document-exports/{export_id}')
def get_export(project_id:str,export_id:str,store:Store):return ReviewDocumentExportService(store).get(project_id,export_id)

@router.get('/document-exports/{export_id}/download')
def download(project_id:str,export_id:str,store:Store):
    meta,raw=ReviewDocumentExportService(store).download(project_id,export_id)
    return RawResponse(raw,media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(meta['filename'],safe='')})
