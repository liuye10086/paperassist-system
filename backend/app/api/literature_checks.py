"""Owner-only independent saved-source check receipts."""
from typing import Annotated
from fastapi import APIRouter,Response,Depends
from app.api.dataset_preparation import Store,Key,Page
from app.domain.literature_checks.contracts import CheckRequest
from app.domain.literature_checks.service import LiteratureCheckService

router=APIRouter(prefix='/api/v1/projects/{project_id}/literature/checks',tags=['文献独立核验记录'])


def get_check_service(store:Store):
    return LiteratureCheckService(store)


Service=Annotated[LiteratureCheckService,Depends(get_check_service)]


@router.get('/config')
def config(project_id:str,service:Service): return service.config(project_id)


@router.get('/candidates')
def candidates(project_id:str,service:Service,page:Page=1): return service.candidates(project_id,page)


@router.get('/references/{project_reference_id}')
def reference(project_id:str,project_reference_id:str,service:Service): return service.reference(project_id,project_reference_id)


@router.get('/references/{project_reference_id}/history')
def history(project_id:str,project_reference_id:str,service:Service,page:Page=1): return service.history(project_id,project_reference_id,page)


@router.post('/references/{project_reference_id}/receipts',status_code=201)
def create(project_id:str,project_reference_id:str,request:CheckRequest,response:Response,service:Service,idempotency_key:Key):
    view,response.status_code=service.create(project_id,project_reference_id,request,idempotency_key)
    return view
