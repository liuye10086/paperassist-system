"""Owner-scoped school template intake, confirmation and explicit binding."""
from fastapi import APIRouter,Response
from app.api.dataset_preparation import Store,Key
from app.domain.school_templates.contracts import ProfileRequest,TemplateRequest,ConfirmRequest,ConfirmRequestV2,BindingRequest,EmptyRequest
from app.domain.school_templates.service import SchoolTemplateService

router=APIRouter(prefix='/api/v1/projects/{project_id}',tags=['学校模板'])

@router.get('/thesis-profile')
def profile(project_id:str,store:Store): return SchoolTemplateService(store).profile(project_id)

@router.put('/thesis-profile')
def save_profile(project_id:str,request:ProfileRequest,store:Store): return SchoolTemplateService(store).save_profile(project_id,request)

@router.get('/school-templates')
def templates(project_id:str,store:Store): return SchoolTemplateService(store).list(project_id)

@router.post('/school-templates',status_code=202)
def create(project_id:str,request:TemplateRequest,response:Response,store:Store,idempotency_key:Key):
    result,response.status_code=SchoolTemplateService(store).create(project_id,request,idempotency_key)
    return result

@router.post('/school-templates/{identity}/retry')
def retry(project_id:str,identity:str,request:EmptyRequest,store:Store): return SchoolTemplateService(store).retry(project_id,identity)

@router.post('/school-templates/{identity}/confirm',status_code=201)
def confirm(project_id:str,identity:str,request:ConfirmRequestV2|ConfirmRequest,response:Response,store:Store,idempotency_key:Key):
    result,response.status_code=SchoolTemplateService(store).confirm(project_id,identity,request,idempotency_key)
    return result

@router.post('/thesis-template-binding')
def bind(project_id:str,request:BindingRequest,store:Store): return SchoolTemplateService(store).bind(project_id,request)

from app.domain.school_templates.suggestion_contracts import SuggestionPreview,SuggestionRequest
from app.domain.school_templates.suggestion_service import SuggestionService

@router.post('/school-templates/{identity}/rule-suggestion-preview')
def suggestion_preview(project_id:str,identity:str,request:SuggestionPreview,store:Store):
    return SuggestionService(store).preview(project_id,identity,request)

@router.post('/school-templates/{identity}/rule-suggestions',status_code=202)
def create_suggestion(project_id:str,identity:str,request:SuggestionRequest,response:Response,store:Store,idempotency_key:Key):
    result,response.status_code=SuggestionService(store).create_suggestion(project_id,identity,request,idempotency_key)
    return result

@router.get('/school-templates/{identity}/rule-suggestions')
def list_suggestions(project_id:str,identity:str,store:Store):return SuggestionService(store).list_suggestions(project_id,identity)

@router.get('/school-rule-suggestions/{identity}')
def get_suggestion(project_id:str,identity:str,store:Store):return SuggestionService(store).get_suggestion(project_id,identity)

@router.post('/school-templates/{identity}/fork',status_code=202)
def fork_template(project_id:str,identity:str,request:EmptyRequest,response:Response,store:Store,idempotency_key:Key):
    result,response.status_code=SuggestionService(store).fork(project_id,identity,idempotency_key)
    return result
