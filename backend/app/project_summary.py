"""Read-only projections of persisted history; never reconcile cloud jobs."""
from typing import Annotated, Generic, Literal, TypeVar
from urllib.parse import quote

from pydantic import BaseModel, Field

from .storage import StorageError


class SourceSummary(BaseModel):
    id: str
    file_id: str
    filename: str
    analysis_run_id: str
    setup_revision: int
    current_revision: int | None
    engine_version: str
    recorded_at: str
    figure_id: str | None
    explanation_id: str | None


class TaskSummary(SourceSummary):
    kind: Literal['statistics', 'boxplot', 'explanation', 'report']
    status: Literal['submitting', 'running', 'completed', 'failed', 'uncertain', 'unknown']


class ArtifactSummary(SourceSummary):
    kind: Literal['figure', 'report']
    download_filename: str
    size_bytes: int
    sha256: str
    download_url: str


Item = TypeVar('Item')


class SummaryPage(BaseModel, Generic[Item]):
    items: list[Item]
    total: int
    page: int
    page_size: int


# Future modules extend these contracts only when their persistence exists.
EmptyHistory = Annotated[list[None], Field(max_length=0)]


class UnavailableModule(BaseModel):
    state: Literal['not_available'] = 'not_available'
    tasks: EmptyHistory = Field(default_factory=list)


class WritingSummary(UnavailableModule):
    current_manuscript: None = None
    versions: EmptyHistory = Field(default_factory=list)


class RevisionSummary(UnavailableModule):
    current_round: None = None
    rounds: EmptyHistory = Field(default_factory=list)
    opinions: EmptyHistory = Field(default_factory=list)
    pending_materials: EmptyHistory = Field(default_factory=list)


class SciSummary(UnavailableModule):
    target_journal: None = None
    recommendations: EmptyHistory = Field(default_factory=list)
    submission_progress: None = None


class ThesisSummary(UnavailableModule):
    school: None = None
    degree: None = None
    template: None = None
    review_progress: None = None


class FutureSummary(BaseModel):
    writing: WritingSummary = Field(default_factory=WritingSummary)
    revision: RevisionSummary = Field(default_factory=RevisionSummary)
    sci: SciSummary | None
    thesis: ThesisSummary | None


class ProjectSummary(BaseModel):
    project_id: str
    project_type: Literal['sci', 'thesis']
    tasks: SummaryPage[TaskSummary]
    artifacts: SummaryPage[ArtifactSummary]
    future: FutureSummary


RUNS = '''WITH runs AS (
    SELECT r.*, f.filename, s.revision AS current_revision
    FROM analysis_runs r JOIN files f ON f.id=r.file_id
    LEFT JOIN analysis_setups s ON s.file_id=f.id
    WHERE f.project_id=%s
), events AS ('''

TASKS = '''
    SELECT id, 'statistics' AS kind, 'completed' AS status, id AS analysis_run_id,
           engine_version, completed_at AS recorded_at, NULL::text AS figure_id,
           NULL::text AS explanation_id FROM runs
    UNION ALL
    SELECT j.id, 'boxplot', j.job_json::jsonb ->> 'status', j.analysis_run_id,
           j.renderer_version, j.created_at, NULL::text, NULL::text
    FROM figure_jobs j JOIN runs r ON r.id=j.analysis_run_id
    UNION ALL
    SELECT j.id, 'explanation', j.job_json::jsonb ->> 'status', j.analysis_run_id,
           j.engine_version, j.created_at, j.figure_id, NULL::text
    FROM explanation_jobs j JOIN runs r ON r.id=j.analysis_run_id
    JOIN figures f ON f.id=j.figure_id AND f.analysis_run_id=r.id
    UNION ALL
    SELECT p.id, 'report', 'completed', p.analysis_run_id,
           p.renderer_version, p.report_json::jsonb ->> 'created_at', e.figure_id, p.explanation_id
    FROM reports p JOIN runs r ON r.id=p.analysis_run_id
    JOIN explanations e ON e.id=p.explanation_id AND e.analysis_run_id=r.id
    JOIN figures f ON f.id=e.figure_id AND f.analysis_run_id=r.id
'''

ARTIFACTS = '''
    SELECT f.id, 'figure' AS kind, f.analysis_run_id, f.renderer_version AS engine_version,
           f.figure_json::jsonb ->> 'created_at' AS recorded_at, f.id AS figure_id,
           NULL::text AS explanation_id, 'boxplot-' || f.id || '.png' AS download_filename,
           (f.figure_json::jsonb ->> 'size_bytes')::bigint AS size_bytes,
           f.figure_json::jsonb ->> 'sha256' AS sha256
    FROM figures f JOIN runs r ON r.id=f.analysis_run_id
    UNION ALL
    SELECT p.id, 'report', p.analysis_run_id, p.renderer_version,
           p.report_json::jsonb ->> 'created_at', e.figure_id, p.explanation_id,
           p.report_json::jsonb ->> 'filename', (p.report_json::jsonb ->> 'size_bytes')::bigint,
           p.report_json::jsonb ->> 'sha256'
    FROM reports p JOIN runs r ON r.id=p.analysis_run_id
    JOIN explanations e ON e.id=p.explanation_id AND e.analysis_run_id=r.id
    JOIN figures f ON f.id=e.figure_id AND f.analysis_run_id=r.id
'''


def _page(db, project_id, events, page, page_size):
    cte = RUNS + events + ') '
    total = db.execute(cte + 'SELECT count(*) AS total FROM events', (project_id,)).fetchone()['total']
    rows = db.execute(cte + '''SELECT e.*, r.file_id, r.filename, r.setup_revision, r.current_revision
        FROM events e JOIN runs r ON r.id=e.analysis_run_id
        ORDER BY e.recorded_at::timestamptz DESC, e.kind, e.id LIMIT %s OFFSET %s''',
                      (project_id, page_size, (page - 1) * page_size))
    return {'items': [dict(row) for row in rows], 'total': total, 'page': page, 'page_size': page_size}


def read_project_summary(store, project_id, *, task_page=1, artifact_page=1, page_size=10):
    if (any(type(page) is not int or not 1 <= page <= 1_000_000 for page in (task_page, artifact_page))
            or type(page_size) is not int or not 1 <= page_size <= 50):
        raise StorageError('project_summary_query_invalid', '摘要页码须为1–1000000，每页须为1–50项。', 422)
    scope = ' AND owner_id=%s' if store.owner_id is not None else ''
    parameters = (project_id, store.owner_id) if store.owner_id is not None else (project_id,)
    # Owner check, counts and lists observe one read-only REPEATABLE READ snapshot.
    with store.connection() as db:
        project = db.execute('SELECT project_type FROM projects WHERE id=%s' + scope, parameters).fetchone()
        if project is None:
            raise StorageError('project_not_found', '项目不存在，请刷新项目列表。', 404)
        tasks = _page(db, project_id, TASKS, task_page, page_size)
        artifacts = _page(db, project_id, ARTIFACTS, artifact_page, page_size)
    for task in tasks['items']:
        if task['status'] not in ('submitting', 'running', 'completed', 'failed', 'uncertain'):
            task['status'] = 'unknown'
    for artifact in artifacts['items']:
        path = '/api/v1/projects/{}/files/{}/analysis-runs/{}'.format(
            *(quote(value, safe='') for value in (project_id, artifact['file_id'], artifact['analysis_run_id'])))
        resource_id = quote(artifact['id'], safe='')
        artifact['download_url'] = (f'{path}/figures/{resource_id}/download' if artifact['kind'] == 'figure'
                                    else f'{path}/report/{resource_id}/download')
    kind = project['project_type']
    return ProjectSummary(project_id=project_id, project_type=kind, tasks=tasks, artifacts=artifacts,
                          future=FutureSummary(sci=SciSummary() if kind == 'sci' else None,
                                               thesis=ThesisSummary() if kind == 'thesis' else None))
