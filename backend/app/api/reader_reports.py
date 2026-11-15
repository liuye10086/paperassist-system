"""Review and explicitly prepare the fixed interpretation for a research report."""
from fastapi import APIRouter, Response

from app.api.bio_datasets import Key, Store
from app.api.tasks import RetryRequest
from app.domain.reader_reports.contracts import NarrativeRequest
from app.domain.reader_reports.service import ReaderReportService
from app.domain.research_results.contracts import ResearchReportRequest


router = APIRouter(prefix='/api/v1/projects/{project_id}/research-report-narratives', tags=['研究报告解读'])


@router.post('/preview')
def preview(project_id: str, request: ResearchReportRequest, store: Store):
    return ReaderReportService(store).preview(project_id, request)


@router.post('', status_code=202)
def create(project_id: str, request: NarrativeRequest, response: Response, store: Store, idempotency_key: Key):
    value, response.status_code = ReaderReportService(store).create(project_id, request, idempotency_key)
    return value


@router.get('/requests/{key}')
def request_receipt(project_id: str, key: str, store: Store):
    return ReaderReportService(store).request(project_id, key)


@router.get('/{narrative_id}')
def get(project_id: str, narrative_id: str, store: Store):
    return ReaderReportService(store).get(project_id, narrative_id)


@router.post('/{narrative_id}/retry', status_code=202)
def retry(project_id: str, narrative_id: str, request: RetryRequest, store: Store):
    return ReaderReportService(store).retry(project_id, narrative_id, request.expected_revision)
