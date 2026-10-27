"""Read-only runtime projections. Observations never come from HTTP clients."""
from fastapi import APIRouter, Request

from app.db.database import database_connection
from app.domain.admin_operations import require_identity
from app.domain.runtime_status import admin_status, public_status

router = APIRouter(tags=['运行状态'])


@router.get('/api/v1/runtime/status')
def runtime_status():
    return public_status()


@router.get('/api/v1/admin/runtime/status')
def administrative_status(request: Request):
    with database_connection() as db:
        require_identity(db, request.state.user['id'])
        return admin_status(db)
