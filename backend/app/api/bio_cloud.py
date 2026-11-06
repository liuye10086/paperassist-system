"""Cloud FASTQ transport and asynchronous preprocessing in the existing project."""
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, Header, Path, Query, Response
from app.adapters.storage import ProjectStore, get_request_project_store
from app.domain.bio_cloud.requests import UploadRequest, PartRequest, RunRequest, EmptyRequest, ReconcileRequest
from app.domain.bio_cloud.service import CloudService
from app.domain.bio_cloud.uploads import CloudUploads

router = APIRouter(prefix='/api/v1/projects/{project_id}/bio-cloud', tags=['外部生信计算'])
Store = Annotated[ProjectStore, Depends(get_request_project_store)]
Key = Annotated[str, Header(alias='Idempotency-Key', min_length=1, max_length=128, pattern=r'^[\x21-\x7e]+$')]


@router.get('/capabilities')
def capabilities(project_id: str, store: Store):
    return CloudService(store).capabilities(project_id)


@router.get('/uploads')
def uploads(project_id: str, store: Store):
    return CloudUploads(CloudService(store)).list(project_id)


@router.post('/uploads', status_code=201)
def begin_upload(project_id: str, request: UploadRequest, store: Store, idempotency_key: Key, response: Response):
    value, status = CloudUploads(CloudService(store)).begin(project_id,request,idempotency_key)
    response.status_code = status
    return value


@router.get('/uploads/{upload_id}')
def upload(project_id: str, upload_id: str, store: Store):
    return CloudUploads(CloudService(store)).get(project_id,upload_id)


@router.get('/uploads/{upload_id}/parts')
def parts(project_id: str, upload_id: str, store: Store):
    return CloudUploads(CloudService(store)).parts(project_id,upload_id)


@router.post('/uploads/{upload_id}/parts/{number}/sign')
def sign(project_id: str, upload_id: str, number: Annotated[int, Path(ge=1,le=10000)], request: PartRequest, store: Store):
    return CloudUploads(CloudService(store)).sign(project_id,upload_id,number,request.checksum_sha256)


@router.post('/uploads/{upload_id}/complete')
def complete(project_id: str, upload_id: str, request: EmptyRequest, store: Store):
    return CloudUploads(CloudService(store)).complete(project_id,upload_id)


@router.post('/uploads/{upload_id}/cancel')
def cancel_upload(project_id: str, upload_id: str, request: EmptyRequest, store: Store):
    return CloudUploads(CloudService(store)).cancel(project_id,upload_id)


@router.get('/runs')
def runs(project_id: str, store: Store):
    return CloudService(store).list_runs(project_id)


@router.post('/runs', status_code=202)
def create_run(project_id: str, request: RunRequest, store: Store, idempotency_key: Key):
    return CloudService(store).create(project_id,request,idempotency_key)


@router.get('/runs/{run_id}')
def run(project_id: str, run_id: str, store: Store):
    return CloudService(store).get(project_id,run_id)


@router.post('/runs/{run_id}/cancel', status_code=202)
def cancel_run(project_id: str, run_id: str, request: EmptyRequest, store: Store):
    return CloudService(store).cancel(project_id,run_id)


@router.post('/runs/{run_id}/retry', status_code=202)
def retry_run(project_id: str, run_id: str, request: EmptyRequest, store: Store):
    return CloudService(store).retry(project_id,run_id)


@router.post('/runs/{run_id}/reconcile', status_code=202)
def reconcile_run(project_id: str, run_id: str, request: ReconcileRequest, store: Store):
    return CloudService(store).reconcile(project_id,run_id,request.provider_run_id)


@router.get('/requests/{request_key}')
def lookup(project_id: str, request_key: str, store: Store, kind: Literal['upload','run'] = Query()):
    return CloudService(store).lookup(project_id,request_key,kind)
