"""Versioned inputs and safe task projections, independent of queue providers."""
from datetime import timezone
from typing import Annotated, Literal

from app.domain.analysis_sources import DatasetAnalysisSource, AnyDatasetAnalysisSource
from app.domain.ocr_review.contracts import OcrReviewInputVersion
from app.domain.tasks.errors import ErrorCategory, RetryReason

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, model_validator


TaskType = Literal['boxplot', 'explanation', 'word_report', 'parse_file', 'extract_dataset', 'prepare_dataset', 'review_ocr', 'analysis_plan', 'analysis_recommendation', 'figure_projection', 'figure_workbench', 'figure_explanation', 'collection_word_report', 'statistics_compute']
UTCDateTime = Annotated[AwareDatetime, AfterValidator(lambda value: value.astimezone(timezone.utc))]
TaskStatus = Literal['queued', 'running', 'waiting_input', 'waiting_confirmation', 'succeeded', 'failed']
TaskPhase = Literal['parse', 'plan', 'compute', 'search', 'interpret', 'write', 'export', 'verify']
TaskReason = Literal['input_required', 'confirmation_required', 'submission_unknown', 'budget_exceeded',
                     'execution_failed', 'retry_requested', 'input_provided', 'confirmation_received', 'observation_expired']
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
    task_type: Literal['boxplot', 'explanation', 'word_report']
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
    model_config = ConfigDict(extra='forbid')
    setup_revision: int
    output_language: Literal['zh-CN', 'en']


class DatasetAnalysisInputVersion(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', frozen=True)
    kind: Literal['dataset_analysis']
    setup_revision: int = Field(strict=True, ge=1, le=2_147_483_647)
    output_language: Literal['zh-CN', 'en']
    source: AnyDatasetAnalysisSource


class CollectionInputVersion(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', frozen=True)
    kind: Literal['report_collection']
    collection_version_id: str = Field(min_length=1, max_length=64)
    export_revision: int = Field(strict=True, ge=1)
    output_language: Literal['zh-CN', 'en']
    workflow_version: Literal['collection_word_report_v1']


class PreparationInputVersion(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', frozen=True)
    kind: Literal['dataset_preparation']
    source: AnyDatasetAnalysisSource
    workflow_version: Literal['dataset_preparation_v1', 'dataset_preparation_v2', 'dataset_preparation_v3']

    @model_validator(mode='after')
    def preparation_source_kind(self):
        expected = 'dataset_version' if self.workflow_version == 'dataset_preparation_v1' else 'prepared_dataset_version'
        if self.source.kind != expected:
            raise ValueError('Preparation workflow and source differ')
        return self


class AnalysisPlanInputVersion(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', frozen=True)
    kind: Literal['analysis_plan']
    source: AnyDatasetAnalysisSource | None
    workflow_version: Literal['analysis_plan_v1', 'analysis_plan_v2', 'analysis_plan_v3', 'analysis_plan_v4', 'analysis_plan_v5']

    @model_validator(mode='after')
    def require_legacy_source(self):
        if self.source is None and self.workflow_version not in ('analysis_plan_v4','analysis_plan_v5'):
            raise ValueError('Only a v4 material request may lack a computational source')
        return self


class RecommendationInputVersion(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', frozen=True)
    kind: Literal['analysis_recommendation']
    source: AnyDatasetAnalysisSource
    workflow_version: Literal['analysis_recommendation_v1','analysis_recommendation_v2','analysis_recommendation_v3','analysis_recommendation_v4','analysis_recommendation_v5']


class ParseInputVersion(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    kind: Literal['parse_file']
    parse_id: str = Field(min_length=1, max_length=64)
    source_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    parser_version: Literal['openpyxl-3.1.5-preview-v1', 'openxml-docx-v1', 'pdfplumber-0.11.10-text-v1', 'pdfplumber-0.11.10-evidence-v2', 'rapidocr-3.10.0-ppocrv6-small-v1']


class StructureInputVersion(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    kind: Literal['excel_structure']
    structure_id: str = Field(min_length=1, max_length=64)
    source_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    parser_version: Literal['openpyxl-3.1.5-structure-v1']


class StatisticsInputVersion(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', frozen=True)
    kind: Literal['statistics_compute']
    setup_revision: int = Field(strict=True, ge=1)
    output_language: Literal['zh-CN', 'en']
    source: AnyDatasetAnalysisSource | None
    analysis_plan_id: str | None
    workflow_version: Literal['statistics_compute_v1']


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
    input_version: StatisticsInputVersion | CollectionInputVersion | RecommendationInputVersion | AnalysisPlanInputVersion | OcrReviewInputVersion | PreparationInputVersion | DatasetAnalysisInputVersion | InputVersion | ParseInputVersion | StructureInputVersion
    result_analysis_run_id: str | None = None
    execution_receipt: dict | None = None
    result_report_id: str | None = None
    result_explanation_id: str | None = None
    result_figure_id: str | None = None
    error_code: str | None = None

    @model_validator(mode='after')
    def metadata_matches_origin(self):
        if (self.task_type == 'statistics_compute') != isinstance(self.input_version, StatisticsInputVersion):
            raise ValueError('Input version must match statistics task type.')
        if (self.task_type == 'parse_file') != isinstance(self.input_version, ParseInputVersion):
            raise ValueError('Input version must match task type.')
        if (self.task_type == 'extract_dataset') != isinstance(self.input_version, StructureInputVersion):
            raise ValueError('Input version must match structure task type.')
        if (self.task_type == 'prepare_dataset') != isinstance(self.input_version, PreparationInputVersion):
            raise ValueError('Input version must match preparation task type.')
        if (self.task_type == 'analysis_plan') != isinstance(self.input_version, AnalysisPlanInputVersion):
            raise ValueError('Input version must match analysis plan task type.')
        if (self.task_type == 'analysis_recommendation') != isinstance(self.input_version, RecommendationInputVersion):
            raise ValueError('Input version must match recommendation type.')
        if (self.task_type == 'review_ocr') != isinstance(self.input_version, OcrReviewInputVersion):
            raise ValueError('Input version must match OCR review task type.')
        if (self.task_type == 'collection_word_report') != isinstance(self.input_version, CollectionInputVersion):
            raise ValueError('Input version must match collection task type.')
        if self.task_type in ('figure_projection', 'figure_workbench', 'figure_explanation') and not isinstance(self.input_version, DatasetAnalysisInputVersion):
            raise ValueError('Configured figures require a frozen dataset source.')
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
