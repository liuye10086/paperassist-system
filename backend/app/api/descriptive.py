"""HTTP routes for descriptive; business operations live in domain."""

from fastapi import APIRouter
from app.domain.tasks.contracts import TaskView

from app.api.dependencies import Store, Settings
from app.domain import descriptive as operations
from app.domain.descriptive import RunRequest, AnalysisResult, ResearchAnalysisResult, ModernDescriptiveResult, CorrelationResult, ComparisonResult, ResultState
from app.domain.descriptive import RegressionResult, RocResult, SurvivalResult

router = APIRouter(prefix='/api/v1/projects/{project_id}/files/{file_id}', tags=['描述统计'])


@router.get('/analysis-result', response_model=ResultState)
def get_result(project_id: str, file_id: str, store: Store):
    return operations.get_result(project_id, file_id, store)


@router.get('/analysis-runs')
def history(project_id: str, file_id: str, store: Store):
    from app.domain.analysis_history import confirmed_history
    return confirmed_history(store,project_id,file_id)

@router.post('/analysis-runs', response_model=TaskView, status_code=202)
def execute(project_id: str, file_id: str, request: RunRequest, store: Store, settings: Settings):
    from app.domain.statistics_execution.service import create
    return create(project_id, file_id, request, store)


@router.get('/analysis-runs/{run_id}')
def exact_result(project_id: str, file_id: str, run_id: str, store: Store):
    return store.analysis_result_by_id(project_id,file_id,run_id)
