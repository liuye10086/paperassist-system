"""HTTP upload preview routes for the workbook parser."""
from typing import Annotated
from fastapi import APIRouter, Depends, File, UploadFile
from app.core.config import ExcelSettings, get_excel_settings
from app.adapters.excel import PreviewConfig, WorkbookPreview, parse_workbook, read_upload

router = APIRouter(prefix="/api/v1/excel", tags=["Excel 预览"])


@router.get("/config", response_model=PreviewConfig)
def preview_config(settings: Annotated[ExcelSettings, Depends(get_excel_settings)]):
    return PreviewConfig(max_upload_bytes=settings.max_upload_bytes)


@router.post("/preview", response_model=WorkbookPreview)
def preview_excel(
    settings: Annotated[ExcelSettings, Depends(get_excel_settings)],
    file: Annotated[UploadFile | None, File(description="一个 .xlsx 工作簿")] = None,
):
    filename, content = read_upload(file, settings)
    return parse_workbook(content, filename, settings)
