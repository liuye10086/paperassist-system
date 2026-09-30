import json
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

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


class ProjectPage(BaseModel):
    items: list[Project]
    total: int
    page: int
    page_size: int


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


def decimal_query_integer(value):
    # Validate the raw HTTP string before Pydantic can coerce "1.0" to 1.
    if value is not None and (not isinstance(value, str) or not value.isascii() or not value.isdecimal()):
        raise ValueError('页码和页面大小须为十进制整数字符串。')
    return value


@router.get("", response_model=list[Project] | ProjectPage,
            description='无page/page_size/q/type参数返回数组，任一显式参数启用分页对象。')
def list_projects(
    store: Store,
    page: Annotated[int | None, Query(ge=1, le=1_000_000), BeforeValidator(decimal_query_integer)] = None,
    page_size: Annotated[int | None, Query(ge=1, le=100), BeforeValidator(decimal_query_integer)] = None,
    q: Annotated[str | None, Query()] = None,
    project_type: Annotated[Literal['sci', 'thesis'] | None, Query(alias='type')] = None,
):
    if all(value is None for value in (page, page_size, q, project_type)):
        return store.projects()
    return store.query_projects(page=page if page is not None else 1,
                                page_size=page_size if page_size is not None else 10,
                                q=q if q is not None else '', project_type=project_type)


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
