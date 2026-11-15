"""Exact statistics selections and access to their published report members."""
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Response

from app.adapters.bio_analysis_store import scoped_object
from app.adapters.research_results_store import invalid
from app.api.bio_datasets import Key, Page, Store
from app.api.bulk_workflow import stream_attachment
from app.domain.research_results.reports import ResearchReportService
from app.domain.research_results.sources import ResearchSourceReader
from app.domain.statistics_reader_reports.contracts import StatisticsReportPrepareRequest
from app.domain.statistics_reader_reports.service import StatisticsReaderReportService, KIND, VERSIONS

router = APIRouter(prefix='/api/v1/projects/{project_id}/statistics-reader-reports', tags=['统计报告'])

MemberRole = Literal['docx', 'xlsx', 'zip']
MEDIA = {'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
         'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'zip': 'application/zip'}
PAGE_SIZE = 20
BOUND_REPORT = """FROM research_report_versions r WHERE EXISTS (SELECT 1 FROM statistics_report_context_requests q
    WHERE q.context_id=%s AND q.finding_version_id=r.finding_version_id
    AND q.project_id=r.project_id AND q.user_id=r.user_id) AND r.project_id=%s AND r.user_id=%s"""


@router.post('/prepare', status_code=201)
def prepare(project_id: str, request: StatisticsReportPrepareRequest, response: Response, store: Store, idempotency_key: Key):
    value, response.status_code = StatisticsReaderReportService(store).prepare(project_id, request, idempotency_key)
    return value


@router.get('/requests/{key}')
def receipt(project_id: str, key: str, store: Store):
    return StatisticsReaderReportService(store).request_receipt(project_id, key)


@router.get('/{context_id}')
def context(project_id: str, context_id: str, store: Store):
    return StatisticsReaderReportService(store).get(project_id, context_id)


def report_members(db, service, project, context, report):
    snapshot = service.verify_content(report)
    sources = snapshot['finding']['content']['sources']
    if (len(sources) != 1 or sources[0]['source_kind'] != KIND or sources[0]['source_id'] != context['id']
            or sources[0]['sha256'] != context['content_sha256'] or snapshot['language'] != report['language']):
        raise invalid()
    task = service.store.require_task(db, report['task_id'])
    from app.domain.statistics_reader_reports.legacy_exports import is_reader_export, StatisticsLegacyReportService
    legacy = is_reader_export(task)
    if legacy:
        binding=StatisticsLegacyReportService(service.assets).association(db,task)
        if (binding['project_id']!=project or binding['context_id']!=context['id']
                or binding['report_version_id']!=report['id'] or binding['content_sha256']!=report['content_sha256']):
            raise invalid()
    elif (task['task_type'] != 'research_report' or task['input_snapshot']['report_version_id'] != report['id']
            or task['input_snapshot']['content_sha256'] != report['content_sha256']):
        raise invalid()
    members = []
    if task['status'] == 'succeeded':
        if not report['manifest_object_id'] or not legacy and task['result_research_report_version_id'] != report['id']:
            raise invalid()
        _, available = service.checked_members(db, project, report, read_member_bytes=False)
        members = [item for item in available if item['role'] in MEDIA and item['format'] == item['role']]
    return task, members


@router.get('/{context_id}/reports')
def reports(project_id: str, context_id: str, store: Store, page: Page = 1):
    service = ResearchReportService(store)
    with service.store.connection() as db:
        context = service.require(db, VERSIONS, project_id, context_id)
        args = (context_id, project_id, service.store.user_id)
        total = db.execute('SELECT count(*) AS n ' + BOUND_REPORT, args).fetchone()['n']
        rows = db.execute('SELECT r.* ' + BOUND_REPORT + ' ORDER BY r.created_at DESC,r.id LIMIT %s OFFSET %s',
                          (*args, PAGE_SIZE, (page - 1) * PAGE_SIZE)).fetchall()
        items = []
        for report in rows:
            task, members = report_members(db, service, project_id, context, report)
            base = f'/api/v1/projects/{project_id}/statistics-reader-reports/{context_id}/reports/{report["id"]}'
            for member in members:
                member['download_url'] = base + f"/members/{member['role']}/download"
            items.append(dict(id=report['id'], task_id=task['id'], task=service.store.public_task(task), members=members))
    return dict(items=items, total=total, page=page, page_size=PAGE_SIZE)


@router.get('/{context_id}/reports/{report_version_id}/members/{role}/download')
def member(project_id: str, context_id: str, report_version_id: str, role: MemberRole, store: Store):
    from app.adapters.research_objects import ResearchObjects

    service = ResearchReportService(store)
    with service.store.connection() as db:
        context = service.require(db, VERSIONS, project_id, context_id)
        report = db.execute('SELECT r.* ' + BOUND_REPORT + ' AND r.id=%s LIMIT 1',
                            (context_id, project_id, service.store.user_id, report_version_id)).fetchone()
        if report is None:
            raise invalid('research_source_not_found', 404)
        _, members = report_members(db, service, project_id, context, report)
        selected = [item for item in members if item['role'] == role]
        if len(selected) != 1:
            raise invalid('research_source_not_found', 404)
        saved = service.require(db, 'research_report_members', project_id, selected[0]['id'])
        obj = scoped_object(db, project_id, service.store.user_id, saved['storage_object_id'])
        ResearchSourceReader(store).read_source(project_id, dict(source_kind=KIND, source_id=context_id,
                                                                sha256=context['content_sha256']), db=db)
        filename = f"{saved['key']}.{role}"
        headers = {'Content-Disposition': "attachment; filename*=UTF-8''" + quote(filename, safe=''),
                   'ETag': '"' + obj['sha256'] + '"', 'Cache-Control': 'private, no-store',
                   'X-Content-Type-Options': 'nosniff'}
    return stream_attachment(ResearchObjects(store.directory).open_verified(obj), MEDIA[role], headers)
