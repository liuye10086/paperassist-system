"""Owner-scoped OCR review: explicit saved decisions and immutable versions."""
from typing import Annotated
from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import BeforeValidator
from app.adapters.storage import ProjectStore, get_request_project_store
from app.api.tasks import decimal_query_integer
from app.domain.ocr_review.service import OcrReviewService, OcrReviewCreateRequest, OcrReviewDecisionRequest
from app.domain.tasks.contracts import TaskView

router = APIRouter(prefix='/api/v1',tags=['OCR 核对'])
Store = Annotated[ProjectStore,Depends(get_request_project_store)]
Key = Annotated[str,Header(min_length=1,max_length=128,pattern=r'^[\x21-\x7e]+$')]
Page = Annotated[int,Query(ge=1,le=1000000),BeforeValidator(decimal_query_integer)]
Five = Annotated[int,Query(ge=5,le=5),BeforeValidator(decimal_query_integer)]
Parse = Annotated[str|None,Query(min_length=1,max_length=64)]


@router.post('/projects/{project_id}/files/{file_id}/ocr-reviews',response_model=TaskView,status_code=202)
def create(project_id:str,file_id:str,request:OcrReviewCreateRequest,response:Response,store:Store,idempotency_key:Key):
    task,status = OcrReviewService(store).create(project_id,file_id,request,idempotency_key)
    response.status_code = status
    return task


@router.get('/projects/{project_id}/files/{file_id}/ocr-reviews')
def list_tasks(project_id:str,file_id:str,store:Store,parse_id:Parse=None):
    return OcrReviewService(store).list_tasks(project_id,file_id,parse_id)


@router.get('/tasks/{task_id}/ocr-review')
def review(task_id:str,store:Store):
    return OcrReviewService(store).get_task(task_id)


@router.post('/tasks/{task_id}/ocr-review/decision',response_model=TaskView,status_code=202)
def decide(task_id:str,request:OcrReviewDecisionRequest,store:Store,idempotency_key:Key):
    return OcrReviewService(store).decide(task_id,request,idempotency_key)


@router.get('/tasks/{task_id}/ocr-review/preview/download')
def preview_download(task_id:str,store:Store):
    return Response(OcrReviewService(store).preview_download(task_id),media_type='application/json',
        headers={'Content-Disposition':'attachment; filename="ocr-review-preview.json"'})


@router.get('/projects/{project_id}/files/{file_id}/ocr-review-versions')
def versions(project_id:str,file_id:str,store:Store,parse_id:Parse=None,page:Page=1,page_size:Five=5):
    return OcrReviewService(store).list_versions(project_id,file_id,parse_id,page,page_size)


@router.get('/projects/{project_id}/files/{file_id}/ocr-review-versions/{review_id}')
def detail(project_id:str,file_id:str,review_id:str,store:Store):
    return OcrReviewService(store).get_version(project_id,file_id,review_id)


@router.get('/projects/{project_id}/files/{file_id}/ocr-review-versions/{review_id}/download')
def download(project_id:str,file_id:str,review_id:str,store:Store):
    row,content,_ = OcrReviewService(store).load_version(project_id,file_id,review_id)
    return Response(content,media_type='application/json',
        headers={'Content-Disposition':f'attachment; filename="ocr-review-v{row["version"]}.json"'})
