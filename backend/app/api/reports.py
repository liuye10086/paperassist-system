"""HTTP routes for reports; business operations live in domain."""
from urllib.parse import quote

from fastapi import APIRouter, Response

from app.api.dependencies import Store
from app.domain import reports as operations
from app.domain.reports import ReportRequest
from app.adapters.report_store import ReportStore

router = APIRouter(prefix='/api/v1/projects/{project_id}/files/{file_id}/analysis-runs/{run_id}', tags=['Word 分析报告'])


@router.get('/report')
def get_report(project_id: str, file_id: str, run_id: str, store: Store):
    return operations.get_report(project_id, file_id, run_id, store)

@router.post('/report')
def generate_report(project_id: str, file_id: str, run_id: str, request: ReportRequest, store: Store, response: Response):
    result, response.status_code = operations.generate_report(project_id, file_id, run_id, request, store)
    return result

@router.get('/report/{report_id}/download')
def download(project_id: str, file_id: str, run_id: str, report_id: str, store: Store):
    repository = ReportStore(store)
    report = repository.by_id(project_id, file_id, run_id, report_id)
    return Response(repository.content(report), media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                    headers={'Content-Disposition': "attachment; filename=analysis-report.docx; filename*=UTF-8''" + quote(report['filename']),
                             'Cache-Control': 'no-store'})
