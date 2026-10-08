"""Owner-scoped, read-only model usage with a public field allowlist."""
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, BeforeValidator, Field

from app.api.tasks import decimal_query_integer
from app.domain.model_usage.service import ModelUsageService

router = APIRouter(prefix='/api/v1', tags=['模型调用与预算'])


def get_request_usage_service(request: Request) -> ModelUsageService:
    return ModelUsageService(request.state.user['id'])


Service = Annotated[ModelUsageService, Depends(get_request_usage_service)]
Page = Annotated[int, Query(ge=1, le=1_000_000), BeforeValidator(decimal_query_integer)]
PageSize = Annotated[int, Query(ge=1, le=50), BeforeValidator(decimal_query_integer)]
Amount = Annotated[int, Field(strict=True, ge=0)]


class BudgetView(BaseModel):
    scope_type: Literal['user', 'project', 'task']
    limit_micro_usd: Amount | None
    revision: Annotated[int, Field(strict=True, ge=0)]
    estimated_micro_usd: Amount
    reserved_micro_usd: Amount
    available_micro_usd: Annotated[int, Field(strict=True)] | None
    exceeded: bool


class PublicCall(BaseModel):
    id: str
    task_type: Literal['boxplot', 'explanation', 'word_report']
    model: str
    status: Literal['reserved', 'submitting', 'submitted', 'submission_unknown', 'completed', 'failed', 'released']
    provider_status: str | None
    usage_status: Literal['pending', 'estimated']
    estimated_cost_micro_usd: Amount | None
    created_at: datetime
    updated_at: datetime


class ProjectUsageView(BaseModel):
    currency: Literal['USD']
    period: Literal['cumulative']
    enforcement_scope: Literal['unified_only']
    user_budget: BudgetView
    project_budget: BudgetView
    estimated_micro_usd: Amount
    reserved_micro_usd: Amount
    pending_count: Annotated[int, Field(strict=True, ge=0)]
    items: list[PublicCall]
    total: Annotated[int, Field(strict=True, ge=0)]
    page: Annotated[int, Field(strict=True, ge=1)]
    page_size: Annotated[int, Field(strict=True, ge=1, le=50)]


class TaskUsageView(ProjectUsageView):
    task_budget: BudgetView


@router.get('/projects/{project_id}/model-usage', response_model=ProjectUsageView)
def project_usage(project_id: str, service: Service, page: Page = 1, page_size: PageSize = 10):
    return service.project_usage(project_id, page=page, page_size=page_size)


@router.get('/tasks/{task_id}/model-usage', response_model=TaskUsageView)
def task_usage(task_id: str, service: Service, page: Page = 1, page_size: PageSize = 10):
    return service.task_usage(task_id, page=page, page_size=page_size)
