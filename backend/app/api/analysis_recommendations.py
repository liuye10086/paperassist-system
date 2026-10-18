"""Explicit recommendation preview/create and read-only review routes."""
from fastapi import APIRouter, Response
from app.core.exceptions import StorageError
from app.api.dataset_preparation import Store, Key
from app.domain.analysis_recommendation.contracts import PreviewRequest, CreateRequest, PreviewRequestV2, CreateRequestV2, PreviewRequestV3, CreateRequestV3, PreviewRequestV4, CreateRequestV4, PreviewRequestV5, CreateRequestV5
from app.domain.analysis_recommendation.service import RecommendationService
from app.domain.tasks.contracts import TaskView

router=APIRouter(prefix='/api/v1',tags=['分析建议'])


@router.post('/projects/{project_id}/files/{file_id}/analysis-recommendations/preview')
def preview(project_id:str,file_id:str,request:PreviewRequestV5 | PreviewRequestV4 | PreviewRequestV3 | PreviewRequestV2 | PreviewRequest,store:Store):
    if getattr(request,'schema_version',None)!=5:raise StorageError('task_input_invalid','新建议须使用来源引用合同v5。',422)
    return RecommendationService(store).preview(project_id,file_id,request)


@router.post('/projects/{project_id}/files/{file_id}/analysis-recommendations',response_model=TaskView,status_code=202)
def create(project_id:str,file_id:str,request:CreateRequestV5 | CreateRequestV4 | CreateRequestV3 | CreateRequestV2 | CreateRequest,response:Response,store:Store,idempotency_key:Key):
    if getattr(request,'schema_version',None)!=5:raise StorageError('task_input_invalid','新建议须使用来源引用合同v5。',422)
    task,status=RecommendationService(store).create(project_id,file_id,request,idempotency_key)
    response.status_code=status
    return task


@router.get('/tasks/{task_id}/analysis-recommendation')
def get(task_id:str,store:Store):
    return RecommendationService(store).get(task_id)
