"""Customer-only progress, published deliveries and feedback endpoints."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.bio_datasets import Key, Store
from app.api.delivery_packages import attachment
from app.auth.permissions import CUSTOMER_WORKSPACE_PATH, require_customer_role
from app.domain.customer_workspace import CustomerWorkspace


router = APIRouter(prefix=CUSTOMER_WORKSPACE_PATH, tags=['客户工作台'], dependencies=[Depends(require_customer_role)])


class FeedbackInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=4000, pattern=r'^[^\x00]+$')
    snapshot_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=r'^[^\x00]+$')


class FeedbackView(BaseModel):
    id: str
    message: str
    created_at: datetime


class MaterialSubmissionInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)
    requirement_version: int = Field(ge=1, le=2**31 - 1)
    file_ids: list[Annotated[str, Field(min_length=1, max_length=128, pattern=r'^[^\x00]+$')]] = Field(min_length=1, max_length=50)
    note: str | None = Field(default=None, max_length=4000, pattern=r'^[^\x00]*$')

    @field_validator('file_ids')
    @classmethod
    def distinct(cls, value):
        if len(set(value)) != len(value):
            raise ValueError('Duplicate files are not allowed')
        return value


class SubmissionFile(BaseModel):
    id: str
    name: str


class SubmissionView(BaseModel):
    id: str
    requirement_version: int
    file_ids: list[str]
    files: list[SubmissionFile]
    note: str | None
    created_at: datetime


ProgressStatus = Literal['draft', 'pending_assignment', 'assigned', 'analyzing', 'needs_materials', 'materials_submitted',
                         'delivered']


class ProgressView(BaseModel):
    status: ProgressStatus
    requirement_version: int | None
    submitted_at: datetime | None
    updated_at: datetime | None
    note: str | None
    feedback: list[FeedbackView]
    submissions: list[SubmissionView]


class SummaryTarget(BaseModel):
    delivery_id: str | None
    snapshot_id: str | None
    manuscript_id: str | None
    revision: int | None
    round_id: str | None
    item_id: str | None
    template_version_id: str | None
    view: str | None
    mode: Literal['supplement'] | None


class SummaryView(BaseModel):
    project_id: str
    project_type: Literal['research', 'sci', 'thesis']
    kind: str
    actor: Literal['customer', 'analyst', 'admin', 'none']
    step: str
    target: SummaryTarget
    message_key: str
    message_params: dict[str, int | str]
    updated_at: datetime | None


class DeliverySummary(BaseModel):
    id: str
    delivery_id: str
    title: str
    kind: Literal['analysis', 'sci_draft', 'thesis_draft']
    revision: int
    published_at: datetime
    member_count: int


class DeliveryList(BaseModel):
    items: list[DeliverySummary]


class DeliveryMember(BaseModel):
    id: str
    name: str
    format: str
    size_bytes: int
    download_url: str


class DeliveryDetail(DeliverySummary):
    members: list[DeliveryMember]
    package_url: str | None
    feedback: list[FeedbackView]


@router.get('/summary', response_model=SummaryView)
def summary(project_id: str, store: Store):
    return CustomerWorkspace(store).summary(project_id)


@router.get('/progress', response_model=ProgressView)
def progress(project_id: str, store: Store):
    return CustomerWorkspace(store).progress(project_id)


@router.get('/deliveries', response_model=DeliveryList)
def deliveries(project_id: str, store: Store):
    return CustomerWorkspace(store).deliveries(project_id)


@router.get('/deliveries/{snapshot_id}', response_model=DeliveryDetail)
def delivery(project_id: str, snapshot_id: str, store: Store):
    return CustomerWorkspace(store).detail(project_id, snapshot_id)


@router.get('/deliveries/{snapshot_id}/members/{member_id}/download')
def member(project_id: str, snapshot_id: str, member_id: str, store: Store):
    return attachment(*CustomerWorkspace(store).member(project_id, snapshot_id, member_id))


@router.get('/deliveries/{snapshot_id}/download')
def package(project_id: str, snapshot_id: str, store: Store):
    return attachment(*CustomerWorkspace(store).package(project_id, snapshot_id))


@router.post('/feedback', response_model=FeedbackView, status_code=201)
def feedback(project_id: str, request: FeedbackInput, store: Store, idempotency_key: Key, response: Response):
    result, response.status_code = CustomerWorkspace(store).submit_feedback(project_id, request, idempotency_key)
    return result


@router.post('/material-submissions', response_model=SubmissionView, status_code=201)
def submit_materials(project_id: str, request: MaterialSubmissionInput, store: Store, idempotency_key: Key, response: Response):
    result, response.status_code = CustomerWorkspace(store).submit_materials(project_id, request, idempotency_key)
    return result
