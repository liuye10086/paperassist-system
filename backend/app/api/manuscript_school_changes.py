from fastapi import APIRouter,Response
from app.api.dataset_preparation import Store,Key
from app.domain.manuscripts.school_change_contracts import RegisterChange,PreviewChange,AdoptChange
from app.domain.manuscripts.school_changes import SchoolChangeService

router=APIRouter(prefix='/api/v1/projects/{project_id}/manuscripts/{manuscript_id}',tags=['学校稿件变更'])

@router.post('/versions/{revision}/school-changes',status_code=201)
def register(project_id:str,manuscript_id:str,revision:int,request:RegisterChange,response:Response,store:Store,idempotency_key:Key):
    result,response.status_code=SchoolChangeService(store).register(project_id,manuscript_id,revision,request,idempotency_key);return result

@router.get('/school-changes')
def changes(project_id:str,manuscript_id:str,store:Store):return SchoolChangeService(store).list(project_id,manuscript_id)

@router.get('/school-changes/{change_id}')
def change(project_id:str,manuscript_id:str,change_id:str,store:Store):return SchoolChangeService(store).get(project_id,manuscript_id,change_id)

@router.post('/school-changes/{change_id}/preview')
def preview(project_id:str,manuscript_id:str,change_id:str,request:PreviewChange,store:Store):return SchoolChangeService(store).get(project_id,manuscript_id,change_id,request)

@router.post('/school-changes/{change_id}/adopt',status_code=201)
def adopt(project_id:str,manuscript_id:str,change_id:str,request:AdoptChange,response:Response,store:Store,idempotency_key:Key):
    result,response.status_code=SchoolChangeService(store).adopt(project_id,manuscript_id,change_id,request,idempotency_key);return result
