"""Explicit plan creation and decisions; owner-scoped GETs are read-only."""
from fastapi import APIRouter,Response
from app.core.exceptions import StorageError
from app.api.dataset_preparation import Store,Key,Page,Five
from app.domain.tasks.contracts import TaskView
from app.domain.analysis_plan.contracts import (AnalysisPlanCreateRequest,AnalysisPlanDecisionRequest,
    AnalysisPlanReview,AnalysisPlanPage,ConfirmedPlan,ConfirmedResearchPlan,ConfirmedModernPlan)
from app.domain.analysis_plan.service import AnalysisPlanService

from app.domain.analysis_plan.requirements import SourceRequirementCreateRequest,SourceRequirementReview,ConfirmedSourceRequirementPlan,SourceDecisionRequest,RequirementCreateRequest,ContinuationRequest,ConfirmedRequirementPlan,RequirementReview,RequirementPage
from app.domain.analysis_plan.requirements_service import create_requirement,continue_requirement

router=APIRouter(prefix='/api/v1',tags=['分析计划'])


@router.post('/projects/{project_id}/files/{file_id}/analysis-plans',response_model=TaskView,status_code=202)
def create(project_id:str,file_id:str,request:SourceRequirementCreateRequest | RequirementCreateRequest | AnalysisPlanCreateRequest,response:Response,store:Store,idempotency_key:Key):
    if request.schema_version!=5:raise StorageError('task_input_invalid','新计划须使用来源确认合同v5。',422)
    if isinstance(request,RequirementCreateRequest):
        if request.file_id!=file_id:
            raise StorageError('task_input_invalid','文件路径与需求来源不一致。',422)
        task,status=create_requirement(AnalysisPlanService(store),project_id,request,idempotency_key)
    else:task,status=AnalysisPlanService(store).create(project_id,file_id,request,idempotency_key)
    response.status_code=status
    return task


@router.get('/tasks/{task_id}/analysis-plan',response_model=SourceRequirementReview | RequirementReview | AnalysisPlanReview)
def review(task_id:str,store:Store):
    return AnalysisPlanService(store).get_task(task_id)


@router.post('/tasks/{task_id}/analysis-plan/decisions',response_model=TaskView,status_code=202)
def decide(task_id:str,request:AnalysisPlanDecisionRequest,response:Response,store:Store,idempotency_key:Key):
    task,status=AnalysisPlanService(store).decide(task_id,request,idempotency_key)
    response.status_code=status
    return task


@router.get('/projects/{project_id}/files/{file_id}/analysis-plans',response_model=RequirementPage)
def list_plans(project_id:str,file_id:str,store:Store,page:Page=1,page_size:Five=5):
    return AnalysisPlanService(store).list(project_id,file_id,page,page_size)


@router.get('/projects/{project_id}/files/{file_id}/analysis-plans/{plan_id}',response_model=ConfirmedSourceRequirementPlan | ConfirmedRequirementPlan | ConfirmedModernPlan | ConfirmedResearchPlan | ConfirmedPlan)
def confirmed(project_id:str,file_id:str,plan_id:str,store:Store):
    return AnalysisPlanService(store).get_plan(project_id,file_id,plan_id)


@router.post('/projects/{project_id}/analysis-plans',response_model=TaskView,status_code=202)
def create_project_requirement(project_id:str,request:SourceRequirementCreateRequest | RequirementCreateRequest,response:Response,store:Store,idempotency_key:Key):
    if request.schema_version!=5:raise StorageError('task_input_invalid','新计划须使用来源确认合同v5。',422)
    task,status=create_requirement(AnalysisPlanService(store),project_id,request,idempotency_key)
    response.status_code=status
    return task


@router.post('/tasks/{task_id}/analysis-plan/continuations',status_code=202)
def continue_plan(task_id:str,request:ContinuationRequest,response:Response,store:Store,idempotency_key:Key):
    result,status=continue_requirement(AnalysisPlanService(store),task_id,request,idempotency_key)
    response.status_code=status
    return result


@router.post('/tasks/{task_id}/analysis-plan/source-decisions',response_model=TaskView,status_code=202)
def source_decision(task_id:str,request:SourceDecisionRequest,response:Response,store:Store,idempotency_key:Key):
    decision=AnalysisPlanDecisionRequest.model_validate(dict(operation='revise',resolutions={},**request.model_dump(mode='json')),strict=True)
    task,status=AnalysisPlanService(store).decide(task_id,decision,idempotency_key)
    response.status_code=status
    return task
