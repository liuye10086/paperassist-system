"""Read-only projections of persisted history; never reconcile cloud jobs."""
from typing import Annotated, Generic, Literal, TypeVar
from urllib.parse import quote

from pydantic import BaseModel, Field

from app.core.exceptions import StorageError


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
    status: Literal['queued', 'submitting', 'running', 'waiting_input', 'waiting_confirmation', 'completed', 'failed', 'uncertain', 'unknown']


class ArtifactSummary(SourceSummary):
    analysis_run_id: str | None
    setup_revision: int | None
    figure_kind: str | None = None
    figure_config_version_id: str | None = None
    collection_id: str | None = None
    collection_version_id: str | None = None
    collection_revision: int | None = None
    export_revision: int | None = None
    collection_title: str | None = None
    result_count: int | None = None
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


class WritingSummary(BaseModel):
    state: Literal['available','not_available'] = 'not_available'
    tasks: list[dict] = Field(default_factory=list)
    current_manuscript: dict | None = None
    versions: list[dict] = Field(default_factory=list)


class RevisionSummary(BaseModel):
    state: Literal['available','not_available'] = 'available'
    tasks: list[dict] = Field(default_factory=list)
    current_round: dict | None = None
    rounds: list[dict] = Field(default_factory=list)
    opinions: list[dict] = Field(default_factory=list)
    pending_materials: list[dict] = Field(default_factory=list)
    actual_revisions: list[dict] = Field(default_factory=list)
    documents: list[dict] = Field(default_factory=list)


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
    project_type: Literal['sci', 'thesis', 'research']
    tasks: SummaryPage[TaskSummary]
    artifacts: SummaryPage[ArtifactSummary]
    future: FutureSummary
    layout_exports: list[dict] = Field(default_factory=list)
    thesis_profile: dict | None = None
    journal: dict | None = None


RUNS = '''WITH runs AS (
    SELECT r.*, f.filename, f.project_id, p.owner_id, s.revision AS current_revision
    FROM analysis_runs r JOIN files f ON f.id=r.file_id
    JOIN projects p ON p.id=f.project_id
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
    WHERE NOT EXISTS (SELECT 1 FROM tasks t WHERE t.result_report_id=p.id
        AND t.task_type='word_report' AND t.project_id=r.project_id AND t.user_id=r.owner_id)
    UNION ALL
    SELECT t.id, 'report', CASE WHEN t.status='succeeded' THEN 'completed' ELSE t.status END,
           r.id, t.input_snapshot->'versions'->>'report', t.updated_at::text,
           t.input_snapshot->'figure'->>'id', t.input_snapshot->'explanation'->>'id'
    FROM tasks t JOIN runs r ON r.id=t.input_snapshot->'result'->>'id'
        AND r.project_id=t.project_id AND r.owner_id=t.user_id
    WHERE t.task_type='word_report'
    UNION ALL
    SELECT t.id, 'explanation', CASE WHEN t.status='succeeded' THEN 'completed' ELSE t.status END,
           r.id, t.input_snapshot->'versions'->>'explanation', t.updated_at::text,
           t.input_snapshot->'figure'->>'id', t.result_explanation_id
    FROM tasks t JOIN runs r ON r.id=t.input_snapshot->'result'->>'id'
        AND r.project_id=t.project_id AND r.owner_id=t.user_id
    WHERE t.task_type='explanation'
    UNION ALL
    SELECT t.id, 'boxplot', CASE WHEN t.status='succeeded' THEN 'completed' ELSE t.status END,
           r.id, t.input_snapshot->'versions'->>'figure', t.updated_at::text,
           t.result_figure_id, NULL::text
    FROM tasks t JOIN runs r ON r.id=t.input_snapshot->'result'->>'id'
        AND r.project_id=t.project_id AND r.owner_id=t.user_id
    WHERE t.task_type='boxplot'
'''

ARTIFACTS = '''
    SELECT f.id, 'figure' AS kind, f.analysis_run_id, f.renderer_version AS engine_version,
           f.figure_json::jsonb ->> 'created_at' AS recorded_at, f.id AS figure_id,
           NULL::text AS explanation_id, COALESCE(f.figure_json::jsonb ->> 'figure_kind', 'boxplot') || '-' || f.id || '.png' AS download_filename,
           (f.figure_json::jsonb ->> 'size_bytes')::bigint AS size_bytes,
           f.figure_json::jsonb ->> 'sha256' AS sha256,
           r.file_id, r.filename, r.setup_revision, r.current_revision,
           COALESCE(f.figure_json::jsonb ->> 'figure_kind', 'boxplot') AS figure_kind,
           f.figure_json::jsonb ->> 'figure_config_version_id' AS figure_config_version_id,
           NULL::text AS collection_id, NULL::text AS collection_version_id, NULL::integer AS collection_revision,
           NULL::integer AS export_revision, NULL::text AS collection_title, NULL::integer AS result_count
    FROM figures f JOIN runs r ON r.id=f.analysis_run_id
    UNION ALL
    SELECT p.id, 'report', p.analysis_run_id, p.renderer_version,
           p.report_json::jsonb ->> 'created_at', e.figure_id, p.explanation_id,
           p.report_json::jsonb ->> 'filename', (p.report_json::jsonb ->> 'size_bytes')::bigint,
           p.report_json::jsonb ->> 'sha256', r.file_id, r.filename, r.setup_revision, r.current_revision,
           NULL::text, NULL::text, NULL::text, NULL::text, NULL::integer, NULL::integer, NULL::text, NULL::integer
    FROM reports p JOIN runs r ON r.id=p.analysis_run_id
    JOIN explanations e ON e.id=p.explanation_id AND e.analysis_run_id=r.id
    JOIN figures f ON f.id=e.figure_id AND f.analysis_run_id=r.id
    UNION ALL
    SELECT p.id, 'report', NULL::text, p.renderer_version, p.created_at::text,
           NULL::text, NULL::text, p.report_json->>'filename', (p.report_json->>'size_bytes')::bigint, p.sha256,
           f.id, f.filename, NULL::integer, NULL::integer, NULL::text, NULL::text,
           c.id, v.id, v.revision, p.export_revision, v.content_json->>'title',
           (SELECT count(DISTINCT i.analysis_run_id)::integer FROM report_collection_items i WHERE i.version_id=v.id)
    FROM collection_reports p JOIN report_collection_versions v ON v.id=p.version_id
    JOIN report_collections c ON c.id=v.collection_id
    JOIN projects owner_project ON owner_project.id=c.project_id AND owner_project.owner_id=c.created_by
    JOIN files f ON f.id=v.source_json->>'file_id' AND f.project_id=c.project_id
    WHERE c.project_id=%s
'''


def _page(db, project_id, events, page, page_size, *, artifacts=False):
    cte = RUNS + events + ') '
    parameters = (project_id, project_id) if artifacts else (project_id,)
    total = db.execute(cte + 'SELECT count(*) AS total FROM events', parameters).fetchone()['total']
    selection = 'SELECT e.* FROM events e' if artifacts else '''SELECT e.*, r.file_id, r.filename, r.setup_revision, r.current_revision
        FROM events e JOIN runs r ON r.id=e.analysis_run_id'''
    rows = db.execute(cte + selection + '''
        ORDER BY e.recorded_at::timestamptz DESC, e.kind, e.id LIMIT %s OFFSET %s''',
                      (*parameters, page_size, (page - 1) * page_size))
    return {'items': [dict(row) for row in rows], 'total': total, 'page': page, 'page_size': page_size}


def read_project_summary(store, project_id, *, task_page=1, artifact_page=1, page_size=10):
    if (any(type(page) is not int or not 1 <= page <= 1_000_000 for page in (task_page, artifact_page))
            or type(page_size) is not int or not 1 <= page_size <= 50):
        raise StorageError('project_summary_query_invalid', '摘要页码须为1–1000000，每页须为1–50项。', 422)
    scope = ' AND owner_id=%s' if store.owner_id is not None else ''
    parameters = (project_id, store.owner_id) if store.owner_id is not None else (project_id,)
    # Owner check, counts and lists observe one read-only REPEATABLE READ snapshot.
    with store.connection() as db:
        project = db.execute('SELECT project_type,owner_id FROM projects WHERE id=%s' + scope, parameters).fetchone()
        if project is None:
            raise StorageError('project_not_found', '项目不存在，请刷新项目列表。', 404)
        tasks = _page(db, project_id, TASKS, task_page, page_size)
        artifacts = _page(db, project_id, ARTIFACTS, artifact_page, page_size, artifacts=True)
        from app.domain.layout_exports.service import LayoutExportService
        from app.domain.report_collections.service import scoped_store
        layout_service=LayoutExportService(scoped_store(project['owner_id'],store.db_config,store.directory))
        layout_rows=db.execute('SELECT * FROM layout_exports WHERE project_id=%s ORDER BY created_at DESC,id LIMIT 20',(project_id,)).fetchall()
        layouts=[layout_service.view(db,row) for row in layout_rows]
        thesis_profile=None
        if project['project_type']=='thesis':
            from app.domain.school_templates.service import SchoolTemplateService
            service=SchoolTemplateService(scoped_store(project['owner_id'],store.db_config,store.directory))
            thesis_profile=service.profile_view(db,project_id)
            bound=db.execute('SELECT v.name,v.version_label FROM school_template_confirmations c JOIN school_template_versions v ON v.id=c.template_version_id WHERE c.id=%s AND c.project_id=%s AND c.user_id=%s',(thesis_profile['bound_confirmation_id'],project_id,project['owner_id'])).fetchone()
            thesis_profile.update(template_name=bound['name'] if bound else None,template_version_label=bound['version_label'] if bound else None)
        journal=None
        if project['project_type']=='sci':
            from app.domain.journals.submissions import SubmissionService
            journal=SubmissionService(scoped_store(project['owner_id'],store.db_config,store.directory)).summary(db,project_id)
        from app.domain.review_rounds.service import ReviewRoundService
        review_service=ReviewRoundService(scoped_store(project['owner_id'],store.db_config,store.directory))
        review_rows=db.execute('SELECT * FROM review_rounds WHERE project_id=%s AND user_id=%s ORDER BY round_number DESC LIMIT 20',(project_id,project['owner_id'])).fetchall()
        review_views=[review_service.view(db,review_service.round_row(db,project_id,r['id'])) for r in review_rows]
        current=review_views[0] if review_views else None
        compact=lambda r:{k:r[k] for k in ('id','title','round_number','revision','synthetic','manuscript')}
        revision=RevisionSummary(tasks=[r['task'] for r in review_views],rounds=[compact(r) for r in review_views],current_round=compact(current) if current else None,opinions=[dict({k:i[k] for k in ('id','source_id','number','category','status','uncompleted_reason')},source_label=next(s['label'] for s in current['sources'] if s['id']==i['source_id'])) for i in current['items']] if current else [],pending_materials=[dict(item_id=i['id'],needs=i['needs']) for i in current['items'] if i['status']=='waiting_material'] if current else [])
        revision.actual_revisions=current.get('actual_revisions',[]) if current else []
        revision.documents=current.get('documents',[]) if current else []
        revision.tasks.extend(r['task'] for r in revision.actual_revisions)
        if project['project_type']=='research':
            revision=RevisionSummary(state='not_available')
        writing=WritingSummary()
        if project['project_type'] in ('sci','thesis'):
            latest=db.execute('SELECT id,title,current_revision FROM manuscripts WHERE project_id=%s ORDER BY updated_at DESC,id LIMIT 1',(project_id,)).fetchone()
            versions=db.execute('SELECT id,manuscript_id,revision FROM manuscript_versions WHERE project_id=%s ORDER BY created_at DESC,id LIMIT 20',(project_id,)).fetchall()
            writing=WritingSummary(state='available',current_manuscript=dict(latest) if latest else None,versions=[dict(v) for v in versions])
    for task in tasks['items']:
        if task['status'] not in ('queued', 'submitting', 'running', 'waiting_input', 'waiting_confirmation', 'completed', 'failed', 'uncertain'):
            task['status'] = 'unknown'
    for artifact in artifacts['items']:
        resource_id = quote(artifact['id'], safe='')
        if artifact['collection_id']:
            artifact['download_url'] = '/api/v1/projects/{}/report-collections/{}/reports/{}/download'.format(
                quote(project_id, safe=''), quote(artifact['collection_id'], safe=''), resource_id)
            continue
        path = '/api/v1/projects/{}/files/{}/analysis-runs/{}'.format(
            *(quote(value, safe='') for value in (project_id, artifact['file_id'], artifact['analysis_run_id'])))
        artifact['download_url'] = (f'{path}/figure-workbench/figures/{resource_id}/png'
                                    if artifact['kind'] == 'figure' and artifact['figure_config_version_id'] else
                                    f'{path}/figures/{resource_id}/download' if artifact['kind'] == 'figure'
                                    else f'{path}/report/{resource_id}/download')
    kind = project['project_type']
    return ProjectSummary(project_id=project_id, project_type=kind, tasks=tasks, artifacts=artifacts,layout_exports=layouts,thesis_profile=thesis_profile,journal=journal,
                          future=FutureSummary(writing=writing,revision=revision,sci=SciSummary() if kind == 'sci' else None,
                                               thesis=ThesisSummary() if kind == 'thesis' else None))
