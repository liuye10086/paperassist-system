"""Project-scoped Bulk workflow, sensitivity review and frozen delivery."""
import tempfile

from fastapi import APIRouter, Response
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from app.adapters.bio_insights_store import invalid
from app.api.bio_datasets import Store
from app.domain.bio_insights.bulk_delivery_contracts import BulkDeliveryRequest, BulkDownloadRequest, BulkSensitivityQuery

router = APIRouter(prefix='/api/v1/projects/{project_id}/bulk-workflow', tags=['Bulk RNA-seq 流程与交付'])
WORD_MEDIA_TYPE = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'


@router.get('')
def overview(project_id: str, store: Store):
    from app.domain.bio_insights.bulk_workflow import BulkWorkflowService

    return BulkWorkflowService(store).overview(project_id)


def sensitivity_for(service, project, request, **options):
    return service.sensitivity(project, request.baseline_version_id, request.scenario_version_id,
                               request.baseline_selection, request.scenario_selection, **options)


@router.post('/sensitivity')
def review_sensitivity(project_id: str, request: BulkSensitivityQuery, store: Store):
    from app.domain.bio_insights.bulk_workflow import BulkWorkflowService

    return sensitivity_for(BulkWorkflowService(store), project_id, request, page=request.page, page_size=request.page_size)


def resolve_delivery(project, store, request, *, change_stream=None):
    from app.domain.bio_insights.bulk_delivery import BulkDeliveryService
    from app.domain.bio_insights.bulk_workflow import BulkWorkflowService

    workflow = BulkWorkflowService(store)
    sensitivity = None
    if request.sensitivity:
        result = sensitivity_for(workflow, project, request.sensitivity, page_size=20, change_stream=change_stream)
        sensitivity = {key: value for key, value in result.items() if key not in ('page', 'page_size')}
    evidence = workflow.evidence(project, [entry.model_dump() for entry in request.evidence],
                                 baseline_version_id=request.comparison_version_id) if request.evidence else []
    service = BulkDeliveryService(store)
    facts = service.facts(project, request.comparison_version_id, result_version_ids=request.result_version_ids,
                          selections=request.selections, language=request.language, sensitivity=sensitivity, evidence=evidence)
    return service, facts


def checked_facts(request, facts):
    if facts['facts_digest'] != request.facts_digest:
        raise invalid('bio_insight_source_conflict', 409)
    return facts


def delivery_headers(filename, facts):
    return {
        'Content-Disposition': f'attachment; filename="{filename}"',
        'X-Bulk-Facts-SHA256': facts['facts_digest'],
        'Cache-Control': 'private, no-store',
        'X-Content-Type-Options': 'nosniff',
    }


def word_response(content, facts):
    return Response(content, media_type=WORD_MEDIA_TYPE, headers=delivery_headers('bulk-rna-seq-report.docx', facts))


@router.post('/delivery/preview')
def preview_delivery(project_id: str, request: BulkDeliveryRequest, store: Store):
    _, facts = resolve_delivery(project_id, store, request)
    return facts


@router.post('/delivery/report.docx')
def download_report(project_id: str, request: BulkDownloadRequest, store: Store):
    service, facts = resolve_delivery(project_id, store, request)
    checked_facts(request, facts)
    return word_response(service.docx(project_id, facts), facts)


@router.post('/delivery/reproducibility-package')
def download_archive(project_id: str, request: BulkDownloadRequest, store: Store):
    from app.domain.bio_insights.bulk_delivery_archive import BulkDeliveryArchive

    with tempfile.TemporaryFile(mode='w+t', encoding='utf-8', newline='') as changes:
        service, facts = resolve_delivery(project_id, store, request, change_stream=changes)
        checked_facts(request, facts)
        word = service.docx(project_id, facts)
        changes.seek(0)
        package = BulkDeliveryArchive(store).export_delivery(
            project_id, facts, word, change_table=changes.buffer if request.sensitivity else None,
        )
    handle = package['file']
    headers = delivery_headers('bulk-rna-seq-reproduction.zip', facts)
    headers['X-Reproducibility-Manifest-SHA256'] = package['manifest_sha256']
    headers['X-Analysis-Inputs-Self-Contained'] = str(package['analysis_inputs_self_contained']).lower()

    def chunks():
        try:
            while block := handle.read(1024**2):
                yield block
        finally:
            handle.close()

    return StreamingResponse(chunks(), media_type='application/zip', headers=headers, background=BackgroundTask(handle.close))
