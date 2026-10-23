"""Explicit user returns, next-round inputs and independent user progress."""
from fastapi import APIRouter, Response
from app.api.dataset_preparation import Store, Key
from app.domain.review_rounds.return_contracts import RegisterReturn, PreviewReturn, AdoptReturn, ProgressRequest
from app.domain.review_rounds.returns import ReviewReturnService
from app.domain.review_rounds.lineage import continuation_context
from app.domain.review_rounds.progress import ReviewProgressService

router = APIRouter(prefix='/api/v1/projects/{project_id}/reviews', tags=['用户回传与返修进展'])


@router.get('/rounds/{identity}/continuation-context')
def context(project_id: str, identity: str, store: Store):
    return continuation_context(store, project_id, identity)


@router.post('/rounds/{identity}/returns', status_code=201)
def register(project_id: str, identity: str, request: RegisterReturn, response: Response, store: Store, idempotency_key: Key):
    result, response.status_code = ReviewReturnService(store).register(project_id, identity, request, idempotency_key)
    return result


@router.get('/returns/{identity}')
def get(project_id: str, identity: str, store: Store):
    return ReviewReturnService(store).get(project_id, identity)


@router.post('/returns/{identity}/preview')
def preview(project_id: str, identity: str, request: PreviewReturn, store: Store):
    return ReviewReturnService(store).get(project_id, identity, request)


@router.post('/returns/{identity}/adopt', status_code=201)
def adopt(project_id: str, identity: str, request: AdoptReturn, response: Response, store: Store, idempotency_key: Key):
    result, response.status_code = ReviewReturnService(store).adopt(project_id, identity, request, idempotency_key)
    return result


@router.get('/progress')
def progress(project_id: str, store: Store):
    return ReviewProgressService(store).listing(project_id)


@router.post('/progress', status_code=201)
def save_progress(project_id: str, request: ProgressRequest, response: Response, store: Store, idempotency_key: Key):
    result, response.status_code = ReviewProgressService(store).create(project_id, request, idempotency_key)
    return result
