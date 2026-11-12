from contextvars import ContextVar
from dataclasses import dataclass
from time import time

from fastapi import Request
from starlette.concurrency import run_in_threadpool

from app.auth.config import settings
from app.auth.middleware import COOKIE_NAME
from app.auth.revocations import session_expiry_reason
from app.auth.service import digest, resolve_session
from app.core.exceptions import StorageError


READ_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS'})
PROJECT_PATH = '/api/v1/projects/{project_id}'
CUSTOMER_WORKSPACE_PATH = PROJECT_PATH + '/customer-workspace'


@dataclass(frozen=True)
class WriteSession:
    user_id: str
    role: str
    token_hash: str


_write_session = ContextVar[WriteSession | None]('request_write_session', default=None)


def current_write_session() -> WriteSession | None:
    return _write_session.get()


def require_write_session(db, session: WriteSession) -> None:
    row = db.execute('''SELECT u.role,u.active,u.review_status,s.last_seen_at,s.expires_at
        FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=%s AND u.id=%s''',
        (session.token_hash, session.user_id)).fetchone()
    if (row is None or row['role'] != session.role or row['review_status'] != 'approved'
            or session_expiry_reason(row, time(), settings().idle_seconds)):
        raise StorageError('authentication_required', '请登录后继续。', 401)


async def bind_write_session(request: Request):
    user = getattr(request.state, 'user', None)
    session = None
    if user is not None and request.method not in READ_METHODS:
        token = request.cookies.get(COOKIE_NAME)
        if token is None:
            raise StorageError('authentication_required', '请登录后继续。', 401)
        session = WriteSession(user['id'], user['role'], digest(token))
    marker = _write_session.set(session)
    try:
        yield
    finally:
        _write_session.reset(marker)

# Match the registered route and method so new internal read and write routes
# stay closed to customers by default.
CUSTOMER_OPERATIONS = frozenset({
    ('GET', '/api/v1/auth/me'),
    ('GET', '/api/v1/auth/preferences'),
    ('POST', '/api/v1/auth/logout'),
    ('POST', '/api/v1/auth/change-password'),
    ('PATCH', '/api/v1/auth/preferences'),
    ('GET', '/api/v1/projects'),
    ('POST', '/api/v1/projects'),
    ('GET', '/api/v1/project-create-requests/{key}'),
    ('GET', PROJECT_PATH),
    ('PATCH', PROJECT_PATH),
    ('GET', PROJECT_PATH + '/language'),
    ('PATCH', PROJECT_PATH + '/language'),
    ('POST', '/api/v1/excel/preview'),
    ('GET', PROJECT_PATH + '/files'),
    ('POST', PROJECT_PATH + '/files'),
    ('GET', PROJECT_PATH + '/files/{file_id}/preview'),
    ('GET', PROJECT_PATH + '/files/{file_id}/download'),
    ('PUT', PROJECT_PATH + '/files/{file_id}/purposes'),
    ('GET', PROJECT_PATH + '/file-batches'),
    ('POST', PROJECT_PATH + '/file-batches'),
    ('GET', PROJECT_PATH + '/file-batches/{batch_id}'),
    ('POST', PROJECT_PATH + '/file-batches/{batch_id}/items/{item_id}'),
    ('GET', PROJECT_PATH + '/bio-upload-batches'),
    ('POST', PROJECT_PATH + '/bio-upload-batches'),
    ('GET', PROJECT_PATH + '/bio-upload-batches/{batch_id}'),
    ('POST', PROJECT_PATH + '/bio-upload-batches/{batch_id}/items/{item_id}'),
    ('GET', PROJECT_PATH + '/research-intake'),
    ('POST', PROJECT_PATH + '/requirements'),
    ('GET', PROJECT_PATH + '/requirements'),
    ('GET', PROJECT_PATH + '/requirements/requests/{key}'),
    ('GET', PROJECT_PATH + '/requirements/{version_id}'),
    ('GET', CUSTOMER_WORKSPACE_PATH + '/progress'),
    ('GET', CUSTOMER_WORKSPACE_PATH + '/deliveries'),
    ('GET', CUSTOMER_WORKSPACE_PATH + '/deliveries/{snapshot_id}'),
    ('GET', CUSTOMER_WORKSPACE_PATH + '/deliveries/{snapshot_id}/members/{member_id}/download'),
    ('GET', CUSTOMER_WORKSPACE_PATH + '/deliveries/{snapshot_id}/download'),
    ('POST', CUSTOMER_WORKSPACE_PATH + '/feedback'),
})


async def require_customer_permission(request: Request) -> None:
    user = getattr(request.state, 'user', None)
    if not user:
        return
    route = request.scope['route']
    if (request.method, route.path_format) in CUSTOMER_OPERATIONS:
        return

    if user['role'] != 'customer' and request.method not in READ_METHODS:
        # Authentication runs before FastAPI reads the request body. A role
        # change can revoke the session while that body is still arriving.
        token = request.cookies.get(COOKIE_NAME)
        session = await run_in_threadpool(resolve_session, token) if token else None
        if session is None:
            raise StorageError('authentication_required', '请登录后继续。', 401)
        user = session['user']
        request.state.user = user

    if user['role'] == 'customer':
        raise StorageError('customer_operation_forbidden', '客户账号可提交需求、资料和反馈。分析由分析员执行。', 403)


def require_customer_role(request: Request) -> None:
    if request.state.user['role'] != 'customer':
        raise StorageError('permission_denied', '此工作台仅供客户账号使用。', 403)
