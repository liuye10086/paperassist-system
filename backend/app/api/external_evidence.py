from typing import Literal
from fastapi import APIRouter, Response
from app.api.dataset_preparation import Store,Key,Page
from app.domain.external_evidence.contracts import EvidenceRequest
from app.domain.external_evidence.service import ExternalEvidenceService

router=APIRouter(prefix='/api/v1/projects/{project_id}',tags=['外部材料来源'])


@router.get('/files/{file_id}/external-evidence-source')
def source(project_id:str,file_id:str,store:Store,source_kind:Literal['original','document_version','ocr_review_version']='original',version_id:str|None=None,page:Page=1):
    return ExternalEvidenceService(store).preview(project_id,file_id,source_kind,version_id,page)


@router.get('/external-evidence')
def list_versions(project_id:str,store:Store,page:Page=1,file_id:str|None=None):
    return ExternalEvidenceService(store).list(project_id,page,file_id)


@router.get('/external-evidence/{version_id}')
def version(project_id:str,version_id:str,store:Store):
    return ExternalEvidenceService(store).get(project_id,version_id)


@router.post('/external-evidence',status_code=201)
def create(project_id:str,request:EvidenceRequest,response:Response,store:Store,idempotency_key:Key):
    result,status=ExternalEvidenceService(store).create(project_id,request,idempotency_key)
    response.status_code=status
    return result
