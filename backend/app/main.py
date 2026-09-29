import asyncio
from contextlib import asynccontextmanager, suppress
import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .config import get_excel_settings, local_config
from .excel import router as excel_router
from .upload_limit import UploadLimitMiddleware
from .projects import router as projects_router
from .storage import StorageError
from .analysis import router as analysis_router
from .descriptive import router as descriptive_router
from .boxplot import router as boxplot_router, poll_pending_figures
from .openai_plot import configuration
from .explanations import router as explanations_router, poll_pending_explanations

# Fail early on invalid environment configuration.
get_excel_settings()
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
app.include_router(excel_router)
app.include_router(projects_router)
app.include_router(analysis_router)
app.include_router(descriptive_router)
app.include_router(boxplot_router)
app.include_router(explanations_router)


@app.get('/api/v1/ai/config')
def ai_config():
    return configuration()


@app.exception_handler(StorageError)
async def storage_error_handler(request, exc: StorageError):
    return JSONResponse(status_code=exc.status, content={"detail": {"code": exc.code, "message": exc.message}})


@app.get("/api/v1/health")
def health():
    return {
        "status": "ok",
        "service": "paperassist-system",
    }
