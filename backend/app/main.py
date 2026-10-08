import asyncio
from contextlib import asynccontextmanager, suppress
import logging

from fastapi import FastAPI
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
from app.core.errors import PUBLIC_CODES, error_response, fallback_error, unexpected_error_response
from app.core.request_id import RequestIdMiddleware

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
