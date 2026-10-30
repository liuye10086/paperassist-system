"""Finite offline journal versioning and recommendation endpoints."""
from fastapi import APIRouter,Response
from app.api.dataset_preparation import Store,Key
from app.domain.journals.contracts import ProfileRequest,RecommendationRequest,EmptyRequest
from app.domain.journals.service import JournalService
from app.domain.journals.guides import GuideService
from app.domain.journals.format_service import FormatService
from app.domain.journals.format_contracts import GuideRequest,TargetRequest,FormatCheckRequest
router=APIRouter(prefix='/api/v1/projects/{project_id}/journals',tags=['期刊建议'])

@router.get('/config')
def config(project_id:str,store:Store):return JournalService(store).config(project_id)
@router.get('/profiles')
def profiles(project_id:str,store:Store):return JournalService(store).profiles(project_id)
@router.get('/profiles/{identity}')
def profile(project_id:str,identity:str,store:Store):return JournalService(store).profile(project_id,identity)
@router.post('/profiles',status_code=201)
def create_profile(project_id:str,request:ProfileRequest,response:Response,store:Store,idempotency_key:Key):
    result,response.status_code=JournalService(store).create_profile(project_id,request,idempotency_key);return result
@router.get('/recommendations')
def recommendations(project_id:str,store:Store):return JournalService(store).list(project_id)
@router.get('/recommendations/{identity}')
def recommendation(project_id:str,identity:str,store:Store):return JournalService(store).get(project_id,identity)
@router.post('/recommendations',status_code=202)
def create(project_id:str,request:RecommendationRequest,response:Response,store:Store,idempotency_key:Key):
    result,response.status_code=JournalService(store).create(project_id,request,idempotency_key);return result
@router.post('/recommendations/{identity}/retry')
def retry(project_id:str,identity:str,request:EmptyRequest,store:Store):return JournalService(store).retry(project_id,identity)

@router.get('/guides')
def guides(project_id:str,store:Store):return GuideService(store).guides(project_id)
@router.get('/guides/{identity}')
def guide(project_id:str,identity:str,store:Store):return GuideService(store).get_guide(project_id,identity)
@router.post('/guides/{identity}/fetch',status_code=201)
def fetch_guide(project_id:str,identity:str,request:EmptyRequest,response:Response,store:Store,idempotency_key:Key):
    result,response.status_code=GuideService(store).fetch_guide(project_id,identity,idempotency_key);return result
@router.post('/guides',status_code=201)
def create_guide(project_id:str,request:GuideRequest,response:Response,store:Store,idempotency_key:Key):
    result,response.status_code=GuideService(store).create_guide(project_id,request,idempotency_key);return result
@router.get('/targets')
def targets(project_id:str,store:Store):return GuideService(store).targets(project_id)
@router.get('/targets/{identity}')
def target(project_id:str,identity:str,store:Store):return GuideService(store).get_target(project_id,identity)
@router.post('/targets',status_code=201)
def create_target(project_id:str,request:TargetRequest,response:Response,store:Store,idempotency_key:Key):
    result,response.status_code=GuideService(store).create_target(project_id,request,idempotency_key);return result
@router.get('/checks')
def checks(project_id:str,store:Store):return FormatService(store).checks(project_id)
@router.get('/checks/{identity}')
def check(project_id:str,identity:str,store:Store):return FormatService(store).get_check(project_id,identity)
@router.post('/checks',status_code=202)
def create_check(project_id:str,request:FormatCheckRequest,response:Response,store:Store,idempotency_key:Key):
    result,response.status_code=FormatService(store).create_check(project_id,request,idempotency_key);return result
@router.post('/checks/{identity}/retry')
def retry_check(project_id:str,identity:str,request:EmptyRequest,store:Store):return FormatService(store).retry_check(project_id,identity)

from app.domain.journals.adaptation_contracts import PreviewRequest,AdaptationRequest,SubmissionRequest
from app.domain.journals.adaptation_service import AdaptationService
from app.domain.journals.submissions import SubmissionService

@router.post('/adaptations/preview')
def preview_adaptation(project_id:str,request:PreviewRequest,store:Store):return AdaptationService(store).preview(project_id,request)
@router.get('/adaptations')
def adaptations(project_id:str,store:Store):return AdaptationService(store).adaptations(project_id)
@router.get('/adaptations/{identity}')
def adaptation(project_id:str,identity:str,store:Store):return AdaptationService(store).get_adaptation(project_id,identity)
@router.post('/adaptations',status_code=202)
def create_adaptation(project_id:str,request:AdaptationRequest,response:Response,store:Store,idempotency_key:Key):
    result,response.status_code=AdaptationService(store).create_adaptation(project_id,request,idempotency_key);return result
@router.post('/adaptations/{identity}/retry')
def retry_adaptation(project_id:str,identity:str,request:EmptyRequest,store:Store):return AdaptationService(store).retry_adaptation(project_id,identity)
@router.get('/submission-events')
def submission_events(project_id:str,store:Store):return SubmissionService(store).list_events(project_id)
@router.post('/submission-events',status_code=201)
def create_submission_event(project_id:str,request:SubmissionRequest,response:Response,store:Store,idempotency_key:Key):
    result,response.status_code=SubmissionService(store).create_event(project_id,request,idempotency_key);return result
