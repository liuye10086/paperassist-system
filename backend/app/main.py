from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .config import get_excel_settings
from .excel import router as excel_router
from .upload_limit import UploadLimitMiddleware
from .projects import router as projects_router
from .storage import StorageError
from .analysis import router as analysis_router

# Fail early on invalid environment configuration.
get_excel_settings()
app = FastAPI(title="PaperAssist System")
app.add_middleware(UploadLimitMiddleware)
app.include_router(excel_router)
app.include_router(projects_router)
app.include_router(analysis_router)


@app.exception_handler(StorageError)
async def storage_error_handler(request, exc: StorageError):
    return JSONResponse(status_code=exc.status, content={"detail": {"code": exc.code, "message": exc.message}})


@app.get("/api/v1/health")
def health():
    return {
        "status": "ok",
        "service": "paperassist-system",
    }
