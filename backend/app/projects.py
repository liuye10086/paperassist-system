import json
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from .config import ExcelSettings, get_excel_settings
from .excel import WorkbookPreview, fail, parse_workbook, read_upload
from .storage import PROJECT_UPDATE_LIMITS, ProjectStore, get_request_project_store

router = APIRouter(prefix="/api/v1/projects", tags=["项目与文件"])
Store = Annotated[ProjectStore, Depends(get_request_project_store)]


class ProjectInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    research_topic: str = Field(min_length=1, max_length=500)
    project_type: Literal["sci", "thesis"]


class Project(ProjectInput):
    id: str
    created_at: str
    updated_at: str
    file_count: int


class FileError(BaseModel):
    code: str
    message: str


class ProjectFile(BaseModel):
    id: str
    project_id: str
    filename: str
    file_type: Literal["xlsx"]
    size_bytes: int
    sha256: str
    uploaded_at: str
    parse_status: Literal["parsed", "failed"]
    error: FileError | None


class SavedUpload(BaseModel):
    file: ProjectFile
    preview: WorkbookPreview | None


@router.get("", response_model=list[Project])
def list_projects(store: Store):
    return store.projects()


@router.post("", status_code=201, response_model=Project)
def create_project(project: ProjectInput, store: Store):
    return store.create_project(**project.model_dump())


@router.get("/{project_id}", response_model=Project)
def get_project(project_id: str, store: Store):
    return store.project(project_id)


@router.patch('/{project_id}', response_model=Project,
              openapi_extra={'requestBody': {'required': True}})
def update_project(project_id: str, store: Store, changes: Annotated[Any, Body(
    description='仅修改名称或研究主题，项目类型创建后不可更改。',
    json_schema_extra={
        'type': 'object', 'minProperties': 1, 'additionalProperties': False,
        'properties': {field: {'type': 'string', 'minLength': 1, 'maxLength': limit}
                       for field, limit in PROJECT_UPDATE_LIMITS.items()},
    },
)] = None):
    # The persistence boundary validates raw JSON once and returns stable
    # application errors, including null, unknown fields and type lock attempts.
    return store.update_project(project_id, changes)


@router.get("/{project_id}/files", response_model=list[ProjectFile])
def list_files(project_id: str, store: Store):
    return store.files(project_id)


@router.post("/{project_id}/files", status_code=201, response_model=SavedUpload)
def upload_file(
    project_id: str, store: Store,
    settings: Annotated[ExcelSettings, Depends(get_excel_settings)],
    file: Annotated[UploadFile | None, File(description="一个 .xlsx 工作簿")] = None,
):
    store.project(project_id)
    filename, content = read_upload(file, settings)
    preview, error = None, None
    try:
        preview = parse_workbook(content, filename, settings)
    except HTTPException as exc:
        if exc.status_code != 422:
            raise
        error = exc.detail
    record = store.save_file(project_id, filename, content, preview.model_dump_json() if preview else None, error)
    return SavedUpload(file=record, preview=preview)


@router.get("/{project_id}/files/{file_id}/preview", response_model=WorkbookPreview)
def get_preview(project_id: str, file_id: str, store: Store):
    record = store.file(project_id, file_id)
    store.original(record)
    if record["parse_status"] == "failed":
        error = json.loads(record["error_json"])
        fail(error["code"], error["message"])
    return WorkbookPreview.model_validate_json(record["preview_json"])


@router.get("/{project_id}/files/{file_id}/download")
def download_file(project_id: str, file_id: str, store: Store):
    record = store.file(project_id, file_id)
    return Response(store.original(record), media_type="application/octet-stream", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(record['filename'], safe='')}",
        "X-Content-Type-Options": "nosniff",
    })
