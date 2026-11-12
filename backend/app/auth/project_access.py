"""A request can borrow one customer project scope while retaining its actor."""

from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime

from fastapi import Request
from starlette.concurrency import run_in_threadpool

from app.core.exceptions import StorageError


PROJECT_PATH = '/api/v1/projects/{project_id}'
FILE = '/files/{file_id}'
RUN = FILE + '/analysis-runs/{run_id}'
DELIVERY = '/deliveries/{delivery_id}'
SNAPSHOT = DELIVERY + '/snapshots/{identifier}'
TASK = '/api/v1/tasks/{task_id}'

# Only these registered paths receive the project owner's storage scope.
PROJECT_OPERATIONS = frozenset((method, PROJECT_PATH + path) for method, paths in {
    'GET': (
        '', '/language', '/workflow-state', '/analyst-workspace', '/tasks',
        '/files', FILE + '/details', FILE + '/preview', FILE + '/download',
        '/file-batches', '/file-batches/{batch_id}',
        '/bio-upload-batches', '/bio-upload-batches/{batch_id}',
        '/research-intake', '/requirements', '/requirements/{version_id}',
        '/research-designs', '/research-designs/requests/{key}', '/research-designs/{version_id}',
        FILE + '/document-versions', FILE + '/document-versions/{parse_id}',
        FILE + '/document-versions/{parse_id}/blocks', FILE + '/document-versions/{parse_id}/pages',
        FILE + '/document-versions/{parse_id}/download', FILE + '/document-versions/{parse_id}/images/{image_id}',
        FILE + '/document-versions/{version_id}/evidence', FILE + '/dataset-versions/{version_id}/evidence',
        FILE + '/prepared-dataset-versions/{version_id}/evidence',
        FILE + '/ocr-reviews', FILE + '/ocr-review-versions',
        FILE + '/ocr-review-versions/{review_id}', FILE + '/ocr-review-versions/{review_id}/download',
        FILE + '/structure-versions', FILE + '/structure-versions/{structure_id}',
        FILE + '/lifecycle/assessment', FILE + '/lifecycle/tasks',
        FILE + '/dataset-versions/{dataset_id}/rows', FILE + '/dataset-versions/{dataset_id}/download',
        FILE + '/dataset-versions/{dataset_id}/profile', FILE + '/dataset-versions/{dataset_id}/profile/issues',
        FILE + '/dataset-versions/{dataset_id}/preparation-defaults',
        FILE + '/prepared-dataset-versions', FILE + '/prepared-dataset-versions/{dataset_id}',
        FILE + '/prepared-dataset-versions/{dataset_id}/rows', FILE + '/prepared-dataset-versions/{dataset_id}/download',
        FILE + '/prepared-dataset-versions/{dataset_id}/quality-defaults',
        FILE + '/prepared-dataset-versions/{dataset_id}/filter-defaults',
        FILE + '/prepared-dataset-versions/{dataset_id}/impacts',
        FILE + '/prepared-dataset-versions/{dataset_id}/impacts/download',
        FILE + '/analysis-plans', FILE + '/analysis-plans/{plan_id}', FILE + '/analysis-profile',
        FILE + '/analysis-setup', FILE + '/analysis-result', FILE + '/analysis-runs',
        FILE + '/comparison-group-options', RUN, RUN + '/boxplot/disclosure', RUN + '/boxplot', RUN + '/boxplot/image',
        RUN + '/figures/{figure_id}/download', RUN + '/explanation/disclosure', RUN + '/explanation',
        RUN + '/report', RUN + '/report/{report_id}/download', RUN + '/figure-workbench',
        RUN + '/figure-workbench/figures/{figure_id}/png', RUN + '/figure-workbench/figures/{figure_id}/package',
        '/bio-imports/{import_id}', '/bio-datasets', '/bio-datasets/{dataset_id}/versions/{version_id}',
        '/bio-datasets/{dataset_id}/versions/{version_id}/manifest',
        '/bio-datasets/{dataset_id}/versions/{version_id}/members/{member_id}',
        '/bio-datasets/{dataset_id}/versions/{version_id}/members/{member_id}/download',
        '/bio-datasets/{dataset_id}/versions/{version_id}/matrix-preview',
        '/bio-datasets/{dataset_id}/versions/{version_id}/coordinate-preview',
        '/bio-analysis-capabilities', '/bio-observation-maps/{set_id}/versions/{version_id}',
        '/bio-analysis-setups/{setup_id}', '/bio-analysis-setups/{setup_id}/recipes/{version_id}',
        '/bio-analysis-runs', '/bio-analysis-runs/{run_id}', '/bio-analysis-runs/{run_id}/qc-members/{member_id}/download',
        '/bio-processed-datasets/{version_id}', '/bio-processed-datasets/{version_id}/report.docx',
        '/bio-processed-datasets/{version_id}/tables/{key}', '/bio-processed-datasets/{version_id}/coordinates',
        '/bio-processed-datasets/{version_id}/matrix-preview', '/bio-processed-datasets/{version_id}/robustness',
        '/bio-processed-datasets/{version_id}/repeat-context', '/bio-processed-datasets/{version_id}/members/{member_id}/download',
        '/bio-annotation-sets/{set_id}/versions/{version_id}', '/bio-processed-datasets/{version_id}/annotations',
        '/bio-annotation-sets/{set_id}/versions/{version_id}/members/{member_id}/download',
        '/bio-single-cell-references', '/bio-single-cell-annotation-runs/{run_id}',
        '/bio-processed-datasets/{version_id}/annotation-runs', '/bio-figures/{figure_id}',
        '/bio-figures/{figure_id}/members/{member_id}/download', '/bio-requests/{request_key}',
        '/bio-insights/capabilities', '/bio-insights/sources', '/bio-insights/sources/{source_kind}/{source_id}/observations',
        '/bio-resource-files/requests/{request_key}', '/bio-insight-plans', '/bio-insight-plans/{plan_id}/versions/{version_id}',
        '/bio-insight-runs', '/bio-insight-runs/{run_id}', '/bio-insight-requests/{request_key}',
        '/bio-resources', '/bio-resources/{version_id}', '/bio-resources/{version_id}/members/{member_id}/download',
        '/bio-resources/{version_id}/reproducibility-package', '/bio-resources/{version_id}/impact',
        '/bio-insight-results/{version_id}', '/bio-insight-results/{version_id}/figures',
        '/bio-insight-results/{version_id}/report.docx', '/bio-insight-results/{version_id}/members/{member_id}/download',
        '/bio-insight-results/{version_id}/tables/{key}', '/bio-insight-results/{version_id}/bulk-comparisons',
        '/bio-insight-results/{version_id}/reproducibility-package', '/bio-insight-results/{version_id}/impact',
        '/bulk-workflow', '/bulk-workflow/delivery/prepared/{kind}/{artifact_id}',
        '/research-results/sources', '/research-requests/{request_key}',
        '/research-findings', '/research-findings/{set_id}/versions/{version_id}',
        '/research-figures', '/research-figures/{version_id}', '/research-figures/{version_id}/members/{member_id}/download',
        '/research-reports', '/research-reports/{version_id}', '/research-reports/{version_id}/members/{member_id}/download',
        '/report-collections', '/report-collections/candidates', '/report-collections/{collection_id}',
        '/report-collections/{collection_id}/versions/{version_id}/preview',
        '/report-collections/{collection_id}/reports/{report_id}/download',
        '/deliveries', DELIVERY + '/candidates', DELIVERY + '/snapshots', DELIVERY + '/snapshots/requests/{key}',
        SNAPSHOT, SNAPSHOT + '/package', SNAPSHOT + '/download', SNAPSHOT + '/members/{member_id}/download',
    ),
    'POST': (
        '/analyst-workspace/publish', '/analyst-workspace/delivery-artifacts',
        '/files', '/file-batches', '/file-batches/{batch_id}/items/{item_id}',
        '/bio-upload-batches', '/bio-upload-batches/{batch_id}/items/{item_id}',
        '/research-designs', '/design-table-preview', '/design-table-previews',
        FILE + '/document-versions', FILE + '/document-versions/ocr', FILE + '/ocr-reviews',
        FILE + '/structure-versions', FILE + '/dataset-preparations', FILE + '/dataset-quality-preparations',
        FILE + '/dataset-population-filters', FILE + '/analysis-check', FILE + '/analysis-plans', '/analysis-plans',
        FILE + '/analysis-recommendations', FILE + '/analysis-recommendations/preview', FILE + '/analysis-runs',
        RUN + '/boxplot', RUN + '/explanation', RUN + '/report', RUN + '/figure-workbench/configurations',
        RUN + '/figure-workbench/versions/{version_id}/check', RUN + '/figure-workbench/versions/{version_id}/confirm',
        RUN + '/figure-workbench/versions/{version_id}/external-preview', RUN + '/figure-workbench/versions/{version_id}/generate',
        RUN + '/figure-workbench/figures/{figure_id}/explanation-preview', RUN + '/figure-workbench/figures/{figure_id}/explanations',
        RUN + '/figure-workbench/versions/{version_id}/reuse-explanation',
        '/bio-imports', '/bio-imports/{import_id}/confirm', '/bio-observation-map-table-previews',
        '/bio-observation-maps', '/bio-observation-maps/{set_id}/versions',
        '/bio-analysis-setups', '/bio-analysis-setups/{setup_id}/recipes', '/bio-analysis-runs',
        '/single-cell-analysis-runs', '/bio-single-cell-subsets', '/bio-analysis-runs/{run_id}/confirm',
        '/bio-annotation-sets', '/bio-annotation-sets/{set_id}/versions', '/bio-single-cell-annotation-runs',
        '/bio-figures', '/bio-figures/{root_id}/versions',
        '/bio-resource-files', '/bio-insight-plans/preview', '/bio-insight-plans', '/bio-insight-plans/{plan_id}/versions',
        '/bio-insight-runs', '/bio-resources/preview', '/bio-resources', '/bio-resources/{root_id}/versions',
        '/bulk-workflow/sensitivity', '/bulk-workflow/delivery/preview', '/bulk-workflow/delivery/report.docx',
        '/bulk-workflow/delivery/reproducibility-package', '/bulk-workflow/delivery/prepare/{kind}',
        '/research-results/preview', '/research-results/source-changes', '/research-findings', '/research-findings/{set_id}/versions',
        '/research-figures', '/research-figures/{root_id}/versions', '/research-reports', '/research-reports/{root_id}/versions',
        '/report-collections', '/report-collections/{collection_id}/versions',
        '/report-collections/{collection_id}/versions/{version_id}/exports',
        DELIVERY + '/snapshots/preview', DELIVERY + '/snapshots', SNAPSHOT + '/package',
    ),
    'PUT': (FILE + '/purposes', FILE + '/analysis-setup'),
    'PATCH': ('/analyst-workspace/progress',),
}.items() for path in paths)

TASK_OPERATIONS = frozenset((method, TASK + path) for method, paths in {
    'GET': (
        '', '/events', '/workspace', '/progress', '/analysis-plan', '/analysis-recommendation', '/ocr-review',
        '/ocr-review/preview/download', '/dataset-preparation', '/dataset-preparation/impacts',
        '/dataset-preparation/impacts/download', '/dataset-preparation/preview/download',
    ),
    'POST': (
        '/retry', '/resume', '/cancel', '/analysis-plan/decisions', '/analysis-plan/continuations', '/analysis-plan/source-decisions',
        '/ocr-review/decision', '/dataset-preparation/decision',
    ),
}.items() for path in paths)

ASSIGNED_TASK_TYPES = (
    'boxplot', 'explanation', 'word_report', 'parse_file', 'extract_dataset', 'prepare_dataset', 'review_ocr',
    'analysis_plan', 'analysis_recommendation', 'figure_projection', 'figure_workbench', 'figure_explanation',
    'collection_word_report', 'statistics_compute', 'bio_import', 'bio_analysis', 'bio_annotation', 'bio_figure',
    'research_figure', 'research_report', 'delivery_package', 'bio_resource_import', 'bio_comparison',
    'bio_result_import', 'bio_enrichment', 'bio_candidate', 'bio_insight_figure', 'bio_feature_extract', 'bio_integration',
)

ACTIVE_ASSIGNMENTS_FROM = '''FROM project_assignments a
    JOIN projects p ON p.id=a.project_id AND p.owner_id=a.owner_id
    JOIN users customer ON customer.id=a.owner_id
    JOIN users analyst ON analyst.id=a.analyst_id
    WHERE customer.role='customer' AND customer.active AND customer.review_status='approved'
      AND analyst.role='analyst' AND analyst.active AND analyst.review_status='approved' '''


@dataclass(frozen=True)
class ProjectAssignment:
    project_id: str
    owner_id: str
    analyst_id: str
    revision: int
    updated_at: datetime | None = field(default=None, compare=False)

    def require_project(self, project_id: str) -> None:
        if project_id != self.project_id:
            raise StorageError('project_not_found', '项目不存在，请刷新项目列表。', 404)


_assignment = ContextVar[ProjectAssignment | None]('project_assignment', default=None)


def current_assignment() -> ProjectAssignment | None:
    return _assignment.get()


def assignment_for_owner(owner_id: str | None) -> ProjectAssignment | None:
    scope = current_assignment()
    return scope if scope is not None and scope.owner_id == owner_id else None


def read_current_assignment(db, project_id: str, analyst_id: str | None = None, *, lock=False) -> ProjectAssignment | None:
    query = 'SELECT a.project_id,a.owner_id,a.analyst_id,a.revision,a.updated_at ' + ACTIVE_ASSIGNMENTS_FROM + ' AND a.project_id=%s'
    args = (project_id,)
    if analyst_id is not None:
        query += ' AND a.analyst_id=%s'
        args += (analyst_id,)
    if lock:
        query += ' FOR SHARE OF a,p,customer,analyst'
    row = db.execute(query, args).fetchone()
    return ProjectAssignment(**row) if row else None


def require_current_assignment(db, scope: ProjectAssignment, *, lock=False) -> None:
    if read_current_assignment(db, scope.project_id, scope.analyst_id, lock=lock) != scope:
        raise StorageError('project_assignment_stale', '项目分配已变化，请刷新分配给我的项目。', 409)


def _lookup_assignment(analyst_id, project_id, task_id):
    from app.adapters.storage import _storage_connection

    with _storage_connection() as db:
        if task_id is not None:
            row = db.execute('''SELECT t.project_id FROM tasks t
                JOIN projects p ON p.id=t.project_id AND p.owner_id=t.user_id
                WHERE t.id=%s AND t.task_type=ANY(%s)''', (task_id, list(ASSIGNED_TASK_TYPES))).fetchone()
            if row is None:
                return None
            project_id = row['project_id']
        return read_current_assignment(db, project_id, analyst_id)


async def bind_project_assignment(request: Request):
    user = getattr(request.state, 'user', None)
    scope = None
    if user and user['role'] == 'analyst':
        operation = (request.method, request.scope['route'].path_format)
        if operation in PROJECT_OPERATIONS:
            scope = await run_in_threadpool(_lookup_assignment, user['id'], request.path_params['project_id'], None)
        elif operation in TASK_OPERATIONS:
            scope = await run_in_threadpool(_lookup_assignment, user['id'], None, request.path_params['task_id'])
    request.state.project_assignment = scope
    token = _assignment.set(scope)
    try:
        yield
    finally:
        _assignment.reset(token)
