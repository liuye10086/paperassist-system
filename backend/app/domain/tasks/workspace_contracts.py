"""Safe task-center projections, separate from the existing task contract."""
from typing import Literal

from pydantic import BaseModel, Field

from app.domain.tasks.contracts import TaskView
from app.domain.tasks.wait_contracts import WaitView


class TaskSource(BaseModel):
    file_id: str
    filename: str
    analysis_run_id: str
    is_current: bool


class TaskListItem(BaseModel):
    task: TaskView
    source: TaskSource


class TaskListPage(BaseModel):
    project_id: str
    items: list[TaskListItem]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=50)


class FigureArtifact(BaseModel):
    title: str
    caption: str
    download_url: str


class ExplanationSection(BaseModel):
    key: str
    title: str
    text: str


class ExplanationArtifact(BaseModel):
    sections: list[ExplanationSection]
    limitations: list[str]


class ReportArtifact(BaseModel):
    filename: str
    download_url: str


class TaskArtifacts(BaseModel):
    figure: FigureArtifact | None = None
    explanation: ExplanationArtifact | None = None
    report: ReportArtifact | None = None


class TaskWorkspace(BaseModel):
    task: TaskView
    source: TaskSource
    wait: WaitView | None
    allowed_actions: list[Literal['resume', 'retry']]
    artifacts: TaskArtifacts
