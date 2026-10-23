"""Safe waiting projections and explicit, versioned recovery input."""
from typing import Literal
from app.domain.school_templates.contracts import SchoolTemplateInputVersion

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.ocr_review.contracts import OcrReviewInputVersion
from app.domain.literature.contracts import LiteratureInputVersion
from app.domain.literature_assistance.contracts import AssistanceInputVersion
from app.domain.manuscripts.contracts import ManuscriptInputVersion
from app.domain.manuscript_writing.contracts import WritingInputVersion
from app.domain.tasks.contracts import StatisticsInputVersion, CollectionInputVersion, RecommendationInputVersion, AnalysisPlanInputVersion, PreparationInputVersion, DatasetAnalysisInputVersion, InputVersion, ParseInputVersion, StructureInputVersion, UTCDateTime


class StrictInputVersion(InputVersion):
    model_config = ConfigDict(extra='forbid')
    setup_revision: int = Field(strict=True, ge=1, le=2_147_483_647)


class WaitView(BaseModel):
    id: str
    kind: Literal['literature_model_authorization', 'literature_configuration', 'remote_observation', 'budget_confirmation', 'submission_unknown', 'unsupported_input', 'unsupported_confirmation', 'dataset_preparation_confirmation', 'ocr_review_confirmation', 'analysis_plan_confirmation', 'analysis_plan_input', 'figure_projection_confirmation', 'remote_observation']
    status: Literal['open', 'resolved', 'superseded']
    task_revision: int
    input_version: SchoolTemplateInputVersion | WritingInputVersion | ManuscriptInputVersion | AssistanceInputVersion | LiteratureInputVersion | StatisticsInputVersion | CollectionInputVersion | RecommendationInputVersion | AnalysisPlanInputVersion | OcrReviewInputVersion | PreparationInputVersion | DatasetAnalysisInputVersion | InputVersion
    reason_code: str | None
    error_code: str | None
    created_at: UTCDateTime
    resolved_at: UTCDateTime | None


class ResumeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    operation: Literal['resume', 'retry']
    wait_id: str | None = Field(min_length=1, max_length=64, pattern=r'^\S+$')
    expected_task_revision: int = Field(strict=True, ge=1, lt=2_147_483_647)
    input_version: SchoolTemplateInputVersion | WritingInputVersion | ManuscriptInputVersion | AssistanceInputVersion | LiteratureInputVersion | StatisticsInputVersion | CollectionInputVersion | RecommendationInputVersion | AnalysisPlanInputVersion | OcrReviewInputVersion | PreparationInputVersion | DatasetAnalysisInputVersion | StrictInputVersion | ParseInputVersion | StructureInputVersion

    @model_validator(mode='after')
    def wait_matches_operation(self):
        if (self.wait_id is not None) != (self.operation == 'resume'):
            raise ValueError('A waiting generation is required only for resume.')
        return self
