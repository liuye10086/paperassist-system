"""Owner-scoped registration and bounded per-item upload HTTP contracts."""
from typing import Annotated

from fastapi import APIRouter, Depends, File, Header, Query, Response, UploadFile
from pydantic import BeforeValidator

from app.adapters.storage import ProjectStore, get_request_project_store
from app.core.exceptions import StorageError
from app.core.config import get_request_excel_settings
from app.domain.file_batches import BatchInput, BatchItem, BatchPage, BatchView, FileBatchService
from app.api.tasks import decimal_query_integer

router = APIRouter(prefix='/api/v1/projects', tags=['文件批次'])
Store = Annotated[ProjectStore, Depends(get_request_project_store)]


@router.post('/{project_id}/file-batches', response_model=BatchView, status_code=201)
def register_batch(project_id: str, request: BatchInput, response: Response, store: Store,
    idempotency_key: Annotated[str, Header(min_length=1, max_length=128, pattern=r'^[\x21-\x7e]+$')]):
    result, status = FileBatchService(store).register(project_id, request, idempotency_key)
    response.status_code = status
    return result


@router.get('/{project_id}/file-batches', response_model=BatchPage)
def list_batches(project_id: str, store: Store,
    page: Annotated[int, Query(ge=1, le=1000000), BeforeValidator(decimal_query_integer)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100), BeforeValidator(decimal_query_integer)] = 5):
    return FileBatchService(store).list(project_id, page, page_size)


@router.get('/{project_id}/file-batches/{batch_id}', response_model=BatchView)
def read_batch(project_id: str, batch_id: str, store: Store):
    return FileBatchService(store).get(project_id, batch_id)


@router.post('/{project_id}/file-batches/{batch_id}/items/{item_id}', response_model=BatchItem, status_code=202)
def upload_item(project_id: str, batch_id: str, item_id: str, store: Store,
                file: Annotated[UploadFile | None, File()] = None):
    if file is None or not file.filename:
        raise StorageError('missing_file', '请选择登记的文件。', 422)
    # No ZIP/XML expansion in this process. The body middleware bounds multipart.
    maximum = get_request_excel_settings().max_upload_bytes
    content = file.file.read(maximum + 1)
    if len(content) > maximum:
        raise StorageError('file_too_large', '文件超过上传大小限制。', 413, params={'max_bytes': maximum})
    return FileBatchService(store).upload(project_id, batch_id, item_id, file.filename, content)
