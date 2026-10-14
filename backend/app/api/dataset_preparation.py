"""Explicit preparation and review routes; every GET is read-only."""
from typing import Annotated
from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import BeforeValidator

from app.adapters.storage import ProjectStore, get_request_project_store
from app.api.tasks import decimal_query_integer
from app.domain.dataset_preparation.service import (DatasetPreparationService,
    PreparationCreateRequest,PreparationDecisionRequest)
from app.domain.tasks.contracts import TaskView

router = APIRouter(prefix='/api/v1',tags=['整理数据'])
Store = Annotated[ProjectStore,Depends(get_request_project_store)]
Key = Annotated[str,Header(min_length=1,max_length=128,pattern=r'^[\x21-\x7e]+$')]
Page = Annotated[int,Query(ge=1,le=1000000),BeforeValidator(decimal_query_integer)]
Five = Annotated[int,Query(ge=5,le=5),BeforeValidator(decimal_query_integer)]
Row = Annotated[int,Query(ge=1,le=100000),BeforeValidator(decimal_query_integer)]
Twenty = Annotated[int,Query(ge=20,le=20),BeforeValidator(decimal_query_integer)]


@router.get('/projects/{project_id}/files/{file_id}/dataset-versions/{dataset_id}/preparation-defaults')
def defaults(project_id:str,file_id:str,dataset_id:str,store:Store,header_row:Row=1,data_range:str|None=None):
    return DatasetPreparationService(store).defaults(project_id,file_id,dataset_id,header_row,data_range)


@router.post('/projects/{project_id}/files/{file_id}/dataset-preparations',response_model=TaskView,status_code=202)
def create(project_id:str,file_id:str,request:PreparationCreateRequest,response:Response,store:Store,idempotency_key:Key):
    task,status = DatasetPreparationService(store).create(project_id,file_id,request,idempotency_key)
    response.status_code = status
    return task


@router.get('/tasks/{task_id}/dataset-preparation')
def review(task_id:str,store:Store):
    return DatasetPreparationService(store).get_task(task_id)


@router.post('/tasks/{task_id}/dataset-preparation/decision',response_model=TaskView,status_code=202)
def decide(task_id:str,request:PreparationDecisionRequest,store:Store,idempotency_key:Key):
    return DatasetPreparationService(store).decide(task_id,request,idempotency_key)


@router.get('/tasks/{task_id}/dataset-preparation/preview/download')
def preview_download(task_id:str,store:Store):
    content = DatasetPreparationService(store).preview_download(task_id)
    return Response(content,media_type='application/json',headers={'Content-Disposition':'attachment; filename="preparation-preview.json"'})


@router.get('/projects/{project_id}/files/{file_id}/prepared-dataset-versions')
def list_versions(project_id:str,file_id:str,store:Store,page:Page=1,page_size:Five=5):
    return DatasetPreparationService(store).list_versions(project_id,file_id,page,page_size)


@router.get('/projects/{project_id}/files/{file_id}/prepared-dataset-versions/{dataset_id}')
def get_version(project_id:str,file_id:str,dataset_id:str,store:Store):
    return DatasetPreparationService(store).get_version(project_id,file_id,dataset_id)


@router.get('/projects/{project_id}/files/{file_id}/prepared-dataset-versions/{dataset_id}/rows')
def rows(project_id:str,file_id:str,dataset_id:str,store:Store,
    start_row:Annotated[int|None,Query(ge=1,le=100000),BeforeValidator(lambda value:decimal_query_integer(value) if value is not None else None)]=None,
    limit:Twenty=20):
    return DatasetPreparationService(store).rows(project_id,file_id,dataset_id,start_row,limit)


@router.get('/projects/{project_id}/files/{file_id}/prepared-dataset-versions/{dataset_id}/download')
def download(project_id:str,file_id:str,dataset_id:str,store:Store):
    row,content,_ = DatasetPreparationService(store).load_version(project_id,file_id,dataset_id)
    filename = f"prepared-data-v{row['version']}.json"
    return Response(content,media_type='application/json',headers={'Content-Disposition':f'attachment; filename="{filename}"'})
