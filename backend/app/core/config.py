from app.core.paths import BACKEND_ROOT

import os
from pathlib import Path

from pydantic import BaseModel, Field
from dotenv import dotenv_values


def local_config():
    # Read at request time so a locally saved API key is usable without exposing it.
    # Environment variables (including deliberately empty values) take precedence.
    values = dotenv_values(BACKEND_ROOT / '.env', encoding='utf-8-sig', interpolate=False)
    return {**values, **os.environ}


class ExcelSettings(BaseModel):
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, gt=0, le=10485760)
    max_uncompressed_bytes: int = Field(default=64 * 1024 * 1024, gt=0, le=67108864)
    max_sheets: int = Field(default=50, gt=0, le=50)
    max_rows: int = Field(default=100_000, gt=0, le=100000)
    max_columns: int = Field(default=256, gt=0, le=256)
    max_cells: int = Field(default=1_000_000, gt=0, le=1000000)


def get_excel_settings() -> ExcelSettings:
    """Pure deployment limits; existing analysis tasks keep their original contract."""
    config = local_config()
    return ExcelSettings(**{
        name: config[f"EXCEL_{name.upper()}"]
        for name in ExcelSettings.model_fields
        if f"EXCEL_{name.upper()}" in config
    })


def effective_excel_settings(version) -> ExcelSettings:
    """Select once while creating a task, then persist its full ParseSettings.

    Lower deployment limits always win for new operations. They never rewrite
    previously frozen snapshots, and active limits are never used as a ceiling.
    """
    deployment = get_excel_settings().model_dump()
    if version is None:
        return ExcelSettings(**deployment)
    basic = version['bundle']['basic']
    return ExcelSettings(**{name: min(value, basic[name]) for name, value in deployment.items()})


def get_request_excel_settings() -> ExcelSettings:
    """Dynamic upload/preview limits, read for each request (never at startup)."""
    from app.db.database import database_connection
    from app.domain.admin_configuration.bindings import current
    with database_connection() as db:
        return effective_excel_settings(current(db))


def get_data_dir() -> Path:
    backend_dir = BACKEND_ROOT
    configured = Path(local_config().get("PAPERASSIST_DATA_DIR") or "data").expanduser()
    return (backend_dir / configured).resolve()
