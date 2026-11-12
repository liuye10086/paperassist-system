"""Administrator grants and the analyst's assigned-project index."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from app.adapters.storage import _storage_connection
from app.api.admin import AccountReason, Identifier, Paging
from app.api.projects import ProjectPage, Store
from app.api.tasks import decimal_query_integer
from app.core.exceptions import StorageError
from app.domain.admin_operations import page_query, require_identity


router = APIRouter(prefix='/api/v1', tags=['项目分配'])


class AssignmentsQuery(Paging):
    q: str = Field(default='', max_length=254, pattern=r'^[^\x00-\x1f\x7f]*$')


class AssignmentChange(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    analyst_id: Identifier | None
    expected_revision: int = Field(ge=0, lt=9_007_199_254_740_991)
    reason: AccountReason


class AssignmentRow(BaseModel):
    id: str
    name: str
    research_topic: str
    customer_email: str
    analyst_id: str | None
    analyst_email: str | None
    revision: int
    submitted_version: int | None
    progress_status: str
    updated_at: str


class AssignmentEvent(BaseModel):
    id: str
    actor_email: str
    previous_analyst_email: str | None
    analyst_email: str | None
    revision: int
    reason: str
    created_at: datetime


class AssignmentPage(BaseModel):
    items: list[AssignmentRow]
    total: int
    page: int
    page_size: int


class AssignmentEventPage(BaseModel):
    items: list[AssignmentEvent]
    total: int
    page: int
    page_size: int


_ELIGIBLE = "analyst.role='analyst' AND analyst.active AND analyst.review_status='approved'"
_ACTIVE_GRANT = f"({_ELIGIBLE} AND customer.active AND customer.review_status='approved')"
_SOURCE = f'''projects p JOIN users customer ON customer.id=p.owner_id
    LEFT JOIN project_assignments a ON a.project_id=p.id AND a.owner_id=p.owner_id
    LEFT JOIN users analyst ON analyst.id=a.analyst_id
    LEFT JOIN LATERAL (
        SELECT r.id,r.version FROM research_requirement_versions r
        WHERE r.project_id=p.id AND r.operation='confirm' ORDER BY r.version DESC LIMIT 1
    ) submitted ON true
    LEFT JOIN customer_requirement_progress progress
        ON progress.requirement_version_id=submitted.id AND progress.project_id=p.id
        AND ((progress.assignment_revision IS NULL AND a.project_id IS NULL)
             OR (progress.assignment_revision=a.revision AND {_ACTIVE_GRANT}))'''
_FIELDS = f'''p.id,p.name,p.research_topic,customer.email AS customer_email,
    a.analyst_id,analyst.email AS analyst_email,coalesce(a.revision,0) AS revision,
    submitted.version AS submitted_version,
    CASE WHEN submitted.id IS NULL THEN 'draft'
         WHEN EXISTS (
             SELECT 1 FROM customer_delivery_publications published
             JOIN delivery_snapshots snapshot ON snapshot.id=published.snapshot_id AND snapshot.project_id=p.id
             WHERE published.project_id=p.id AND snapshot.requirement_version_id=submitted.id
                 AND snapshot.user_id=p.owner_id
         ) THEN 'delivered'
         WHEN progress.status IS NOT NULL THEN progress.status
         WHEN {_ACTIVE_GRANT} THEN 'assigned'
         ELSE 'pending_assignment' END AS progress_status,
    greatest(p.updated_at,to_char(a.updated_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"')) AS updated_at'''
_CUSTOMER_PROJECT = "customer.role='customer'"


def _customer_project(db, project_id, *, lock=False):
    row = db.execute('''SELECT p.owner_id FROM projects p JOIN users customer ON customer.id=p.owner_id
        WHERE p.id=%s AND ''' + _CUSTOMER_PROJECT + (' FOR UPDATE OF p' if lock else ''), (project_id,)).fetchone()
    if row is None:
        raise StorageError('project_not_found', '项目不存在，请刷新项目列表。', 404)
    return row


def _revision_conflict():
    return StorageError('project_assignment_revision_conflict', '项目分配已更新，请刷新后再操作。', 409)


@router.get('/admin/project-assignments', response_model=AssignmentPage)
def list_assignments(request: Request, query: Annotated[AssignmentsQuery, Query()]):
    where, values = [_CUSTOMER_PROJECT], []
    q = query.q.strip()
    if q:
        where.append('(' + ' OR '.join(f'strpos(lower({column}),lower(%s))>0' for column in (
            'p.name', 'p.research_topic', 'customer.email', 'analyst.email',
        )) + ')')
        values.extend((q,) * 4)
    with _storage_connection() as db:
        require_identity(db, request.state.user['id'])
        return page_query(db, _FIELDS, _SOURCE, where, values, query.page, query.page_size, 'updated_at DESC,p.id')


@router.patch('/admin/project-assignments/{project_id}', response_model=AssignmentRow)
def change_assignment(project_id: str, body: AssignmentChange, request: Request):
    actor_id = request.state.user['id']
    with _storage_connection(write=True) as db:
        require_identity(db, actor_id)
        actor = db.execute('SELECT email FROM users WHERE id=%s', (actor_id,)).fetchone()
        project = _customer_project(db, project_id, lock=True)
        current = db.execute('''SELECT a.revision,a.analyst_id,analyst.email FROM project_assignments a
            LEFT JOIN users analyst ON analyst.id=a.analyst_id WHERE a.project_id=%s''', (project_id,)).fetchone()
        revision = current['revision'] if current else 0
        previous_id = current['analyst_id'] if current else None
        if revision != body.expected_revision:
            raise _revision_conflict()
        analyst = None
        if body.analyst_id is not None:
            analyst = db.execute('SELECT analyst.email FROM users analyst WHERE analyst.id=%s AND ' + _ELIGIBLE
                                 + ' FOR SHARE OF analyst', (body.analyst_id,)).fetchone()
            if analyst is None:
                raise StorageError('project_assignment_analyst_invalid', '请选择已通过审核且已启用的分析员。', 422)

        if previous_id != body.analyst_id:
            updated = db.execute('''INSERT INTO project_assignments(project_id,owner_id,analyst_id,revision,updated_by)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT(project_id) DO UPDATE SET analyst_id=excluded.analyst_id,revision=excluded.revision,
                    updated_by=excluded.updated_by,updated_at=excluded.updated_at
                WHERE project_assignments.revision=%s AND project_assignments.owner_id=excluded.owner_id
                RETURNING revision,updated_at''',
                (project_id, project['owner_id'], body.analyst_id, revision + 1, actor_id, revision)).fetchone()
            if updated is None:
                raise _revision_conflict()
            db.execute('''INSERT INTO project_assignment_events(id,project_id,owner_id,revision,actor_id,actor_email,
                previous_analyst_id,previous_analyst_email,analyst_id,analyst_email,reason,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (str(uuid4()), project_id, project['owner_id'], updated['revision'], actor_id, actor['email'],
                 previous_id, current['email'] if current else None, body.analyst_id, analyst['email'] if analyst else None,
                 body.reason, updated['updated_at']))
        return dict(db.execute('SELECT ' + _FIELDS + ' FROM ' + _SOURCE + ' WHERE p.id=%s', (project_id,)).fetchone())


@router.get('/admin/project-assignments/{project_id}/events', response_model=AssignmentEventPage)
def list_assignment_events(project_id: str, request: Request, query: Annotated[Paging, Query()]):
    with _storage_connection() as db:
        require_identity(db, request.state.user['id'])
        _customer_project(db, project_id)
        return page_query(db, 'id,actor_email,previous_analyst_email,analyst_email,revision,reason,created_at',
                          'project_assignment_events', ['project_id=%s'], [project_id],
                          query.page, query.page_size, 'revision DESC')


@router.get('/assigned-projects', response_model=ProjectPage)
def list_assigned_projects(
    request: Request,
    store: Store,
    page: Annotated[int, Query(ge=1, le=1_000_000), BeforeValidator(decimal_query_integer)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100), BeforeValidator(decimal_query_integer)] = 10,
    q: str = '',
    project_type: Annotated[Literal['sci', 'thesis', 'research'] | None, Query(alias='type')] = None,
):
    if request.state.user['role'] != 'analyst':
        raise StorageError('permission_denied', '仅分析员可查看分配给我的项目。', 403)
    return store.query_projects(page=page, page_size=page_size, q=q, project_type=project_type, assigned=True)
