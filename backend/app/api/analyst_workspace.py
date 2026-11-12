"""Progress and publication endpoints for an analyst's assigned project."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.customer_workspace import FeedbackView
from app.api.dependencies import Store
from app.auth.permissions import PROJECT_PATH
from app.domain.analyst_workspace import AnalystWorkspace


router = APIRouter(prefix=PROJECT_PATH + '/analyst-workspace', tags=['分析员工作台'])


class AssignedWrite(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)
    assignment_revision: int = Field(ge=1, le=2**63 - 1)


class ProgressInput(AssignedWrite):
    requirement_version_id: str = Field(min_length=1, max_length=128, pattern=r'^[^\x00]+$')
    status: Literal['analyzing', 'needs_materials']
    note: str | None = Field(default=None, max_length=4000, pattern=r'^[^\x00]*$')


class PublishInput(AssignedWrite):
    snapshot_id: str = Field(min_length=1, max_length=128, pattern=r'^[^\x00]+$')
    title: str = Field(min_length=1, max_length=200, pattern=r'^[^\x00]+$')


class RequirementView(BaseModel):
    id: str
    version: int


class PublicationView(BaseModel):
    id: str
    title: str
    published_at: datetime


class PublicationFeedbackView(PublicationView):
    feedback: list[FeedbackView]


class AnalystWorkspaceView(BaseModel):
    assignment_revision: int
    requirement: RequirementView | None
    status: Literal['draft', 'assigned', 'analyzing', 'needs_materials', 'delivered']
    note: str | None
    feedback: list[FeedbackView]
    publications: list[PublicationFeedbackView]


@router.get('', response_model=AnalystWorkspaceView)
def read(project_id: str, store: Store):
    return AnalystWorkspace(store).read(project_id)


@router.patch('/progress', response_model=AnalystWorkspaceView)
def update_progress(project_id: str, request: ProgressInput, store: Store):
    return AnalystWorkspace(store).update_progress(project_id, request)


@router.post('/publish', response_model=PublicationView, status_code=201)
def publish(project_id: str, request: PublishInput, store: Store, response: Response):
    result, response.status_code = AnalystWorkspace(store).publish(project_id, request)
    return result
