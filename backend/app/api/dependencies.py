"""Request-scoped HTTP dependencies shared by analysis routes."""
from typing import Annotated

from fastapi import Depends

from app.adapters.storage import ProjectStore, get_request_project_store
from app.core.config import ExcelSettings, get_excel_settings

Store = Annotated[ProjectStore, Depends(get_request_project_store)]
Settings = Annotated[ExcelSettings, Depends(get_excel_settings)]
