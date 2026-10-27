"""Safe capacity metadata. Research access remains strictly owner scoped."""
from typing import Literal
from datetime import datetime,timezone
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from app.core.config import get_data_dir
from app.core.exceptions import StorageError
from app.db.database import database_connection
from app.domain.admin_operations import require_identity
from app.domain.storage_governance.service import disk_status,inventory,usage,set_policy,reconcile_intents

router=APIRouter(prefix='/api/v1',tags=['存储治理'])


def identity(request):
    return getattr(request.state,'user',{}).get('id')


def fresh_usage(db,*,user_id=None,project_id=None):
    # API owns this single writer transaction; domain helpers never nest one.
    # Reconciliation commits even if a later, separate upload is rejected.
    unresolved=reconcile_intents(db,get_data_dir())
    value=usage(db,user_id=user_id,project_id=project_id)
    value.update(reconciled_at=datetime.now(timezone.utc).isoformat(),
        reconciliation_status='unresolved' if unresolved else 'current')
    if unresolved:value['status']='unknown'
    if user_id is None:value['unattributed_intent_count']=unresolved
    return value


@router.get('/me/storage')
def own_storage(request:Request,project_id:str|None=None):
    with database_connection(write=True) as db:
        user=require_identity(db,identity(request),admin=False)
        if project_id is not None and not db.execute('SELECT id FROM projects WHERE id=%s AND owner_id=%s',(project_id,user['id'])).fetchone():
            raise StorageError('project_not_found','项目不存在。',404)
        return {**fresh_usage(db,user_id=user['id'],project_id=project_id), 'disk':disk_status(get_data_dir())}


@router.get('/admin/storage')
def admin_storage(request:Request):
    with database_connection(write=True) as db:
        require_identity(db,identity(request))
        policies=[dict(row) for row in db.execute('SELECT scope_type,scope_id,mode,limit_bytes,revision,updated_at FROM storage_policies ORDER BY scope_type,scope_id')]
        scan=db.execute('SELECT summary FROM storage_inventory_scans WHERE id=1').fetchone()
        return {**fresh_usage(db),'disk':disk_status(get_data_dir()),'policies':policies,'inventory':scan['summary'] if scan else None}


@router.get('/admin/storage/recovery')
def recovery_status(request:Request):
    from app.core.config import local_config
    from app.db.database import get_database_config
    from app.maintenance.backup_manifest import status_summary
    with database_connection() as db:
        require_identity(db,identity(request))
        return status_summary(local_config().get('PAPERASSIST_RECOVERY_STATUS_FILE'),get_database_config().schema)


@router.post('/admin/storage/scan')
def scan_storage(request:Request):
    with database_connection(write=True) as db:
        require_identity(db,identity(request))
        scanned=inventory(db,get_data_dir())
        return {**usage(db),'disk':disk_status(get_data_dir()),'inventory':scanned}


class StoragePolicy(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    mode:Literal['enforced','observe_only']
    limit_bytes:int=Field(ge=0,le=2**63-1)
    expected_revision:int=Field(ge=0)
    reason:str=Field(min_length=5,max_length=500)


@router.put('/admin/storage/policies/{scope_type}/{scope_id}')
def update_storage_policy(request:Request,scope_type:Literal['user','project'],scope_id:str,body:StoragePolicy):
    with database_connection(write=True) as db:
        require_identity(db,identity(request))
        return set_policy(db,scope_type,scope_id,body.limit_bytes,body.mode,
            expected_revision=body.expected_revision,actor_user_id=identity(request),reason=body.reason)


@router.get('/admin/storage/policy-events')
def policy_events(request:Request):
    with database_connection() as db:
        require_identity(db,identity(request))
        return {'items':[dict(row) for row in db.execute('SELECT id,scope_type,scope_id,revision,actor_user_id,reason,before_limit_bytes,after_limit_bytes,before_mode,after_mode,created_at FROM storage_policy_events ORDER BY created_at DESC,id LIMIT 100')]}
