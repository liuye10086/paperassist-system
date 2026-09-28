from fastapi import FastAPI

from .config import get_excel_settings
from .excel import router as excel_router
from .upload_limit import UploadLimitMiddleware

# Fail early on invalid environment configuration.
get_excel_settings()
app = FastAPI(title="PaperAssist System")
app.add_middleware(UploadLimitMiddleware)
app.include_router(excel_router)


@app.get("/api/v1/health")
def health():
    return {
        "status": "ok",
        "service": "paperassist-system",
    }
