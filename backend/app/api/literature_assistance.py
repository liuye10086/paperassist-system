"""Project-private assistance task API; no automatic manual decisions."""
from fastapi import APIRouter, Response
from app.api.dataset_preparation import Store, Key, Page
from app.domain.literature_assistance.contracts import AssistanceRequest
from app.domain.literature_assistance.service import LiteratureAssistanceService
from app.domain.tasks.contracts import TaskView

router = APIRouter(prefix='/api/v1/projects/{project_id}/literature/assistance', tags=['文献模型建议'])


@router.post('/tasks', response_model=TaskView, status_code=202)
def create(project_id: str, request: AssistanceRequest, response: Response, store: Store, idempotency_key: Key):
    task, response.status_code = LiteratureAssistanceService(store).create(project_id, request, idempotency_key)
    return task


@router.get('/tasks')
def tasks(project_id: str, store: Store, page: Page = 1):
    return LiteratureAssistanceService(store).list(project_id, page)


@router.get('/tasks/{task_id}')
def task(project_id: str, task_id: str, store: Store):
    return LiteratureAssistanceService(store).get(project_id, task_id)
