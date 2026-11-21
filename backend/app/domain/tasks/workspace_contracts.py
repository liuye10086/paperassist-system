from app.domain.bio_insights.task_contracts import INSIGHT_TASKS
"""Safe task-center projections, separate from the existing task contract."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator, model_serializer
from app.domain.analysis_sources import AnyDatasetAnalysisSource
from app.domain.research_results.contracts import ResearchReportRequest

from app.domain.tasks.contracts import TaskView
from app.domain.tasks.wait_contracts import WaitView


class TaskSource(BaseModel):
    model_config = ConfigDict(extra='forbid')
    dataset_source: AnyDatasetAnalysisSource | None = None
    material_versions: list[dict] | None = None
    continuation_task_id: str | None = None

    @model_serializer(mode='wrap')
    def serialize_source(self, handler):
        value = handler(self)
        if self.dataset_source is None:
            value.pop('dataset_source', None)
        if self.material_versions is None:value.pop('material_versions',None)
        if self.continuation_task_id is None:value.pop('continuation_task_id',None)
        return value

    file_id: str | None
    filename: str
    analysis_run_id: str | None
    is_current: bool


class TaskListItem(BaseModel):
    task: TaskView
    source: TaskSource

    @model_validator(mode='after')
    def source_matches_task(self):
        if self.source.file_id is None and not (self.task.task_type in ('bio_cloud_run','literature_search','literature_assistance','manuscript_draft','manuscript_docx','pdf_export', 'layout_docx','manuscript_writing','journal_recommendation', 'journal_format_check', 'journal_adaptation', 'review_round_plan', 'review_revision', 'review_document_export', 'bio_analysis', 'bio_annotation', 'bio_figure', 'research_figure', 'research_report', 'reader_report_narrative', 'research_fact_draft','delivery_package', *INSIGHT_TASKS) or self.task.task_type=='analysis_plan' and self.task.input_version.workflow_version in ('analysis_plan_v4','analysis_plan_v5') and self.task.input_version.source is None):
            raise ValueError('Only a material requirement may lack a source file')
        if (self.task.task_type in ('bio_cloud_run','parse_file','extract_dataset','prepare_dataset', 'review_ocr', 'analysis_plan', 'analysis_recommendation', 'collection_word_report', 'statistics_compute', 'literature_search', 'literature_assistance', 'manuscript_draft', 'manuscript_docx', 'pdf_export', 'layout_docx', 'manuscript_writing', 'school_template_parse', 'school_rule_suggestion', 'journal_recommendation', 'journal_format_check', 'journal_adaptation', 'review_round_plan', 'review_revision', 'review_document_export', 'bio_import', 'bio_analysis', 'bio_annotation', 'bio_figure', 'research_figure', 'research_report', 'reader_report_narrative', 'research_fact_draft','delivery_package', *INSIGHT_TASKS)) != (self.source.analysis_run_id is None):
            raise ValueError('Task source must match its input type.')
        return self


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
    reader_export: dict | None = None
    reader_report: dict | None = None
    members: list[dict] | None = None

    @model_serializer(mode='wrap')
    def omit_reader_fields(self, handler):
        value=handler(self)
        for key in ('reader_export','reader_report','members'):
            if getattr(self,key) is None:value.pop(key,None)
        return value


class TaskArtifacts(BaseModel):
    reader_export: dict | None = None
    bio_cloud: dict | None = None
    bio_insights: dict | None = None
    bio_reader_report_context_id: str | None = None
    bio_reader_report_request: ResearchReportRequest | None = None
    research_results: dict | None = None
    bioinformatics: dict | None = None
    school_rule_suggestion: dict | None = None
    review: dict | None = None
    manuscript: dict | None = None
    literature: dict | None = None
    literature_assistance: dict | None = None
    analysis: dict | None = None
    figure: FigureArtifact | None = None
    explanation: ExplanationArtifact | None = None
    report: ReportArtifact | None = None
    dataset: ReportArtifact | None = None
    ocr_review: ReportArtifact | None = None

    @model_serializer(mode='wrap')
    def serialize_artifacts(self, handler):
        core_artifacts = {'figure', 'explanation', 'report'}
        return {
            name: value for name, value in handler(self).items()
            if value is not None or name in core_artifacts
        }


class TaskWorkspace(BaseModel):
    task: TaskView
    source: TaskSource
    wait: WaitView | None
    allowed_actions: list[Literal['resume', 'retry', 'approve', 'revise', 'cancel']]
    artifacts: TaskArtifacts
    verification_failure: dict | None = None

    @model_serializer(mode="wrap")
    def omit_failure(self,handler):
        value=handler(self)
        if self.verification_failure is None: value.pop("verification_failure")
        return value

    @model_validator(mode='after')
    def source_matches_task(self):
        if self.source.file_id is None and not (self.task.task_type in ('bio_cloud_run','literature_search','literature_assistance','manuscript_draft','manuscript_docx','pdf_export', 'layout_docx','manuscript_writing','journal_recommendation', 'journal_format_check', 'journal_adaptation', 'review_round_plan', 'review_revision', 'review_document_export', 'bio_analysis', 'bio_annotation', 'bio_figure', 'research_figure', 'research_report', 'reader_report_narrative', 'research_fact_draft','delivery_package', *INSIGHT_TASKS) or self.task.task_type=='analysis_plan' and self.task.input_version.workflow_version in ('analysis_plan_v4','analysis_plan_v5') and self.task.input_version.source is None):
            raise ValueError('Only a material requirement may lack a source file')
        if (self.task.task_type in ('bio_cloud_run','parse_file','extract_dataset','prepare_dataset', 'review_ocr', 'analysis_plan', 'analysis_recommendation', 'collection_word_report', 'statistics_compute', 'literature_search', 'literature_assistance', 'manuscript_draft', 'manuscript_docx', 'pdf_export', 'layout_docx', 'manuscript_writing', 'school_template_parse', 'school_rule_suggestion', 'journal_recommendation', 'journal_format_check', 'journal_adaptation', 'review_round_plan', 'review_revision', 'review_document_export', 'bio_import', 'bio_analysis', 'bio_annotation', 'bio_figure', 'research_figure', 'research_report', 'reader_report_narrative', 'research_fact_draft','delivery_package', *INSIGHT_TASKS)) != (self.source.analysis_run_id is None):
            raise ValueError('Task source must match its input type.')
        return self
