"""Read-only project PMC history; no network acquisition route."""
from fastapi import APIRouter, Response
from app.api.dataset_preparation import Store, Page
from app.domain.literature_pmc.service import LiteraturePmcService

router=APIRouter(prefix='/api/v1/projects/{project_id}/literature/pmc',tags=['PMC来源'])


@router.get('/receipts')
def receipts(project_id:str,store:Store,page:Page=1,project_reference_id:str|None=None):
    return LiteraturePmcService(store).list(project_id,page,project_reference_id)


@router.get('/receipts/{receipt_id}/source')
def source(project_id:str,receipt_id:str,store:Store,page:Page=1):
    return LiteraturePmcService(store).source(project_id,receipt_id,page)


@router.get('/receipts/{receipt_id}/raw/{index}')
def raw(project_id:str,receipt_id:str,index:int,store:Store):
    return Response(content=LiteraturePmcService(store).raw(project_id,receipt_id,index),media_type='application/xml',headers={'Content-Disposition':'attachment; filename="pmc-source.xml"','X-Content-Type-Options':'nosniff'})
