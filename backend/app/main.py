import asyncio
from contextlib import asynccontextmanager, suppress
import logging

from app.core.safe_logging import configure_safe_logging

configure_safe_logging()

from fastapi import FastAPI, Depends
from app.api.research_guards import legacy_writing_project
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from app.core.config import get_excel_settings, local_config
from app.api.excel import router as excel_router
from app.api.upload_limit import UploadLimitMiddleware
from app.auth.middleware import AuthMiddleware
from app.auth.routes import router as auth_router
from app.auth.config import settings as auth_settings
from app.api.projects import router as projects_router
from app.core.exceptions import StorageError
from app.adapters.storage import check_database_ready
from app.api.analysis import router as analysis_router
from app.api.descriptive import router as descriptive_router
from app.api.boxplot import router as boxplot_router
from app.domain.boxplot import poll_pending_figures
from app.adapters.openai_plot import configuration
from app.api.explanations import router as explanations_router
from app.domain.explanations import poll_pending_explanations
from app.api.reports import router as reports_router
from app.api.tasks import router as tasks_router, project_router as project_tasks_router
from app.api.model_usage import router as model_usage_router
from app.api.file_batches import router as file_batches_router
from app.api.datasets import router as datasets_router
from app.api.dataset_preparation import router as dataset_preparation_router
from app.api.analysis_plans import router as analysis_plans_router
from app.api.file_lifecycle import router as file_lifecycle_router
from app.api.ocr_review import router as ocr_review_router
from app.core.errors import PUBLIC_CODES, error_response, fallback_error, unexpected_error_response
from app.core.request_id import RequestIdMiddleware, configure_request_logging

configure_request_logging()

# Fail early on invalid environment configuration.
get_excel_settings()
auth_settings()
async def run_recovery_worker(poll, name):
    while True:
        try:
            await asyncio.to_thread(poll)
        except Exception as exc:
            # Avoid logging provider bodies, research input or credentials.
            logging.getLogger(__name__).warning('%s recovery scan failed (%s)', name, type(exc).__name__)
        await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app):
    check_database_ready()
    tasks = []
    if local_config().get('PAPERASSIST_PLOT_WORKER_ENABLED', '1') != '0':
        tasks = [asyncio.create_task(run_recovery_worker(poll, name)) for poll, name in
                 ((poll_pending_figures, 'Plot'), (poll_pending_explanations, 'Explanation'))]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


app = FastAPI(title="PaperAssist System", lifespan=lifespan)
app.add_middleware(UploadLimitMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(RequestIdMiddleware)
app.include_router(auth_router)
from app.api.runtime_status import router as runtime_status_router
app.include_router(runtime_status_router)
app.include_router(excel_router)
app.include_router(projects_router)
app.include_router(analysis_router)
app.include_router(descriptive_router)
app.include_router(boxplot_router)
app.include_router(explanations_router)
app.include_router(reports_router)
app.include_router(tasks_router)
app.include_router(project_tasks_router)
app.include_router(model_usage_router)
from app.api.storage_governance import router as storage_governance_router
app.include_router(storage_governance_router)
from app.api.storage_deletion import router as storage_deletion_router
app.include_router(storage_deletion_router)
from app.api.documents import router as documents_router
app.include_router(documents_router)
app.include_router(file_batches_router)
from app.api.research_intake import router as research_intake_router
app.include_router(research_intake_router)
from app.api.bio_datasets import router as bio_datasets_router
from app.api.bio_analysis import router as bio_analysis_router
app.include_router(bio_datasets_router)
app.include_router(bio_analysis_router)
app.include_router(datasets_router)
app.include_router(dataset_preparation_router)
app.include_router(analysis_plans_router)
app.include_router(file_lifecycle_router)
app.include_router(ocr_review_router)
from app.api.parsed_evidence import router as parsed_evidence_router
app.include_router(parsed_evidence_router)
from app.api.external_evidence import router as external_evidence_router
app.include_router(external_evidence_router)
from app.api.literature import router as literature_router
app.include_router(literature_router)
from app.api.literature_evidence import router as literature_evidence_router
app.include_router(literature_evidence_router)
from app.api.literature_pmc import router as literature_pmc_router
app.include_router(literature_pmc_router)
from app.api.literature_assistance import router as literature_assistance_router
app.include_router(literature_assistance_router)
from app.api.literature_citations import router as literature_citations_router
app.include_router(literature_citations_router)
from app.api.manuscripts import router as manuscripts_router
app.include_router(manuscripts_router, dependencies=[Depends(legacy_writing_project)])


@app.get('/api/v1/ai/config')
def ai_config():
    return configuration()


@app.get('/api/v1/ai/explanation-config')
def explanation_ai_config():
    from app.domain.explanation_policy import configuration as explanation_configuration
    return explanation_configuration()


@app.get('/api/v1/ai/plot-config')
def plot_ai_config():
    from app.domain.plot_policy import configuration as plot_configuration
    return plot_configuration()


@app.exception_handler(StorageError)
async def storage_error_handler(request, exc: StorageError):
    return error_response(exc.status, exc.code, exc.message, getattr(exc, 'params', None))


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request, exc):
    # Pydantic errors can contain passwords, request input and arbitrary context.
    if request.url.path.endswith('/ocr-review/decision'):
        message = '替换文字不能为空；无法辨认请使用 unreadable。'
        if any(str(error.get('ctx', {}).get('error', '')) == message for error in exc.errors()):
            return error_response(422, 'task_input_invalid', message)
    return error_response(422, 'invalid_request', '请求格式无效，请检查填写的内容后重试。')


@app.exception_handler(HTTPException)
async def http_error_handler(request, exc):
    detail = exc.detail
    if (isinstance(detail, dict) and isinstance(detail.get('code'), str)
            and detail['code'] in PUBLIC_CODES and isinstance(detail.get('message'), str)):
        return error_response(exc.status_code, detail['code'], detail['message'], detail.get('params'), exc.headers)
    code, message = fallback_error(exc.status_code)
    return error_response(exc.status_code, code, message, headers=exc.headers)


@app.exception_handler(Exception)
async def unexpected_error_handler(request, exc):
    return unexpected_error_response(exc)


@app.get("/api/v1/health")
def health():
    check_database_ready()
    return {
        "status": "ok",
        "service": "paperassist-system",
    }

from app.api.analysis_recommendations import router as recommendation_router
app.include_router(recommendation_router)

from app.api.report_collections import router as report_collections_router
app.include_router(report_collections_router)

from app.api.figure_workbench import router as figure_workbench_router
app.include_router(figure_workbench_router)

from app.api.literature_checks import router as literature_checks_router
app.include_router(literature_checks_router)

from app.api.pdf_exports import router as pdf_exports_router
app.include_router(pdf_exports_router)

from app.api.manuscript_writing import router as manuscript_writing_router
app.include_router(manuscript_writing_router, dependencies=[Depends(legacy_writing_project)])
from app.api.manuscript_review import router as manuscript_review_router
app.include_router(manuscript_review_router, dependencies=[Depends(legacy_writing_project)])

from app.api.layout_exports import router as layout_exports_router
app.include_router(layout_exports_router)

from app.api.manuscript_writing import preview_router, authorization_router
app.include_router(preview_router, dependencies=[Depends(legacy_writing_project)])
app.include_router(authorization_router, dependencies=[Depends(legacy_writing_project)])

from app.api.manuscript_figure_language import router as manuscript_figure_language_router
app.include_router(manuscript_figure_language_router, dependencies=[Depends(legacy_writing_project)])

from app.api.school_templates import router as school_templates_router
app.include_router(school_templates_router, dependencies=[Depends(legacy_writing_project)])

from app.api.manuscript_school_changes import router as manuscript_school_changes_router
app.include_router(manuscript_school_changes_router, dependencies=[Depends(legacy_writing_project)])

from app.api.journals import router as journals_router
app.include_router(journals_router, dependencies=[Depends(legacy_writing_project)])

from app.api.review_rounds import router as review_rounds_router
app.include_router(review_rounds_router, dependencies=[Depends(legacy_writing_project)])

from app.api.review_documents import router as review_documents_router
app.include_router(review_documents_router, dependencies=[Depends(legacy_writing_project)])

from app.api.review_science import router as review_science_router
app.include_router(review_science_router, dependencies=[Depends(legacy_writing_project)])

from app.api.review_continuations import router as review_continuations_router
app.include_router(review_continuations_router, dependencies=[Depends(legacy_writing_project)])

from app.api.admin import router as admin_router
app.include_router(admin_router)

from app.api.admin_configurations import router as admin_configurations_router
app.include_router(admin_configurations_router)
