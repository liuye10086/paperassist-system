"""HTTP routes for descriptive; business operations live in domain."""

from fastapi import APIRouter

from app.api.dependencies import Store, Settings
from app.domain import descriptive as operations
from app.domain.descriptive import RunRequest, AnalysisResult, ResultState

router = APIRouter(prefix='/api/v1/projects/{project_id}/files/{file_id}', tags=['描述统计'])


@router.get('/analysis-result', response_model=ResultState)
def get_result(project_id: str, file_id: str, store: Store):
    return operations.get_result(project_id, file_id, store)

@router.post('/analysis-runs', response_model=AnalysisResult)
def execute(project_id: str, file_id: str, request: RunRequest, store: Store, settings: Settings):
    return operations.execute(project_id, file_id, request, store, settings)
