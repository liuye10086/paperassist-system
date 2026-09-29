import os
from pathlib import Path

from pydantic import BaseModel, Field


class ExcelSettings(BaseModel):
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    max_uncompressed_bytes: int = Field(default=64 * 1024 * 1024, gt=0)
    max_sheets: int = Field(default=50, gt=0)
    max_rows: int = Field(default=100_000, gt=0)
    max_columns: int = Field(default=256, gt=0)
    max_cells: int = Field(default=1_000_000, gt=0)


def get_excel_settings() -> ExcelSettings:
    return ExcelSettings(**{
        name: os.environ[f"EXCEL_{name.upper()}"]
        for name in ExcelSettings.model_fields
        if f"EXCEL_{name.upper()}" in os.environ
    })


def get_data_dir() -> Path:
    backend_dir = Path(__file__).resolve().parents[1]
    configured = Path(os.environ.get("PAPERASSIST_DATA_DIR", "data")).expanduser()
    return (backend_dir / configured).resolve()
