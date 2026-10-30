"""Owner-scoped requirement/design versioning and delivery registration."""
from typing import Annotated
from fastapi import APIRouter, Depends, Header, Query
from app.adapters.storage import ProjectStore, get_request_project_store
from app.domain.research_intake import service
from app.domain.research_intake.contracts import RequirementWrite, DesignWrite, DesignTablePreview

router=APIRouter(prefix='/api/v1',tags=['研究需求与设计'])
Store=Annotated[ProjectStore,Depends(get_request_project_store)]
Key=Annotated[str | None,Header(alias='Idempotency-Key')]


@router.get('/project-create-requests/{key}')
def creation_request(key:str,store:Store):
    return store.project_creation_request(key)


@router.get('/projects/{project_id}/research-intake')
def intake(project_id:str,store:Store):
    return service.read_intake(store,project_id)


@router.get('/projects/{project_id}/deliveries')
def deliveries(project_id:str,store:Store):
    result=service.read_intake(store,project_id)
    return {'items':result['deliveries'],'capabilities':result['capabilities']}


@router.post('/projects/{project_id}/requirements',status_code=201)
def requirements(project_id:str,request:RequirementWrite,store:Store,idempotency_key:Key=None):
    return service.write_version(store,project_id,'requirements',request,idempotency_key)


@router.get('/projects/{project_id}/requirements')
def requirement_versions(project_id:str,store:Store,page:Annotated[int,Query(ge=1,le=1000000)]=1):
    return service.read_versions(store,project_id,'requirements',page=page)


@router.get('/projects/{project_id}/requirements/requests/{key}')
def requirement_request(project_id:str,key:str,store:Store):
    return service.read_versions(store,project_id,'requirements',key=key)


@router.get('/projects/{project_id}/requirements/{version_id}')
def requirement_version(project_id:str,version_id:str,store:Store):
    return service.read_versions(store,project_id,'requirements',version_id=version_id)


@router.post('/projects/{project_id}/research-designs',status_code=201)
def designs(project_id:str,request:DesignWrite,store:Store,idempotency_key:Key=None):
    return service.write_version(store,project_id,'research-designs',request,idempotency_key)


@router.get('/projects/{project_id}/research-designs')
def design_versions(project_id:str,store:Store,page:Annotated[int,Query(ge=1,le=1000000)]=1):
    return service.read_versions(store,project_id,'research-designs',page=page)


@router.get('/projects/{project_id}/research-designs/requests/{key}')
def design_request(project_id:str,key:str,store:Store):
    return service.read_versions(store,project_id,'research-designs',key=key)


@router.get('/projects/{project_id}/research-designs/{version_id}')
def design_version(project_id:str,version_id:str,store:Store):
    return service.read_versions(store,project_id,'research-designs',version_id=version_id)


@router.post('/projects/{project_id}/design-table-preview')
@router.post('/projects/{project_id}/design-table-previews')
def design_table(project_id:str,request:DesignTablePreview,store:Store):
    return service.preview_table(store,project_id,request)
