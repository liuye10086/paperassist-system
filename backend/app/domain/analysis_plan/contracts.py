"""Strict review and persisted state contracts; no client check conclusions."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.domain.analysis import AnalysisSelection, SelectionCheck
from app.domain.analysis_sources import PreparedDatasetAnalysisSource
from app.domain.dataset_preparation.contracts import PreparationUnit
from app.domain.tasks.contracts import AnalysisPlanInputVersion, TaskView

WORKFLOW_VERSION='analysis_plan_v1'
RULES_VERSION='analysis_plan_rules_v1'


class StrictModel(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid',allow_inf_nan=False)


class DeclaredUnit(StrictModel):
    status: Literal['unknown','label']
    value: str | None


class SelectedField(StrictModel):
    letter: str
    name: str
    type_counts: dict[str,int]
    missing_count: int = Field(ge=0)
    non_missing_count: int = Field(ge=0)
    prepared_unit: PreparationUnit
    declared_unit: DeclaredUnit
    observed_min: float | None
    observed_max: float | None


class PlanIssue(StrictModel):
    id: str
    code: Literal['unit_conflict','unit_unconfirmed','numeric_precision','outlier','partial_metrics',
        'numeric_type','group_type','no_complete_records','too_many_groups','small_sample','selected_missing',
        'invalid_column','sheet_not_found','invalid_analysis_selection']
    severity: Literal['blocking','warning']
    field: str | None
    count: int = Field(ge=0)
    coordinates: list[str] = Field(max_length=5)
    message: str
    allowed_resolutions: list[Literal['exclude_selected_missing','retain','accept_partial_metrics','unknown','declare_label']]


class AnalysisPlanCheck(StrictModel):
    rules_version: Literal['analysis_plan_rules_v1']
    data_range: str
    row_count: int = Field(ge=1)
    selected_fields: list[SelectedField] = Field(max_length=2)
    selection_check: SelectionCheck | None
    issues: list[PlanIssue]
    limitations: list[str]


class AnalysisPlanCreateRequest(StrictModel):
    dataset_id: str = Field(min_length=1,max_length=64)
    expected_setup_revision: int = Field(ge=0,lt=2147483647)
    selection: AnalysisSelection


class AnalysisPlanDecisionRequest(StrictModel):
    operation: Literal['approve','revise']
    expected_task_revision: int = Field(ge=1,lt=2147483647)
    input_version: AnalysisPlanInputVersion
    checkpoint_id: str = Field(min_length=1,max_length=64)
    wait_id: str = Field(min_length=1,max_length=64)
    plan_revision: int = Field(ge=1,lt=2147483647)
    resolutions: dict[str,str]
    selection: AnalysisSelection | None = None

    @model_validator(mode='before')
    @classmethod
    def operation_shape(cls,value):
        if isinstance(value,dict):
            if value.get('operation')=='approve' and 'selection' in value:
                raise ValueError('Approval cannot change the displayed selection.')
            if value.get('operation')=='revise' and (value.get('selection') is None or value.get('resolutions')):
                raise ValueError('Revision requires a complete selection and empty resolutions.')
        return value


class AnalysisPlanSnapshot(StrictModel):
    schema_version: Literal[1]
    kind: Literal['analysis_plan']
    workflow_version: Literal['analysis_plan_v1']
    rules_version: Literal['analysis_plan_rules_v1']
    project_id: str
    filename: str
    source: PreparedDatasetAnalysisSource
    expected_setup_revision: int = Field(ge=0)
    selection: AnalysisSelection


class AnalysisPlanState(StrictModel):
    input_version: AnalysisPlanInputVersion
    plan_revision: int = Field(ge=1)
    selection: AnalysisSelection
    check: AnalysisPlanCheck | None = None
    resolutions: dict[str,str] = Field(default_factory=dict)
    decision_id: str | None = None
    result_id: str | None = None


class PlanContent(StrictModel):
    schema_version: Literal[1]
    workflow_version: Literal['analysis_plan_v1']
    rules_version: Literal['analysis_plan_rules_v1']
    id: str
    task_id: str
    decision_id: str
    project_id: str
    file_id: str
    source: PreparedDatasetAnalysisSource
    selection: AnalysisSelection
    check: AnalysisPlanCheck
    resolutions: dict[str,str]
    plan_revision: int = Field(ge=1)
    setup_revision: int = Field(ge=1)
    created_at: str


class ConfirmedPlan(PlanContent):
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class AnalysisPlanReview(StrictModel):
    task: TaskView
    source: PreparedDatasetAnalysisSource
    checkpoint_id: str
    wait_id: str | None
    plan_revision: int
    input_version: AnalysisPlanInputVersion
    selection: AnalysisSelection
    check: AnalysisPlanCheck | None
    resolutions: dict[str,str]
    result: ConfirmedPlan | None


class AnalysisPlanPage(StrictModel):
    items: list[AnalysisPlanReview]
    total: int
    page: int
    page_size: Literal[5]
