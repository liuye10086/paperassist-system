from fastapi import APIRouter, Response
from app.api.dataset_preparation import Store, Key
from app.domain.review_rounds.science import ScienceService
from app.domain.review_rounds.science_contracts import TaskLinkRequest, StatisticsTaskRequest, AnalysisAdoptionRequest, ProjectionTaskRequest, PlotTaskRequest
from app.domain.review_rounds.science_contracts import FigureAdoptionRequest

router = APIRouter(prefix='/api/v1/projects/{project_id}/reviews', tags=['返修科学任务'])


@router.post('/rounds/{identity}/figure-adoptions', status_code=201)
def figure_adoption(project_id: str, identity: str, request: FigureAdoptionRequest, response: Response, store: Store, idempotency_key: Key):
    result, response.status_code = ScienceService(store).create_figure_adoption(project_id, identity, request, idempotency_key)
    return result


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


@router.post('/rounds/{identity}/projection-tasks', status_code=202)
def projection_task(project_id: str, identity: str, request: ProjectionTaskRequest, response: Response, store: Store, idempotency_key: Key):
    result, response.status_code = ScienceService(store).create_figure_task(project_id, identity, request, idempotency_key)
    return result


@router.post('/rounds/{identity}/plot-tasks', status_code=202)
def plot_task(project_id: str, identity: str, request: PlotTaskRequest, response: Response, store: Store, idempotency_key: Key):
    result, response.status_code = ScienceService(store).create_figure_task(project_id, identity, request, idempotency_key, plot=True)
    return result
