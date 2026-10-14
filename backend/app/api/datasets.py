"""Explicit structure generation; every GET only reads persisted versions."""
from typing import Annotated
from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import BeforeValidator
from app.adapters.storage import ProjectStore, get_request_project_store
from app.domain.datasets.service import DatasetService, StructureCreateRequest
from app.api.tasks import decimal_query_integer
from app.domain.dataset_profile.contracts import Profile, IssueKind, IssuePage
from app.domain.dataset_profile.service import DatasetProfileService

router = APIRouter(prefix='/api/v1/projects',tags=['原始数据版本'])
Store = Annotated[ProjectStore,Depends(get_request_project_store)]


@router.post('/{project_id}/files/{file_id}/structure-versions',status_code=202)
def create_structure(project_id:str,file_id:str,request:StructureCreateRequest,response:Response,store:Store,
    idempotency_key:Annotated[str,Header(min_length=1,max_length=128,pattern=r'^[\x21-\x7e]+$')]):
    view,status=DatasetService(store).create(project_id,file_id,request,idempotency_key)
    response.status_code=status
    return view


@router.get('/{project_id}/files/{file_id}/structure-versions')
def list_structures(project_id:str,file_id:str,store:Store,
    page:Annotated[int,Query(ge=1,le=1000000),BeforeValidator(decimal_query_integer)]=1,
    page_size:Annotated[int,Query(ge=1,le=100),BeforeValidator(decimal_query_integer)]=5):
    return DatasetService(store).list(project_id,file_id,page,page_size)


@router.get('/{project_id}/files/{file_id}/structure-versions/{structure_id}')
def get_structure(project_id:str,file_id:str,structure_id:str,store:Store):
    return DatasetService(store).get(project_id,file_id,structure_id)


@router.get('/{project_id}/files/{file_id}/dataset-versions/{dataset_id}/rows')
def get_rows(project_id:str,file_id:str,dataset_id:str,store:Store,
    start_row:Annotated[int,Query(ge=1,le=100000),BeforeValidator(decimal_query_integer)]=1,
    limit:Annotated[int,Query(ge=20,le=20),BeforeValidator(decimal_query_integer)]=20):
    return DatasetService(store).rows(project_id,file_id,dataset_id,start_row,limit)


@router.get('/{project_id}/files/{file_id}/dataset-versions/{dataset_id}/download')
def download_dataset(project_id:str,file_id:str,dataset_id:str,store:Store):
    row,content,_=DatasetService(store).dataset(project_id,file_id,dataset_id)
    filename=f"raw-data-v{row['version']}-sheet-{row['sheet_index']+1}.json"
    return Response(content,media_type='application/json',headers={'Content-Disposition':f'attachment; filename="{filename}"'})


@router.get('/{project_id}/files/{file_id}/dataset-versions/{dataset_id}/profile', response_model=Profile)
def get_dataset_profile(project_id: str, file_id: str, dataset_id: str, store: Store):
    return DatasetProfileService(store).profile(project_id, file_id, dataset_id)


@router.get('/{project_id}/files/{file_id}/dataset-versions/{dataset_id}/profile/issues', response_model=IssuePage)
def get_dataset_profile_issues(project_id: str, file_id: str, dataset_id: str, store: Store,
    kind: Annotated[IssueKind, Query()],
    column: Annotated[int | None, Query(ge=1, le=256), BeforeValidator(decimal_query_integer)] = None,
    page: Annotated[int, Query(ge=1, le=1000000), BeforeValidator(decimal_query_integer)] = 1,
    page_size: Annotated[int, Query(ge=20, le=20), BeforeValidator(decimal_query_integer)] = 20):
    return DatasetProfileService(store).issues(project_id, file_id, dataset_id, kind, column, page)
