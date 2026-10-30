"""Independent biological upload profile and explicit candidate review API."""
from typing import Annotated, Literal
from urllib.parse import quote
from fastapi import APIRouter, Depends, File, Header, Query, Response, UploadFile
from pydantic import BeforeValidator
from app.adapters.storage import ProjectStore, get_request_project_store
from app.adapters.bio_dataset_store import BioDatasetStore
from app.core.exceptions import StorageError
from app.domain.file_batches import BatchInput, BioUploadService
from app.domain.bioinformatics.contracts import BioImportRequest, BioImportRequestV2, BioConfirmRequest
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


@router.post('/{project_id}/bio-upload-batches/{batch_id}/items/{item_id}',status_code=202)
def upload(project_id:str,batch_id:str,item_id:str,store:Store,file:Annotated[UploadFile|None,File()]=None):
    if file is None or not file.filename:
        raise StorageError('missing_file','请选择登记的原始文件。',422)
    maximum=BioLimits().max_upload_bytes
    content=file.file.read(maximum+1)
    if len(content)>maximum:
        raise StorageError('file_too_large','生信原始文件超过上传限制。',413,params={'max_bytes':maximum})
    return BioUploadService(store).upload(project_id,batch_id,item_id,file.filename,content)


@router.post('/{project_id}/bio-imports',status_code=202)
def create_import(project_id:str,request:BioImportRequest | BioImportRequestV2,store:Store,idempotency_key:Key):
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
