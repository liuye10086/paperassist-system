from fastapi import APIRouter,Response,Query
from app.api.dataset_preparation import Store,Key
from app.domain.manuscript_review.contracts import ReviewRequest,PublishRequest
from app.domain.manuscript_review.service import ReviewService
router=APIRouter(prefix='/api/v1/projects/{project_id}/manuscripts/{manuscript_id}/reviews',tags=['SCI资料确认与一致性'])

@router.get('/context')
def context(project_id:str,manuscript_id:str,store:Store,revision:int|None=Query(default=None,ge=1)):
    return ReviewService(store).context(project_id,manuscript_id,revision)

@router.get('')
def listing(project_id:str,manuscript_id:str,store:Store): return ReviewService(store).list(project_id,manuscript_id)

@router.post('',status_code=201)
def create(project_id:str,manuscript_id:str,request:ReviewRequest,response:Response,store:Store,idempotency_key:Key):
    result,response.status_code=ReviewService(store).create(project_id,manuscript_id,request,idempotency_key)
    return result

@router.get('/{review_id}')
def get(project_id:str,manuscript_id:str,review_id:str,store:Store): return ReviewService(store).get(project_id,manuscript_id,review_id)

@router.post('/{review_id}/publish',status_code=201)
def publish(project_id:str,manuscript_id:str,review_id:str,request:PublishRequest,response:Response,store:Store,idempotency_key:Key):
    result,response.status_code=ReviewService(store).publish(project_id,manuscript_id,review_id,request.expected_revision,idempotency_key)
    return result
