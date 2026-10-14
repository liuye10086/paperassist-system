from typing import Annotated
from fastapi import APIRouter, Depends, Query
from pydantic import BeforeValidator
from app.adapters.storage import ProjectStore, get_request_project_store
from app.api.tasks import decimal_query_integer
from app.domain.parsed_evidence.contracts import Evidence
from app.domain.parsed_evidence.service import ParsedEvidenceService

router=APIRouter(prefix='/api/v1/projects/{project_id}/files/{file_id}',tags=['解析证据'])
Store=Annotated[ProjectStore,Depends(get_request_project_store)]
Page=Annotated[int,Query(ge=1,le=1000000),BeforeValidator(decimal_query_integer)]

@router.get('/document-versions/{version_id}/evidence',response_model=Evidence)
def document(project_id:str,file_id:str,version_id:str,store:Store,page:Page=1):
    return ParsedEvidenceService(store).document(project_id,file_id,version_id,page)

@router.get('/dataset-versions/{version_id}/evidence',response_model=Evidence)
def dataset(project_id:str,file_id:str,version_id:str,store:Store,page:Page=1):
    return ParsedEvidenceService(store).dataset(project_id,file_id,version_id,page)

@router.get('/prepared-dataset-versions/{version_id}/evidence',response_model=Evidence)
def prepared(project_id:str,file_id:str,version_id:str,store:Store,page:Page=1):
    return ParsedEvidenceService(store).prepared(project_id,file_id,version_id,page)
