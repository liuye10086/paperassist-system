"""Project-private citation samples and immutable bibliography/material versions."""
from typing import Annotated
from fastapi import APIRouter, Response, Path
from app.api.dataset_preparation import Store, Key, Page
from app.domain.literature_citations.contracts import MetadataRequest, MaterialConfirmationRequest, DraftRequest, DraftVersionRequest
from app.domain.literature_citations.service import LiteratureCitationService

router=APIRouter(prefix='/api/v1/projects/{project_id}/literature/citations',tags=['文献引用样稿'])


@router.get('/config')
def config(project_id:str,store:Store):
    return LiteratureCitationService(store).config(project_id)


@router.get('/candidates')
def candidates(project_id:str,store:Store,page:Page=1):
    return LiteratureCitationService(store).candidates(project_id,page)


@router.get('/todos')
def todos(project_id:str,store:Store,page:Page=1):
    return LiteratureCitationService(store).candidates(project_id,page,todos=True)


@router.get('/references/{project_reference_id}/metadata')
def metadata(project_id:str,project_reference_id:str,store:Store,page:Page=1):
    return LiteratureCitationService(store).metadata_history(project_id,project_reference_id,page)


@router.post('/references/{project_reference_id}/metadata',status_code=201)
def create_metadata(project_id:str,project_reference_id:str,request:MetadataRequest,response:Response,store:Store,idempotency_key:Key):
    view,response.status_code=LiteratureCitationService(store).create_metadata(project_id,project_reference_id,request,idempotency_key)
    return view


@router.get('/metadata/{metadata_version_id}/source')
def metadata_source(project_id:str,metadata_version_id:str,store:Store):
    return LiteratureCitationService(store).metadata_source(project_id,metadata_version_id)


@router.get('/materials/{material_id}/confirmations')
def confirmations(project_id:str,material_id:str,store:Store,page:Page=1):
    return LiteratureCitationService(store).confirmations(project_id,material_id,page)


@router.post('/materials/{material_id}/confirmations',status_code=201)
def create_confirmation(project_id:str,material_id:str,request:MaterialConfirmationRequest,response:Response,store:Store,idempotency_key:Key):
    view,response.status_code=LiteratureCitationService(store).create_confirmation(project_id,material_id,request,idempotency_key)
    return view


@router.get('/drafts')
def drafts(project_id:str,store:Store,page:Page=1):
    return LiteratureCitationService(store).drafts(project_id,page)


@router.post('/drafts',status_code=201)
def create_draft(project_id:str,request:DraftRequest,response:Response,store:Store,idempotency_key:Key):
    view,response.status_code=LiteratureCitationService(store).create_draft(project_id,request,idempotency_key)
    return view


@router.get('/drafts/{draft_id}')
def draft(project_id:str,draft_id:str,store:Store,revision:Page|None=None):
    return LiteratureCitationService(store).draft(project_id,draft_id,revision)


@router.post('/drafts/{draft_id}/versions',status_code=201)
def version(project_id:str,draft_id:str,request:DraftVersionRequest,response:Response,store:Store,idempotency_key:Key):
    view,response.status_code=LiteratureCitationService(store).create_draft(project_id,request,idempotency_key,draft_id)
    return view


@router.get('/drafts/{draft_id}/versions/{revision}/output')
def output(project_id:str,draft_id:str,revision:Annotated[int,Path(ge=1,le=2147483647)],store:Store):
    return LiteratureCitationService(store).saved(project_id,draft_id,revision)


@router.get('/drafts/{draft_id}/versions/{revision}/source')
def source(project_id:str,draft_id:str,revision:Annotated[int,Path(ge=1,le=2147483647)],store:Store):
    return LiteratureCitationService(store).saved(project_id,draft_id,revision,source=True)
