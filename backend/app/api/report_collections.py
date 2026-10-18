"""Owner-scoped immutable report collection routes."""
from typing import Annotated
from urllib.parse import quote
from fastapi import APIRouter, Header, Response
from app.api.dependencies import Store
from app.adapters.collection_store import CollectionStore
from app.domain.report_collections.contracts import CollectionRequest

router=APIRouter(prefix='/api/v1/projects/{project_id}/report-collections',tags=['报告集合'])

@router.get('')
def list_collections(project_id:str,store:Store): return CollectionStore(store).list(project_id)

@router.get('/candidates')
def candidates(project_id:str,store:Store,file_id:str|None=None): return CollectionStore(store).candidates(project_id,file_id)

@router.post('',status_code=201)
def create(project_id:str,request:CollectionRequest,store:Store,idempotency_key:Annotated[str,Header()]):
    return CollectionStore(store).create(project_id,request,idempotency_key)

@router.get('/{collection_id}')
def get(project_id:str,collection_id:str,store:Store): return CollectionStore(store).get(project_id,collection_id)

@router.post('/{collection_id}/versions',status_code=201)
def version(project_id:str,collection_id:str,request:CollectionRequest,store:Store,idempotency_key:Annotated[str,Header()]):
    return CollectionStore(store).new_version(project_id,collection_id,request,idempotency_key)

@router.post('/{collection_id}/versions/{version_id}/exports',status_code=202)
def export(project_id:str,collection_id:str,version_id:str,store:Store,idempotency_key:Annotated[str,Header()]):
    return CollectionStore(store).export(project_id,collection_id,version_id,idempotency_key)

@router.get('/{collection_id}/versions/{version_id}/preview')
def preview(project_id:str,collection_id:str,version_id:str,store:Store): return CollectionStore(store).preview(project_id,collection_id,version_id)

@router.get('/{collection_id}/reports/{report_id}/download')
def download(project_id:str,collection_id:str,report_id:str,store:Store):
    metadata,content=CollectionStore(store).download(project_id,collection_id,report_id)
    return Response(content,media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',headers={
        'Content-Disposition':"attachment; filename=analysis-report.docx; filename*=UTF-8''"+quote(metadata['filename']),'Cache-Control':'no-store'})
