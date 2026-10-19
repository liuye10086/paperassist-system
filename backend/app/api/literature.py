"""Project literature API; reading never retrieves or verifies external content."""
from typing import Literal
from fastapi import APIRouter, Response

from app.api.dataset_preparation import Store, Key, Page
from app.domain.literature.contracts import SearchRequest, SelectionRequest
from app.domain.literature.service import LiteratureService, configuration
from app.domain.tasks.contracts import TaskView

router = APIRouter(prefix='/api/v1/projects/{project_id}/literature', tags=['文献检索与候选'])


@router.get('/config')
def config(project_id: str, store: Store):
    service = LiteratureService(store)
    with service.store.connection() as db:
        service.store.require_project(db, project_id)
    return configuration()


@router.post('/searches', response_model=TaskView, status_code=202)
def create(project_id: str, request: SearchRequest, response: Response, store: Store, idempotency_key: Key):
    task, status = LiteratureService(store).create(project_id, request, idempotency_key)
    response.status_code = status
    return task


@router.get('/searches')
def searches(project_id: str, store: Store, page: Page = 1):
    return LiteratureService(store).searches(project_id, page)


@router.get('/searches/{search_id}')
def search(project_id: str, search_id: str, store: Store):
    return LiteratureService(store).search(project_id, search_id)


@router.get('/references')
def references(project_id: str, store: Store, page: Page = 1, search_id: str | None = None,
               selection: Literal['candidate','shortlisted','excluded'] | None = None):
    return LiteratureService(store).references(project_id, page, search_id, selection)


@router.get('/references/{reference_id}')
def reference(project_id: str, reference_id: str, store: Store, page: Page = 1, search_id: str | None = None):
    return LiteratureService(store).reference(project_id, reference_id, page, search_id)


@router.patch('/references/{reference_id}')
def select(project_id: str, reference_id: str, request: SelectionRequest, store: Store):
    return LiteratureService(store).select(project_id, reference_id, request)


@router.get('/receipts/{receipt_id}/source')
def source(project_id: str, receipt_id: str, store: Store):
    raw, operation = LiteratureService(store).source(project_id, receipt_id)
    extension = 'json' if operation == 'esearch' else 'xml'
    return Response(raw, media_type='application/octet-stream', headers={
        'Content-Disposition': f'attachment; filename="pubmed-{operation}.{extension}"', 'X-Content-Type-Options': 'nosniff'})
