"""Progress and publication endpoints for an analyst's assigned project."""

from datetime import datetime
from functools import partial
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.customer_workspace import FeedbackView
from app.api.dependencies import Store
from app.auth.permissions import PROJECT_PATH
from app.domain.analyst_workspace import AnalystWorkspace
from app.domain.bioinformatics.analysis_contracts import Hash, Identifier
from app.domain.delivery_packages.native_artifacts import native_png, save_native_artifact, single_cell_word


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


class SingleCellWordInput(AssignedWrite):
    kind: Literal['single_cell_word']
    version_id: Identifier
    annotation_version_id: Identifier | None = None


class BulkWordInput(AssignedWrite):
    kind: Literal['bulk_word']
    artifact_id: Hash
    facts_digest: Hash


class NativeFigureInput(AssignedWrite):
    kind: Literal['single_cell_png', 'bio_figure_png', 'bio_insight_png']
    version_id: Identifier
    member_id: Identifier


NativeArtifactInput = Annotated[SingleCellWordInput | BulkWordInput | NativeFigureInput, Field(discriminator='kind')]


class NativeArtifactView(BaseModel):
    file_id: str
    filename: str
    format: Literal['docx', 'png']
    sha256: str
    size_bytes: int


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


@router.post('/delivery-artifacts', response_model=NativeArtifactView, status_code=201)
def add_delivery_artifact(project_id: str, request: NativeArtifactInput, store: Store, response: Response,
                          idempotency_key: Annotated[str, Header(alias='Idempotency-Key')]):
    if isinstance(request, BulkWordInput):
        from app.api.bulk_workflow import prepared_word_for_delivery

        load = partial(prepared_word_for_delivery, project_id, store, request.artifact_id, request.facts_digest)
    elif isinstance(request, SingleCellWordInput):
        load = partial(single_cell_word, store, project_id, request)
    else:
        load = partial(native_png, store, project_id, request)
    result, response.status_code = save_native_artifact(store, project_id, request, idempotency_key, load)
    return result
