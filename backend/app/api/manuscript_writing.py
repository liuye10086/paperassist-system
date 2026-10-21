from app.domain.manuscript_writing.live_review_contracts import ScientificReviewRequest, ReviewedPublishRequest
from app.domain.manuscript_writing.live_review import LiveReviewService
from app.domain.manuscript_writing.live_contracts import LiveWritingRequest, PreviewRequest, AuthorizationRequest
from app.domain.manuscript_writing.authorization import LiveWritingService
from fastapi import APIRouter,Response
from app.api.dataset_preparation import Store,Key
from app.domain.manuscript_writing.contracts import WritingRequest,PublishRequest
from app.domain.manuscript_writing.service import WritingService
router=APIRouter(prefix='/api/v1/projects/{project_id}/manuscripts/{manuscript_id}/writing-requests',tags=['SCI写作'])

@router.post('',status_code=202)
def create(project_id:str,manuscript_id:str,request:WritingRequest | LiveWritingRequest,response:Response,store:Store,idempotency_key:Key):
    result,response.status_code=WritingService(store).create(project_id,manuscript_id,request,idempotency_key)
    return result

@router.get('')
def listing(project_id:str,manuscript_id:str,store:Store): return WritingService(store).list(project_id,manuscript_id)

@router.get('/{request_id}')
def get(project_id:str,manuscript_id:str,request_id:str,store:Store): return WritingService(store).get(project_id,manuscript_id,request_id)

@router.post('/{request_id}/publish',status_code=201)
def publish(project_id:str,manuscript_id:str,request_id:str,request:PublishRequest | ReviewedPublishRequest,response:Response,store:Store,idempotency_key:Key):
    result,response.status_code=WritingService(store).publish(project_id,manuscript_id,request_id,request.expected_revision,idempotency_key,request if isinstance(request,ReviewedPublishRequest) else None)
    return result

preview_router=APIRouter(prefix='/api/v1/projects/{project_id}/manuscripts/{manuscript_id}/writing-previews',tags=['SCI写作'])
authorization_router=APIRouter(prefix='/api/v1/projects/{project_id}/writing-authorizations',tags=['SCI写作'])

@preview_router.post('',status_code=201)
def preview(project_id:str,manuscript_id:str,request:PreviewRequest,response:Response,store:Store,idempotency_key:Key):
    result,response.status_code=LiveWritingService(store).preview(project_id,manuscript_id,request,idempotency_key)
    return result

@preview_router.get('')
def previews(project_id:str,manuscript_id:str,store:Store):
    return LiveWritingService(store).list_previews(project_id,manuscript_id)

@preview_router.get('/{bundle_id}')
def preview_get(project_id:str,manuscript_id:str,bundle_id:str,store:Store):
    return LiveWritingService(store).get_preview(project_id,manuscript_id,bundle_id)

@authorization_router.post('',status_code=201)
def authorize(project_id:str,request:AuthorizationRequest,response:Response,store:Store,idempotency_key:Key):
    result,response.status_code=LiveWritingService(store).authorize(project_id,request,idempotency_key)
    return result

@authorization_router.get('')
def authorizations(project_id:str,store:Store): return LiveWritingService(store).list_authorizations(project_id)

@authorization_router.get('/{authorization_id}')
def authorization_get(project_id:str,authorization_id:str,store:Store): return LiveWritingService(store).get_authorization(project_id,authorization_id)

@authorization_router.post('/{authorization_id}/close')
def authorization_close(project_id:str,authorization_id:str,store:Store): return LiveWritingService(store).close(project_id,authorization_id)

@router.get('/{request_id}/review-context')
def review_context(project_id:str,manuscript_id:str,request_id:str,store:Store):
    return LiveReviewService(store).context(project_id,manuscript_id,request_id)

@router.post('/{request_id}/reviews',status_code=201)
def review_create(project_id:str,manuscript_id:str,request_id:str,request:ScientificReviewRequest,response:Response,store:Store,idempotency_key:Key):
    result,response.status_code=LiveReviewService(store).create(project_id,manuscript_id,request_id,request,idempotency_key)
    return result

@router.get('/{request_id}/reviews/{review_id}')
def review_get(project_id:str,manuscript_id:str,request_id:str,review_id:str,store:Store):
    return LiveReviewService(store).get(project_id,manuscript_id,request_id,review_id)


from app.domain.manuscript_writing.language_contracts import LanguagePreparation,LanguageReviewRequest
from app.domain.manuscript_writing.language_service import LanguageReviewService

@router.get('/{request_id}/reviews/{review_id}/language-context')
def language_context(project_id:str,manuscript_id:str,request_id:str,review_id:str,store:Store):
    return LanguageReviewService(store).context(project_id,manuscript_id,request_id,review_id)

@router.post('/{request_id}/reviews/{review_id}/language-context')
def language_preview(project_id:str,manuscript_id:str,request_id:str,review_id:str,request:LanguagePreparation,store:Store):
    return LanguageReviewService(store).context(project_id,manuscript_id,request_id,review_id,request)

@router.post('/{request_id}/language-reviews',status_code=201)
def language_create(project_id:str,manuscript_id:str,request_id:str,request:LanguageReviewRequest,response:Response,store:Store,idempotency_key:Key):
    result,response.status_code=LanguageReviewService(store).create_language(project_id,manuscript_id,request_id,request,idempotency_key)
    return result

@router.get('/{request_id}/language-reviews/{language_id}')
def language_get(project_id:str,manuscript_id:str,request_id:str,language_id:str,store:Store):
    return LanguageReviewService(store).get_language(project_id,manuscript_id,request_id,language_id)
