"""Prepare an exact native selection and reuse the standard report workflow."""
from contextlib import ExitStack
import tempfile
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Query, Response

from app.adapters.research_results_store import invalid
from app.api.bio_datasets import Key, Page, Store
from app.api.bulk_workflow import (WORD_MEDIA_TYPE, artifact_response, checked_facts, open_artifact,
    resolve_delivery, sensitivity_for, stream_attachment)

from app.domain.bio_insights.bulk_delivery_archive import BulkDeliveryArchive
from app.domain.bio_insights.bulk_delivery_cache import cache_for, heavy_slot
from app.domain.bio_insights.bulk_delivery_contracts import BulkDownloadRequest
from app.domain.bio_insights.bulk_workflow import BulkWorkflowService
from app.domain.bioinformatics.contracts import digest
from app.domain.bio_reader_reports import BioReaderReportService
from app.domain.bio_reader_reports.contracts import BioReportPrepareRequest
from app.domain.bio_reader_reports.exports import BioReaderReportExports, MemberRole


router = APIRouter(prefix='/api/v1/projects/{project_id}/bio-reader-reports', tags=['生信报告'])
ReportVersion = Annotated[str | None, Query(min_length=1, max_length=64)]
MEMBER_MEDIA = dict(docx=WORD_MEDIA_TYPE, xlsx='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    zip='application/zip')


def report_url(project, context, report):
    return f'/api/v1/projects/{project}/bio-reader-reports/{context}/reports/{report}'


@router.post('/prepare', status_code=201)
def prepare(project_id: str, request: BioReportPrepareRequest, response: Response, store: Store, idempotency_key: Key):
    result, response.status_code = BioReaderReportService(store).prepare(project_id, request, idempotency_key)
    return result


@router.get('/requests/{key}')
def receipt(project_id: str, key: str, store: Store):
    return BioReaderReportService(store).request_receipt(project_id, key)


@router.get('/{context_id}')
def context(project_id: str, context_id: str, store: Store):
    return BioReaderReportService(store).get(project_id, context_id)


@router.get('/{context_id}/reports')
def reports(project_id: str, context_id: str, store: Store, page: Page = 1):
    listing = BioReaderReportExports(store).list(project_id, context_id, page)
    for item in listing['items']:
        base = report_url(project_id, context_id, item['id'])
        for member in item['members']:
            member['download_url'] = base + f"/members/{member['role']}/download"
    return listing


def fixed_member(store, project, report, role, **binding):
    service = BioReaderReportExports(store)
    _, _, members = service.resolve(project, report, (role,), **binding)
    member = members[role]['metadata']
    filename = member['key'] + '.' + member['format']
    headers = {'Content-Disposition': "attachment; filename*=UTF-8''" + quote(filename, safe=''),
               'ETag': '"' + member['sha256'] + '"', 'Cache-Control': 'private, no-store',
               'X-Content-Type-Options': 'nosniff'}
    return stream_attachment(service.objects.open_verified(members[role]['object']), MEMBER_MEDIA[role], headers)


@router.get('/{context_id}/reports/{report_version_id}/members/{role}/download')
def member(project_id: str, context_id: str, report_version_id: str, role: MemberRole, store: Store):
    return fixed_member(store, project_id, report_version_id, role, context_id=context_id)


def fixed_legacy_word(store, project, report, *, selection, language):
    if language is None:
        raise invalid('research_source_conflict', 422)
    return fixed_member(store, project, report, 'docx', selection=selection, language=language)


def _bulk_archive(project, store, context, report, *, artifact_id=None):
    """The caller holds the existing Bulk heavy slot through opening the file."""
    files = BioReaderReportExports(store)
    row, content, members = files.resolve(project, report, ('docx', 'xlsx'), context_id=context)
    supporting = content['supporting_sources']
    if (content['selection']['kind'] != 'bulk' or len(supporting) != 1
            or supporting[0]['kind'] != 'bulk' or supporting[0]['delivery'] != content['selection']['delivery']):
        raise invalid('research_source_unsupported', 422)
    fixed = supporting[0]
    request = BulkDownloadRequest.model_validate(fixed['delivery'])
    if request.language != ('en' if content['language'] == 'en' else 'zh'):
        raise invalid()
    identity = dict(context_id=context, context_sha256=row['content_sha256'], report_version_id=report,
                    language=content['language'], members={
                        role: {key: value['metadata'][key] for key in ('id', 'sha256', 'size_bytes')}
                        for role, value in members.items()})
    _, current = resolve_delivery(project, store, request)
    facts = checked_facts(request, current)
    if facts != fixed['facts']:
        raise invalid()
    archive = BulkDeliveryArchive(store)

    def current_restrictions():
        with archive.store.connection() as db:
            return archive.restricted_material_shas(db, project, facts['evidence'])

    restricted = current_restrictions()
    key = digest(['bulk-fixed-report-v1', identity, request.facts_digest, *restricted])
    if artifact_id is not None and artifact_id != key:
        raise invalid('bio_insight_source_incomplete', 410)

    def verify_restrictions():
        if current_restrictions() != restricted:
            raise invalid('bio_insight_source_incomplete', 410)

    cache = cache_for(store, project, 'reader-archive')
    with ExitStack() as opened:
        word, workbook = [opened.enter_context(files.objects.open_verified(members[role]['object']))
                          for role in ('docx', 'xlsx')]
        if artifact_id is not None:
            entry = cache.read(key)
            if entry is None:
                raise invalid('bio_insight_source_incomplete', 410)
            verify_restrictions()
            return entry, open_artifact(entry)

        def build(folder):
            with tempfile.TemporaryFile(mode='w+t', encoding='utf-8', newline='') as changes:
                change_table = None
                if request.sensitivity:
                    result = sensitivity_for(BulkWorkflowService(store), project, request.sensitivity,
                                             page_size=20, change_stream=changes)
                    if {k: v for k, v in result.items() if k not in ('page', 'page_size')} != facts['sensitivity']:
                        raise invalid()
                    changes.flush()
                    changes.seek(0)
                    change_table = changes.buffer
                package = archive.export_delivery(project, facts, word, workbook=workbook, report_identity=identity,
                    expected_restrictions=restricted, change_table=change_table, destination=folder / 'payload')
                package['file'].close()
            return dict(facts_digest=request.facts_digest, manifest_sha256=package['manifest_sha256'],
                        analysis_inputs_self_contained=package['analysis_inputs_self_contained'])

        entry = cache.obtain(key, build)
        verify_restrictions()
        return key, entry


@router.post('/{context_id}/reports/{report_version_id}/bulk-reproduction/prepare')
def prepare_bulk(project_id: str, context_id: str, report_version_id: str, store: Store):
    with heavy_slot(store, project_id):
        key, entry = _bulk_archive(project_id, store, context_id, report_version_id)
        return dict(artifact_id=key, facts_digest=entry['metadata']['facts_digest'],
                    download_url=report_url(project_id, context_id, report_version_id) + f'/bulk-reproduction/{key}')


@router.get('/{context_id}/reports/{report_version_id}/bulk-reproduction/{artifact_id}')
def download_bulk(project_id: str, context_id: str, report_version_id: str, artifact_id: str, store: Store):
    with heavy_slot(store, project_id):
        entry, handle = _bulk_archive(project_id, store, context_id, report_version_id, artifact_id=artifact_id)
        try:
            return artifact_response(entry, 'archive', handle=handle, filename='Bulk RNA-seq 完整分析复现资料.zip')
        except BaseException:
            handle.close()
            raise
