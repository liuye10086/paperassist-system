"""Configuration administration never accepts paths, credentials or executable rules."""
from typing import Annotated
from fastapi import APIRouter, Depends, Request
from app.core.exceptions import StorageError
from app.db.database import database_connection
from app.domain.admin_operations import require_identity
from app.domain.admin_configuration.service import Configurations

router=APIRouter(prefix='/api/v1/admin/configurations',tags=['配置治理'])


def service(request:Request):
    user=request.state.user['id']
    with database_connection() as db:require_identity(db,user)
    return Configurations(user)


Admin=Annotated[Configurations,Depends(service)]


def shape(body,keys):
    if not isinstance(body,dict) or set(body)!=set(keys):
        raise StorageError('configuration_invalid','配置请求字段无效。',422)


@router.get('')
def versions(admin:Admin):return admin.list()


@router.get('/current')
def current(admin:Admin):return admin.current()


@router.get('/catalog')
def catalog(admin:Admin):return admin.catalog()


@router.get('/events')
def events(admin:Admin):return admin.events()


@router.get('/bindings/{kind}/{object_id}')
def binding(kind:str,object_id:str,admin:Admin):return admin.binding(kind,object_id)


@router.post('/baseline',status_code=201)
def baseline(body:dict,admin:Admin):
    shape(body,());return admin.baseline()


@router.get('/{version_id}')
def detail(version_id:str,admin:Admin):return admin.detail(version_id)


@router.get('/{version_id}/diff')
def diff(version_id:str,admin:Admin,against:str|None=None):return admin.diff(version_id,against)


@router.post('/{version_id}/copy',status_code=201)
def copy(version_id:str,body:dict,admin:Admin):
    shape(body,());return admin.copy(version_id)


@router.post('/{version_id}/save',status_code=201)
def save(version_id:str,body:dict,admin:Admin):
    shape(body,('bundle',));return admin.save(version_id,body['bundle'])


@router.post('/{version_id}/validate')
def validate(version_id:str,body:dict,admin:Admin):
    shape(body,());return admin.validate(version_id)


@router.post('/{version_id}/activate')
def activate(version_id:str,body:dict,admin:Admin):
    shape(body,('expected_revision','reason','request_key'));return admin.switch(version_id,**body)


@router.post('/{version_id}/rollback')
def rollback(version_id:str,body:dict,admin:Admin):
    shape(body,('expected_revision','reason','request_key'));return admin.switch(version_id,operation='rollback',**body)
