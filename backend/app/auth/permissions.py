from contextvars import ContextVar
from dataclasses import dataclass
from time import time

from fastapi import Request
from starlette.concurrency import run_in_threadpool

from app.auth.config import settings
from app.auth.middleware import COOKIE_NAME
from app.auth.revocations import session_expiry_reason
from app.auth.sci_access import (PAPER_PROJECT_OPERATIONS, PAPER_READ_ONLY_TASK_TYPES, PAPER_RECOVERY_TASK_TYPES,
                                PAPER_TASK_TYPES, REVIEW_TASK_TYPES,
                                SCI_PROJECT_OPERATIONS, SCI_TASK_TYPES, THESIS_PROJECT_OPERATIONS, THESIS_TASK_TYPES)
from app.auth.service import digest, resolve_session
from app.core.exceptions import StorageError


READ_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS'})
PROJECT_PATH = '/api/v1/projects/{project_id}'
CUSTOMER_WORKSPACE_PATH = PROJECT_PATH + '/customer-workspace'
MANUSCRIPTS_PATH = PROJECT_PATH + '/manuscripts'
TASK_PATH = '/api/v1/tasks/{task_id}'


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
    ('GET', PROJECT_PATH + '/sci-settings'),
    ('PUT', PROJECT_PATH + '/sci-settings'),
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
    ('GET', PROJECT_PATH + '/research-intake'),
    ('GET', CUSTOMER_WORKSPACE_PATH + '/summary'),
    ('GET', CUSTOMER_WORKSPACE_PATH + '/deliveries'),
    ('GET', CUSTOMER_WORKSPACE_PATH + '/deliveries/{snapshot_id}'),
    ('GET', CUSTOMER_WORKSPACE_PATH + '/deliveries/{snapshot_id}/members/{member_id}/download'),
    ('GET', CUSTOMER_WORKSPACE_PATH + '/deliveries/{snapshot_id}/download'),
    ('POST', CUSTOMER_WORKSPACE_PATH + '/feedback'),
})

CUSTOMER_ANALYSIS_OPERATIONS = frozenset({
    ('GET', PROJECT_PATH + '/bio-upload-batches'),
    ('POST', PROJECT_PATH + '/bio-upload-batches'),
    ('GET', PROJECT_PATH + '/bio-upload-batches/{batch_id}'),
    ('POST', PROJECT_PATH + '/bio-upload-batches/{batch_id}/items/{item_id}'),
    ('POST', PROJECT_PATH + '/requirements'),
    ('GET', PROJECT_PATH + '/requirements'),
    ('GET', PROJECT_PATH + '/requirements/requests/{key}'),
    ('GET', PROJECT_PATH + '/requirements/{version_id}'),
    ('GET', CUSTOMER_WORKSPACE_PATH + '/progress'),
    ('POST', CUSTOMER_WORKSPACE_PATH + '/material-submissions'),
})

CUSTOMER_MANUSCRIPT_READS = frozenset(('GET', MANUSCRIPTS_PATH + suffix) for suffix in (
    '', '/{manuscript_id}', '/{manuscript_id}/versions/{revision}',
    '/{manuscript_id}/versions/{revision}/exports',
    '/{manuscript_id}/exports/{export_id}', '/{manuscript_id}/exports/{export_id}/download',
))

CUSTOMER_MANUSCRIPT_TASK_OPERATIONS = frozenset({
    ('GET', TASK_PATH),
    ('GET', TASK_PATH + '/events'),
    ('GET', TASK_PATH + '/workspace'),
    ('POST', TASK_PATH + '/retry'),
    ('POST', TASK_PATH + '/cancel'),
})
CUSTOMER_PAPER_TASK_RECOVERY_OPERATIONS = frozenset({
    ('POST', TASK_PATH + '/resume'),
})


def require_customer_project_kind(owner_id, project_id, kinds):
    from app.db.database import database_connection

    with database_connection() as db:
        row = db.execute('SELECT project_type FROM projects WHERE id=%s AND owner_id=%s',
                         (project_id, owner_id)).fetchone()
    if row is None:
        raise StorageError('project_not_found', '项目不存在，请刷新项目列表。', 404)
    if row['project_type'] not in kinds:
        raise StorageError('customer_project_type_forbidden', '此操作与当前项目类型不匹配。', 403)


def require_visible_paper_task(db, assets, task):
    from app.adapters.task_store import source_conflict
    from app.domain.manuscripts.sources import require_visible_snapshot

    kind, project, snapshot = task['task_type'], task['project_id'], task['input_snapshot']
    if kind in REVIEW_TASK_TYPES:
        from app.domain.review_rounds.access import require_review_task

        require_review_task(db, assets, task)
    elif kind in ('manuscript_draft', 'manuscript_docx'):
        from app.domain.manuscripts.service import ManuscriptService

        ManuscriptService(assets).verify_task(db, task)
    elif kind == 'school_template_parse':
        from app.domain.school_templates.service import SchoolTemplateService, input_version

        service = SchoolTemplateService(assets)
        row = service.row(db, project, input_version(task)['template_version_id'])
        if row['task_id'] != task['id']:
            raise source_conflict()
        service.validate(db, row)
    elif kind == 'journal_format_check':
        from app.domain.journals.format_service import FormatService, input_version

        row = FormatService(assets).check_row(db, project, input_version(task)['check_id'])
        if row['task_id'] != task['id']:
            raise source_conflict()
    elif kind == 'journal_adaptation':
        from app.domain.journals.adaptation_service import AdaptationService, input_version

        row = AdaptationService(assets).adaptation_row(db, project, input_version(task)['adaptation_id'])
        if row['task_id'] != task['id']:
            raise source_conflict()
    elif kind == 'layout_docx':
        from app.domain.layout_exports.service import LayoutExportService

        service = LayoutExportService(assets)
        row = service.row(db, project, snapshot['export_id'])
        if row['task_id'] != task['id']:
            raise source_conflict()
        service.verify_source(db, row)
    else:
        require_visible_snapshot(assets, db, project, snapshot)
        if kind == 'manuscript_writing':
            require_visible_snapshot(assets, db, project, snapshot['base_snapshot'])


def require_customer_manuscript_task(owner_id, task_id, recovery=False, *, read_only=False):
    from app.adapters.task_store import missing_task
    from app.db.database import database_connection
    from app.domain.report_collections.service import scoped_store

    with database_connection() as db:
        row = db.execute('''SELECT t.*,p.project_type FROM tasks t JOIN projects p ON p.id=t.project_id
            WHERE t.id=%s AND t.user_id=%s AND p.owner_id=%s AND p.project_type IN ('sci', 'thesis')''',
            (task_id, owner_id, owner_id)).fetchone()
        if row is None:
            raise missing_task()
        project_tasks = SCI_TASK_TYPES if row['project_type'] == 'sci' else THESIS_TASK_TYPES
        allowed = PAPER_RECOVERY_TASK_TYPES if recovery else PAPER_TASK_TYPES + project_tasks
        if read_only:
            allowed += PAPER_READ_ONLY_TASK_TYPES
        if row['task_type'] not in allowed:
            raise missing_task()
        assets = scoped_store(owner_id)
        assets.customer = True
        try:
            require_visible_paper_task(db, assets, row)
        except StorageError as exc:
            if exc.status == 404:
                raise missing_task() from None
            raise


async def require_customer_permission(request: Request) -> None:
    user = getattr(request.state, 'user', None)
    if not user:
        return
    route = request.scope['route']
    operation = request.method, route.path_format
    if operation in CUSTOMER_OPERATIONS:
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

    if user['role'] != 'customer':
        return
    if operation in CUSTOMER_ANALYSIS_OPERATIONS:
        await run_in_threadpool(require_customer_project_kind, user['id'], request.path_params['project_id'], ('research',))
    elif operation in SCI_PROJECT_OPERATIONS:
        await run_in_threadpool(require_customer_project_kind, user['id'], request.path_params['project_id'], ('sci',))
    elif operation in THESIS_PROJECT_OPERATIONS:
        await run_in_threadpool(require_customer_project_kind, user['id'], request.path_params['project_id'], ('thesis',))
    elif operation in PAPER_PROJECT_OPERATIONS or operation in CUSTOMER_MANUSCRIPT_READS:
        await run_in_threadpool(require_customer_project_kind, user['id'], request.path_params['project_id'], ('sci', 'thesis'))
    elif operation in CUSTOMER_MANUSCRIPT_TASK_OPERATIONS:
        await run_in_threadpool(require_customer_manuscript_task, user['id'], request.path_params['task_id'],
                                read_only=request.method=='GET')
    elif operation in CUSTOMER_PAPER_TASK_RECOVERY_OPERATIONS:
        await run_in_threadpool(require_customer_manuscript_task, user['id'], request.path_params['task_id'], True)
    else:
        raise StorageError('customer_operation_forbidden', '客户账号无权执行此操作。', 403)


def require_customer_role(request: Request) -> None:
    if request.state.user['role'] != 'customer':
        raise StorageError('permission_denied', '此工作台仅供客户账号使用。', 403)
