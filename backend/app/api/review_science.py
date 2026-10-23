from fastapi import APIRouter, Response
from app.api.dataset_preparation import Store, Key
from app.domain.review_rounds.science import ScienceService
from app.domain.review_rounds.science_contracts import TaskLinkRequest, StatisticsTaskRequest, AnalysisAdoptionRequest

router = APIRouter(prefix='/api/v1/projects/{project_id}/reviews', tags=['返修科学任务'])


@router.get('/rounds/{identity}/science')
def science(project_id: str, identity: str, store: Store):
    return ScienceService(store).get_science(project_id, identity)


@router.post('/rounds/{identity}/task-links', status_code=201)
def task_link(project_id: str, identity: str, request: TaskLinkRequest, response: Response, store: Store, idempotency_key: Key):
    result, response.status_code = ScienceService(store).create_link(project_id, identity, request, idempotency_key)
    return result


@router.post('/rounds/{identity}/statistics-tasks', status_code=202)
def statistics(project_id: str, identity: str, request: StatisticsTaskRequest, response: Response, store: Store, idempotency_key: Key):
    result, response.status_code = ScienceService(store).create_statistics(project_id, identity, request, idempotency_key)
    return result


@router.post('/rounds/{identity}/analysis-adoptions', status_code=201)
def adoption(project_id: str, identity: str, request: AnalysisAdoptionRequest, response: Response, store: Store, idempotency_key: Key):
    result, response.status_code = ScienceService(store).create_adoption(project_id, identity, request, idempotency_key)
    return result
