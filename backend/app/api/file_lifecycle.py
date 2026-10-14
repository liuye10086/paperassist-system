"""Authenticated retention-only lifecycle routes."""
from typing import Annotated
from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import BeforeValidator
from app.adapters.storage import ProjectStore, get_request_project_store
from app.api.tasks import decimal_query_integer
from app.domain.file_lifecycle.contracts import Action, DeletionRequest
from app.domain.file_lifecycle.service import FileLifecycleService

router = APIRouter(prefix='/api/v1/projects/{project_id}/files/{file_id}/lifecycle', tags=['文件生命周期'])
Store = Annotated[ProjectStore, Depends(get_request_project_store)]
Page = Annotated[int, Query(ge=1,le=1000000), BeforeValidator(decimal_query_integer)]
PageSize = Annotated[int, Query(ge=1,le=50), BeforeValidator(decimal_query_integer)]
Key = Annotated[str, Header(min_length=1,max_length=128,pattern=r'^[\x21-\x7e]+$')]


@router.get('/assessment')
def assessment(project_id:str, file_id:str, store:Store, action:Action='delete'):
    return FileLifecycleService(store).assessment(project_id,file_id,action)


@router.get('/tasks')
def tasks(project_id:str, file_id:str, store:Store, page:Page=1, page_size:PageSize=10):
    return FileLifecycleService(store).tasks(project_id,file_id,page,page_size)


@router.get('/deletion-requests')
def history(project_id:str, file_id:str, store:Store, page:Page=1, page_size:PageSize=10):
    return FileLifecycleService(store).history(project_id,file_id,page,page_size)


@router.post('/deletion-requests',status_code=201)
def request_deletion(project_id:str, file_id:str, request:DeletionRequest, response:Response,
                     store:Store, idempotency_key:Key):
    value,status = FileLifecycleService(store).request_deletion(project_id,file_id,request,idempotency_key)
    response.status_code = status
    return value
