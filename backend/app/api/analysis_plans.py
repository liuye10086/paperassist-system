"""Explicit plan creation and decisions; owner-scoped GETs are read-only."""
from fastapi import APIRouter,Response
from app.api.dataset_preparation import Store,Key,Page,Five
from app.domain.tasks.contracts import TaskView
from app.domain.analysis_plan.contracts import (AnalysisPlanCreateRequest,AnalysisPlanDecisionRequest,
    AnalysisPlanReview,AnalysisPlanPage,ConfirmedPlan)
from app.domain.analysis_plan.service import AnalysisPlanService

router=APIRouter(prefix='/api/v1',tags=['分析计划'])


@router.post('/projects/{project_id}/files/{file_id}/analysis-plans',response_model=TaskView,status_code=202)
def create(project_id:str,file_id:str,request:AnalysisPlanCreateRequest,response:Response,store:Store,idempotency_key:Key):
    task,status=AnalysisPlanService(store).create(project_id,file_id,request,idempotency_key)
    response.status_code=status
    return task


@router.get('/tasks/{task_id}/analysis-plan',response_model=AnalysisPlanReview)
def review(task_id:str,store:Store):
    return AnalysisPlanService(store).get_task(task_id)


@router.post('/tasks/{task_id}/analysis-plan/decisions',response_model=TaskView,status_code=202)
def decide(task_id:str,request:AnalysisPlanDecisionRequest,response:Response,store:Store,idempotency_key:Key):
    task,status=AnalysisPlanService(store).decide(task_id,request,idempotency_key)
    response.status_code=status
    return task


@router.get('/projects/{project_id}/files/{file_id}/analysis-plans',response_model=AnalysisPlanPage)
def list_plans(project_id:str,file_id:str,store:Store,page:Page=1,page_size:Five=5):
    return AnalysisPlanService(store).list(project_id,file_id,page,page_size)


@router.get('/projects/{project_id}/files/{file_id}/analysis-plans/{plan_id}',response_model=ConfirmedPlan)
def confirmed(project_id:str,file_id:str,plan_id:str,store:Store):
    return AnalysisPlanService(store).get_plan(project_id,file_id,plan_id)
