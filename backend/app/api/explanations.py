"""HTTP routes for explanations; business operations live in domain."""

from typing import Annotated

from fastapi import APIRouter, Header, Response

from app.api.dependencies import Store
from app.domain import explanation_tasks as operations
from app.domain.explanations import ExplanationRequest

router = APIRouter(prefix='/api/v1/projects/{project_id}/files/{file_id}/analysis-runs/{run_id}', tags=['结果解释'])


@router.get('/explanation')
def get_explanation(project_id: str, file_id: str, run_id: str, store: Store):
    return operations.get_explanation(project_id, file_id, run_id, store)

@router.post('/explanation')
def generate(project_id: str, file_id: str, run_id: str, request: ExplanationRequest, store: Store, response: Response,
             idempotency_key: Annotated[str | None, Header(alias='Idempotency-Key')] = None):
    result, response.status_code = operations.submit_explanation(project_id, file_id, run_id, request, store, idempotency_key)
    return result
