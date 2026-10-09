"""Versioned inputs and safe task projections, independent of queue providers."""
from datetime import timezone
from typing import Annotated, Literal

from app.domain.tasks.errors import ErrorCategory, RetryReason

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, model_validator


TaskType = Literal['boxplot', 'explanation', 'word_report']
UTCDateTime = Annotated[AwareDatetime, AfterValidator(lambda value: value.astimezone(timezone.utc))]
TaskStatus = Literal['queued', 'running', 'waiting_input', 'waiting_confirmation', 'succeeded', 'failed']
TaskPhase = Literal['parse', 'plan', 'compute', 'search', 'interpret', 'write', 'export', 'verify']
TaskReason = Literal['input_required', 'confirmation_required', 'submission_unknown', 'budget_exceeded',
                     'execution_failed', 'retry_requested', 'input_provided', 'confirmation_received']
DisplayStatus = Literal['queued', 'parsing', 'analyzing', 'computing', 'searching', 'generating_document',
                        'waiting_input', 'waiting_confirmation', 'succeeded', 'failed']


def display_status(status: TaskStatus, phase: TaskPhase) -> DisplayStatus:
    if status != 'running':
        return status
    return {'parse': 'parsing', 'plan': 'analyzing', 'interpret': 'analyzing', 'verify': 'analyzing',
            'compute': 'computing', 'search': 'searching', 'write': 'generating_document',
            'export': 'generating_document'}[phase]


class TaskCreateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    task_type: TaskType
    external_processing: dict | None = None
    file_id: str = Field(min_length=1, max_length=64, pattern=r'^\S+$')
    analysis_run_id: str = Field(min_length=1, max_length=64, pattern=r'^\S+$')
    expected_revision: int = Field(strict=True, ge=1, le=2_147_483_647)
    figure_id: str | None = Field(default=None, min_length=1, max_length=64, pattern=r'^\S+$')
    explanation_id: str | None = Field(default=None, min_length=1, max_length=64, pattern=r'^\S+$')

    @model_validator(mode='after')
    def validate_source_shape(self):
        if bool(self.figure_id) != (self.task_type in ('explanation', 'word_report')):
            raise ValueError('This task type requires its exact figure input.')
        if bool(self.explanation_id) != (self.task_type == 'word_report'):
            raise ValueError('Only Word export requires an explanation input.')
        return self


class InputVersion(BaseModel):
    setup_revision: int
    output_language: Literal['zh-CN']


class TaskView(BaseModel):
    id: str
    origin: Literal['unified', 'legacy'] = 'unified'
    project_id: str
    task_type: TaskType
    status: TaskStatus
    phase: TaskPhase
    display_status: DisplayStatus
    revision: int | None
    current_attempt: int | None
    retry_count: int | None = Field(default=0, strict=True, ge=0, le=3)
    reason_code: TaskReason | None
    created_at: UTCDateTime
    updated_at: UTCDateTime | None
    input_version: InputVersion
    result_report_id: str | None = None
    result_explanation_id: str | None = None
    result_figure_id: str | None = None
    error_code: str | None = None

    @model_validator(mode='after')
    def metadata_matches_origin(self):
        values = (self.revision, self.current_attempt, self.retry_count, self.updated_at)
        if self.origin == 'legacy' and any(value is not None for value in values):
            raise ValueError('Historical execution metadata was not recorded.')
        if self.origin == 'unified' and any(value is None for value in values):
            raise ValueError('Unified execution metadata is required.')
        return self


class TaskEventView(BaseModel):
    seq: int
    task_revision: int
    event_type: Literal['created', 'started', 'phase_changed', 'waiting', 'succeeded', 'failed', 'requeued', 'deferred']
    status: TaskStatus
    phase: TaskPhase
    reason_code: TaskReason | None
    created_at: UTCDateTime

    error_code: str | None = None
    error_category: ErrorCategory | None = None
    retry_reason: RetryReason | None = None
    retry_count: int | None = Field(default=None, strict=True, ge=0, le=3)
    retry_delay_seconds: Literal[10, 30, 90] | None = None


class TaskEventPage(BaseModel):
    task_id: str
    items: list[TaskEventView]
    next_cursor: int
    has_more: bool
