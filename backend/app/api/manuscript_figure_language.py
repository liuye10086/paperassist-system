"""Explicit offline figure language version selection; no external provider calls."""
from fastapi import APIRouter,Response
from app.api.dataset_preparation import Store,Key
from app.domain.manuscripts.figure_language import FigureLanguageService
from app.domain.manuscripts.figure_language_contracts import FigureLanguageRequest

router=APIRouter(prefix='/api/v1/projects/{project_id}/manuscript-figure-language-versions',tags=['SCI图件语言版本'])


@router.post('',status_code=201)
def create(project_id:str,request:FigureLanguageRequest,response:Response,store:Store,idempotency_key:Key):
    value,response.status_code=FigureLanguageService(store).create(project_id,request,idempotency_key)
    return value


@router.get('')
def versions(project_id:str,store:Store): return FigureLanguageService(store).list(project_id)


@router.get('/{version_id}')
def version(project_id:str,version_id:str,store:Store): return FigureLanguageService(store).get(project_id,version_id)


@router.get('/{version_id}/download')
def download(project_id:str,version_id:str,store:Store):
    service=FigureLanguageService(store)
    with service.store.connection() as db:
        row=service.row(db,project_id,version_id);raw=service.png(row)
    return Response(raw,media_type='image/png' if raw.startswith(b'\x89PNG') else 'image/jpeg',headers={'ETag':'"'+row['snapshot_json']['sha256']+'"'})
