"""Private SCI fact drafts, historical snapshots and local Word exports."""
from fastapi import APIRouter,Response,Path
from typing import Annotated
from app.api.dataset_preparation import Store,Key
from app.domain.manuscripts.contracts import ManuscriptRequest,EmptyRequest,ExportRequest
from app.domain.manuscripts.service import ManuscriptService
from fastapi.responses import Response as RawResponse
from urllib.parse import quote

router=APIRouter(prefix='/api/v1/projects/{project_id}/manuscripts',tags=['SCI事实稿'])
Revision=Annotated[int,Path(ge=1,le=2147483647)]

from app.domain.manuscripts.analysis_selection import AnalysisSelectionRequest,select,options
from app.domain.manuscripts.collection_selection import CollectionSelectionRequest,select as select_collection

@router.post('/collection-report-selection')
def collection_report_selection(project_id:str,request:CollectionSelectionRequest,store:Store):
    return select_collection(ManuscriptService(store),project_id,request)

@router.get('/analysis-options')
def analysis_options(project_id:str,file_id:str,analysis_run_id:str,store:Store):
    return options(ManuscriptService(store),project_id,file_id,analysis_run_id)

@router.post('/analysis-selection')
def analysis_selection(project_id:str,request:AnalysisSelectionRequest,store:Store):
    return select(ManuscriptService(store),project_id,request)

@router.get('/config')
def config(project_id:str,store:Store): return ManuscriptService(store).config(project_id)

@router.get('/candidates')
def candidates(project_id:str,store:Store): return ManuscriptService(store).candidates(project_id)

@router.post('/preview')
def preview(project_id:str,request:ManuscriptRequest,store:Store): return ManuscriptService(store).preview(project_id,request)

@router.get('')
def manuscripts(project_id:str,store:Store): return ManuscriptService(store).list(project_id)

@router.post('',status_code=201)
def create(project_id:str,request:ManuscriptRequest,response:Response,store:Store,idempotency_key:Key):
    result,response.status_code=ManuscriptService(store).create(project_id,request,idempotency_key)
    return result

@router.get('/{manuscript_id}')
def manuscript(project_id:str,manuscript_id:str,store:Store): return ManuscriptService(store).get(project_id,manuscript_id)

@router.post('/{manuscript_id}/versions',status_code=201)
def create_version(project_id:str,manuscript_id:str,request:ManuscriptRequest,response:Response,store:Store,idempotency_key:Key):
    result,response.status_code=ManuscriptService(store).create(project_id,request,idempotency_key,manuscript_id)
    return result

@router.get('/{manuscript_id}/versions/{revision}')
def version(project_id:str,manuscript_id:str,revision:Revision,store:Store): return ManuscriptService(store).get(project_id,manuscript_id,revision)

@router.get('/{manuscript_id}/versions/{revision}/writing-materials')
def writing_materials(project_id:str,manuscript_id:str,revision:Revision,store:Store):
    return ManuscriptService(store).writing_materials(project_id,manuscript_id,revision)

@router.post('/{manuscript_id}/versions/{revision}/exports',status_code=201)
def create_export(project_id:str,manuscript_id:str,revision:Revision,request:ExportRequest,response:Response,store:Store,idempotency_key:Key):
    result,response.status_code=ManuscriptService(store).create_export(project_id,manuscript_id,revision,idempotency_key,request)
    return result

@router.get('/{manuscript_id}/versions/{revision}/exports')
def exports(project_id:str,manuscript_id:str,revision:Revision,store:Store): return ManuscriptService(store).exports(project_id,manuscript_id,revision)

@router.get('/{manuscript_id}/exports/{export_id}')
def export(project_id:str,manuscript_id:str,export_id:str,store:Store): return ManuscriptService(store).export(project_id,manuscript_id,export_id)

@router.get('/{manuscript_id}/exports/{export_id}/download')
def download(project_id:str,manuscript_id:str,export_id:str,store:Store):
    metadata,raw=ManuscriptService(store).export(project_id,manuscript_id,export_id,True)
    return RawResponse(raw,media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(metadata['filename'],safe='')})

@router.post('/{manuscript_id}/recover')
def recover(project_id:str,manuscript_id:str,request:EmptyRequest,store:Store): return ManuscriptService(store).recover(project_id,manuscript_id)

@router.post('/{manuscript_id}/versions/{revision}/exports/preview')
def preview_export(project_id:str,manuscript_id:str,revision:Revision,request:ExportRequest,store:Store):
    return ManuscriptService(store).preview_export(project_id,manuscript_id,revision,request)
