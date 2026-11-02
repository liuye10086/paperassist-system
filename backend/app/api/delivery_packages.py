"""Authenticated delivery registration, freezing, packaging and acceptance."""
from fastapi import APIRouter,Response
from app.api.bio_datasets import Store,Key
from app.domain.delivery_packages.contracts import SnapshotWrite,AcceptanceWrite,Strict
from app.domain.delivery_packages.service import DeliveryService
from urllib.parse import quote
router=APIRouter(prefix='/api/v1/projects/{project_id}/deliveries/{delivery_id}',tags=['交付快照'])

@router.get('/candidates')
def candidates(project_id:str,delivery_id:str,store:Store):return DeliveryService(store).candidates(project_id,delivery_id)

@router.post('/snapshots/preview')
def preview(project_id:str,delivery_id:str,request:SnapshotWrite,store:Store):return DeliveryService(store).preview(project_id,delivery_id,request)

@router.post('/snapshots')
def freeze(project_id:str,delivery_id:str,request:SnapshotWrite,store:Store,idempotency_key:Key,response:Response):
    result,response.status_code=DeliveryService(store).freeze(project_id,delivery_id,request,idempotency_key);return result

@router.get('/snapshots')
def listing(project_id:str,delivery_id:str,store:Store):return DeliveryService(store).listing(project_id,delivery_id)

@router.get('/snapshots/requests/{key}')
def recover(project_id:str,delivery_id:str,key:str,store:Store):return DeliveryService(store).listing(project_id,delivery_id,key)

@router.get('/snapshots/{identifier}')
def get(project_id:str,delivery_id:str,identifier:str,store:Store):return DeliveryService(store).get(project_id,delivery_id,identifier)

@router.post('/snapshots/{identifier}/package')
def package(project_id:str,delivery_id:str,identifier:str,request:Strict,store:Store,idempotency_key:Key,response:Response):
    from app.domain.research_intake.service import request_key
    request_key(idempotency_key)
    result,response.status_code=DeliveryService(store).package(project_id,delivery_id,identifier,idempotency_key);return result

@router.get('/snapshots/{identifier}/package')
def package_status(project_id:str,delivery_id:str,identifier:str,store:Store):return DeliveryService(store).package(project_id,delivery_id,identifier)[0]

def attachment(meta,raw):return Response(raw,media_type='application/octet-stream',headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(meta.get('filename',meta.get('name','delivery'))),'X-Content-Type-Options':'nosniff','X-Content-SHA256':meta['sha256']})

@router.get('/snapshots/{identifier}/download')
def download(project_id:str,delivery_id:str,identifier:str,store:Store):return attachment(*DeliveryService(store).download(project_id,delivery_id,identifier))

@router.get('/snapshots/{identifier}/members/{member_id}/download')
def member(project_id:str,delivery_id:str,identifier:str,member_id:str,store:Store):return attachment(*DeliveryService(store).member(project_id,delivery_id,identifier,member_id))

@router.post('/snapshots/{identifier}/acceptances')
def accept(project_id:str,delivery_id:str,identifier:str,request:AcceptanceWrite,store:Store,idempotency_key:Key,response:Response):
    result,response.status_code=DeliveryService(store).acceptance(project_id,delivery_id,identifier,request,idempotency_key);return result

@router.get('/snapshots/{identifier}/acceptances')
def acceptances(project_id:str,delivery_id:str,identifier:str,store:Store):return DeliveryService(store).acceptances(project_id,delivery_id,identifier)
