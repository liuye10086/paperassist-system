"""Owner-scoped explicit preview/execute; no fixture enrollment endpoint."""
from typing import Literal
from fastapi import APIRouter,Header,Request
from pydantic import BaseModel,ConfigDict,Field
from app.adapters.storage import ProjectStore
from app.core.config import get_data_dir
from app.domain.storage_governance.deletion import DeletionService

router=APIRouter(prefix='/api/v1/projects/{project_id}/storage-deletions',tags=['受控存储处置'])


class Preview(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    scope_kind:Literal['project','file','temporary']
    file_id:str|None=None
    reason:str=Field(min_length=1,max_length=500)


class Confirmation(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    confirmed_manifest_sha256:str=Field(pattern='^[0-9a-f]{64}$')
    confirmation:Literal['delete_registered_synthetic_objects']


def service(request):
    return DeletionService(ProjectStore(get_data_dir(),owner_id=getattr(request.state,'user',{}).get('id')))


@router.post('/preview')
def preview(request:Request,project_id:str,body:Preview):
    return service(request).preview(project_id,**body.model_dump())


@router.get('/{operation_id}')
def status(request:Request,project_id:str,operation_id:str):
    return service(request).status(project_id,operation_id)


@router.post('/{operation_id}/execute')
def execute(request:Request,project_id:str,operation_id:str,body:Confirmation,idempotency_key:str=Header(alias='Idempotency-Key')):
    return service(request).execute(project_id,operation_id,key=idempotency_key,**body.model_dump())


@router.post('/{operation_id}/retry')
def retry(request:Request,project_id:str,operation_id:str,body:Confirmation,idempotency_key:str=Header(alias='Idempotency-Key')):
    return service(request).retry(project_id,operation_id,key=idempotency_key,**body.model_dump())
