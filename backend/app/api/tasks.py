"""Authenticated task reads and explicit versioned recovery."""
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from app.adapters.task_store import TaskStore
from app.domain.tasks.contracts import TaskEventPage, TaskView, TaskStatus, TaskType
from app.domain.tasks.wait_contracts import ResumeRequest
from app.domain.tasks.resume import TaskResumeService
from app.domain.tasks.workspace import TaskWorkspaceService
from app.domain.tasks.workspace_contracts import TaskListPage, TaskWorkspace


router = APIRouter(prefix='/api/v1/tasks', tags=['任务'])
project_router = APIRouter(prefix='/api/v1/projects', tags=['任务'])


def get_request_task_store(request: Request) -> TaskStore:
    return TaskStore(request.state.user['id'])


Store = Annotated[TaskStore, Depends(get_request_task_store)]


class RetryRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: int = Field(strict=True, ge=1, lt=2_147_483_647)


@router.post('/{task_id}/retry', response_model=TaskView, status_code=202)
def retry_task(task_id: str, request: RetryRequest, store: Store):
    store.require_mutable(task_id)
    task_type = store.get(task_id)['task_type']
    if task_type == 'boxplot':
        from app.domain.plot_tasks import retry_boxplot_task
        return retry_boxplot_task(store, task_id, request.expected_revision)
    if task_type == 'explanation':
        from app.domain.explanation_tasks import retry_explanation_task
        return retry_explanation_task(store, task_id, request.expected_revision)
    from app.domain.report_tasks import retry_word_task
    return retry_word_task(store, task_id, request.expected_revision)


def decimal_query_integer(value):
    # Query strings must be ASCII decimal before Pydantic integer coercion.
    # Integer defaults are supplied by FastAPI without an HTTP query string.
    if type(value) is int:
        return value
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        raise ValueError('分页参数须为十进制整数字符串。')
    return value


@project_router.get('/{project_id}/tasks', response_model=TaskListPage)
def list_project_tasks(
    project_id: str,
    store: Store,
    page: Annotated[int, Query(ge=1, le=1_000_000), BeforeValidator(decimal_query_integer)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50), BeforeValidator(decimal_query_integer)] = 10,
    status: TaskStatus | None = None,
    task_type: TaskType | None = None,
):
    return TaskWorkspaceService(store.user_id).list(project_id, page=page, page_size=page_size,
                                                   status=status, task_type=task_type)


@router.get('/{task_id}/workspace', response_model=TaskWorkspace)
def get_task_workspace(task_id: str, store: Store):
    return TaskWorkspaceService(store.user_id).get(task_id)


@router.post('/{task_id}/resume', response_model=TaskView, status_code=202)
def resume_task(
    task_id: str, request: ResumeRequest, store: Store,
    idempotency_key: Annotated[str, Header(min_length=1, max_length=128, pattern=r'^[\x21-\x7e]+$')],
):
    store.require_mutable(task_id)
    return TaskResumeService(store.user_id).resume(task_id, request, idempotency_key=idempotency_key)


@router.get('/{task_id}', response_model=TaskView)
def get_task(task_id: str, store: Store):
    return store.get(task_id)


@router.get('/{task_id}/events', response_model=TaskEventPage)
def get_task_events(
    task_id: str,
    store: Store,
    after: Annotated[int, Query(ge=0, le=2_147_483_647), BeforeValidator(decimal_query_integer)] = 0,
    limit: Annotated[int, Query(ge=1, le=100), BeforeValidator(decimal_query_integer)] = 50,
):
    return store.events(task_id, after=after, limit=limit)
