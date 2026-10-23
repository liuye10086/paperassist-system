"""Owner-scoped school template intake, confirmation and explicit binding."""
from fastapi import APIRouter,Response
from app.api.dataset_preparation import Store,Key
from app.domain.school_templates.contracts import ProfileRequest,TemplateRequest,ConfirmRequest,BindingRequest,EmptyRequest
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
def confirm(project_id:str,identity:str,request:ConfirmRequest,response:Response,store:Store,idempotency_key:Key):
    result,response.status_code=SchoolTemplateService(store).confirm(project_id,identity,request,idempotency_key)
    return result

@router.post('/thesis-template-binding')
def bind(project_id:str,request:BindingRequest,store:Store): return SchoolTemplateService(store).bind(project_id,request)
