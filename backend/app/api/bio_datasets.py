"""Independent biological upload profile and explicit candidate review API."""
from typing import Annotated, Literal
from urllib.parse import quote
from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BeforeValidator
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from app.adapters.storage import ProjectStore, get_request_project_store
from app.adapters.bio_dataset_store import BioDatasetStore
from app.api.upload_limit import bio_upload_form
from app.core.exceptions import StorageError
from app.domain.file_batches import BatchInput, BioUploadService
from app.domain.bioinformatics.contracts import BioImportRequest, BioImportRequestV2, BioConfirmRequest
from app.domain.bioinformatics.tabular_contracts import BioImportRequestV3
from app.domain.bioinformatics.single_cell_contracts import SingleCellImportRequest
from app.domain.bioinformatics.service import BioDatasetService
from app.domain.bioinformatics.settings import BioLimits
from app.api.tasks import decimal_query_integer

router=APIRouter(prefix='/api/v1/projects',tags=['生信数据接入'])
Store=Annotated[ProjectStore,Depends(get_request_project_store)]
Key=Annotated[str,Header(alias='Idempotency-Key',min_length=1,max_length=128,pattern=r'^[\x21-\x7e]+$')]
Page=Annotated[int,Query(ge=1,le=1000000),BeforeValidator(decimal_query_integer)]


@router.post('/{project_id}/bio-upload-batches',status_code=201)
def register(project_id:str,request:BatchInput,response:Response,store:Store,idempotency_key:Key):
    result,status=BioUploadService(store).register(project_id,request,idempotency_key)
    response.status_code=status
    return result


@router.get('/{project_id}/bio-upload-batches')
def batches(project_id:str,store:Store,page:Page=1):
    return BioUploadService(store).list(project_id,page,5)


@router.get('/{project_id}/bio-upload-batches/{batch_id}')
def batch(project_id:str,batch_id:str,store:Store):
    return BioUploadService(store).get(project_id,batch_id)


@router.post('/{project_id}/bio-upload-batches/{batch_id}/items/{item_id}', status_code=202,
    openapi_extra={'requestBody': {'content': {'multipart/form-data': {'schema': {
        'type': 'object', 'properties': {'file': {'type': 'string', 'format': 'binary'}},
    }}}}})
async def upload(project_id: str, batch_id: str, item_id: str, store: Store, request: Request):
    async with bio_upload_form(request, BioLimits().max_upload_bytes) as form:
        file = form.get('file')
        if file is None or (isinstance(file, UploadFile) and not file.filename):
            raise StorageError('missing_file', '请选择登记的原始文件。', 422)
        if not isinstance(file, UploadFile):
            raise StorageError('invalid_request', '请求格式无效，请检查上传文件后重试。', 422)
        return await run_in_threadpool(
            BioUploadService(store).upload, project_id, batch_id, item_id, file.filename, file.file, file.size)


@router.post('/{project_id}/bio-imports',status_code=202)
def create_import(project_id:str,request:BioImportRequest | BioImportRequestV2 | BioImportRequestV3 | SingleCellImportRequest,store:Store,idempotency_key:Key):
    return BioDatasetService(store).create(project_id,request,idempotency_key)


@router.get('/{project_id}/bio-imports/{import_id}')
def read_import(project_id:str,import_id:str,store:Store):
    return BioDatasetService(store).get(project_id,import_id)


@router.post('/{project_id}/bio-imports/{import_id}/confirm',status_code=202)
def confirm(project_id:str,import_id:str,request:BioConfirmRequest,store:Store,idempotency_key:Key):
    return BioDatasetService(store).confirm(project_id,import_id,request,idempotency_key)


@router.get('/{project_id}/bio-datasets')
def datasets(project_id:str,store:Store,page:Page=1,page_size:Annotated[int,Query(ge=5,le=5),BeforeValidator(decimal_query_integer)]=5):
    return BioDatasetStore(store).list(project_id,page)


@router.get('/{project_id}/bio-datasets/{dataset_id}/versions/{version_id}')
def version(project_id:str,dataset_id:str,version_id:str,store:Store):
    return BioDatasetStore(store).version(project_id,dataset_id,version_id)


@router.get('/{project_id}/bio-datasets/{dataset_id}/versions/{version_id}/manifest')
def manifest(project_id:str,dataset_id:str,version_id:str,store:Store):
    content=BioDatasetStore(store).manifest(project_id,dataset_id,version_id)
    return Response(content,media_type='application/json',headers={'Content-Disposition':'attachment; filename="bio-manifest.json"'})


@router.get('/{project_id}/bio-datasets/{dataset_id}/versions/{version_id}/members/{member_id}')
@router.get('/{project_id}/bio-datasets/{dataset_id}/versions/{version_id}/members/{member_id}/download')
def member(project_id:str,dataset_id:str,version_id:str,member_id:str,store:Store):
    item,content=BioDatasetStore(store).member(project_id,dataset_id,version_id,member_id)
    media={'png':'image/png','jpeg':'image/jpeg','jpg':'image/jpeg'}.get(item['format'],'application/octet-stream')
    filename=item['filename']
    return Response(content,media_type=media,headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(filename,safe='')})


@router.get('/{project_id}/bio-datasets/{dataset_id}/versions/{version_id}/matrix-preview')
def preview(project_id:str,dataset_id:str,version_id:str,store:Store,features_page:Page=1,observations_page:Page=1):
    return BioDatasetStore(store).preview(project_id,dataset_id,version_id,features_page,observations_page)


@router.get('/{project_id}/bio-datasets/{dataset_id}/versions/{version_id}/coordinate-preview')
def coordinates(project_id:str,dataset_id:str,version_id:str,store:Store,image_member_id:Annotated[str|None,Query(max_length=64)]=None):
    return BioDatasetStore(store).coordinates(project_id,dataset_id,version_id,image_member_id)
