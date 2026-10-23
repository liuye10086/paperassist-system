from fastapi import APIRouter,Response
from app.api.dataset_preparation import Store,Key
from app.domain.review_rounds.contracts import Source,CreateRequest,PlansRequest,DecisionsRequest
from app.domain.review_rounds.service import ReviewRoundService
router=APIRouter(prefix='/api/v1/projects/{project_id}/reviews',tags=['返修轮次'])
@router.get('/inputs')
def inputs(project_id:str,store:Store):return ReviewRoundService(store).inputs(project_id)
@router.post('/sources/preview')
def preview(project_id:str,request:Source,store:Store):return ReviewRoundService(store).preview(project_id,request)
@router.get('/rounds')
def listing(project_id:str,store:Store):return ReviewRoundService(store).listing(project_id)
@router.get('/rounds/{identity}')
def get(project_id:str,identity:str,store:Store):return ReviewRoundService(store).get(project_id,identity)
@router.post('/rounds',status_code=202)
def create(project_id:str,request:CreateRequest,response:Response,store:Store,idempotency_key:Key):
    result,response.status_code=ReviewRoundService(store).create(project_id,request,idempotency_key);return result
@router.post('/rounds/{identity}/plans',status_code=201)
def plans(project_id:str,identity:str,request:PlansRequest,response:Response,store:Store,idempotency_key:Key):
    result,response.status_code=ReviewRoundService(store).mutate(project_id,identity,request,idempotency_key,'plans');return result
@router.post('/rounds/{identity}/decisions')
def decisions(project_id:str,identity:str,request:DecisionsRequest,response:Response,store:Store,idempotency_key:Key):
    result,response.status_code=ReviewRoundService(store).mutate(project_id,identity,request,idempotency_key,'decisions');return result

from app.domain.review_rounds.revisions import RevisionService
from app.domain.review_rounds.revision_contracts import RevisionPreview,RevisionAdopt
@router.get('/rounds/{identity}/revision-context')
def revision_context(project_id:str,identity:str,store:Store):return RevisionService(store).revision_context(project_id,identity)
@router.post('/rounds/{identity}/revisions/preview')
def revision_preview(project_id:str,identity:str,request:RevisionPreview,store:Store):return RevisionService(store).preview_revision(project_id,identity,request)
@router.post('/rounds/{identity}/revisions',status_code=202)
@router.post('/rounds/{identity}/revisions/adopt',status_code=202)
def revision_adopt(project_id:str,identity:str,request:RevisionAdopt,response:Response,store:Store,idempotency_key:Key):
    result,response.status_code=RevisionService(store).adopt(project_id,identity,request,idempotency_key);return result
@router.get('/rounds/{identity}/revisions')
def revisions(project_id:str,identity:str,store:Store):return RevisionService(store).revisions(project_id,identity)
@router.get('/revisions/{identity}')
def revision_get(project_id:str,identity:str,store:Store):return RevisionService(store).get_revision(project_id,identity)
