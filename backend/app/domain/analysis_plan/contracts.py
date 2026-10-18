"""Strict review and persisted state contracts; no client check conclusions."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator
from app.domain.analysis import AnalysisSelection, SelectionCheck
from app.domain.analysis_sources import PreparedDatasetAnalysisSource, PreparedDatasetAnalysisSourceV2, PreparedDatasetAnalysisSourceV3
from app.domain.dataset_preparation.contracts import PreparationUnit
from app.domain.tasks.contracts import AnalysisPlanInputVersion, TaskView
from app.domain.analysis_plan.research import ResearchRequest
from app.domain.correlation.contracts import CorrelationSelection, RecommendationReference
from app.domain.comparison.contracts import ComparisonSelection
from app.domain.regression.contracts import RegressionSelection
from app.domain.roc.contracts import RocSelection
from app.domain.survival.contracts import SurvivalSelection

ModernSelection = RegressionSelection | RocSelection | SurvivalSelection | ComparisonSelection | CorrelationSelection | AnalysisSelection

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
        'invalid_column','sheet_not_found','invalid_analysis_selection','correlation_sample_size',
        'correlation_input_limit','correlation_constant','correlation_near_constant','correlation_invalid_input',
        'comparison_sample_size','comparison_input_limit','comparison_constant','comparison_near_constant',
        'comparison_invalid_input','pair_id_missing','pair_id_duplicate','pair_id_type','groups_missing','group_not_selected',
        'numeric_input_limit','numeric_invalid_input','numeric_sample_size','numeric_rank','numeric_constant','numeric_perfect_fit',
        'numeric_descriptive_limit','numeric_row_limit','numeric_effect_limit','numeric_input_bytes_limit',
        'numeric_output_limit','numeric_output_missing','numeric_output_invalid','numeric_timeout_invalid',
        'numeric_separation_check','numeric_separation','numeric_convergence','numeric_unstable','numeric_overflow',
        'numeric_failure','numeric_timeout','numeric_encoding','numeric_id_missing','numeric_id_duplicate','numeric_roles_missing']
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
    schema_version: Literal[3] | None = None
    recommendation_ref: RecommendationReference | None = None
    dataset_id: str = Field(min_length=1,max_length=64)
    expected_setup_revision: int = Field(ge=0,lt=2147483647)
    selection: ModernSelection
    research_request: ResearchRequest | None = None

    @model_validator(mode='before')
    @classmethod
    def research_cannot_be_null(cls, value):
        if isinstance(value, dict) and 'research_request' in value and value['research_request'] is None:
            raise ValueError('Research request must be a complete object.')
        if isinstance(value, dict):
            modern = value.get('schema_version') == 3 and type(value.get('schema_version')) is int
            if ('schema_version' in value and not modern or not modern and ('recommendation_ref' in value or value.get('selection', {}).get('task_type') in ('correlation','group_comparison','regression','roc','survival')) or modern and not value.get('research_request')):
                raise ValueError('Version 3 requires explicit research declarations.')
        return value

    @model_serializer(mode='wrap')
    def legacy_shape(self, handler):
        value = handler(self)
        if self.research_request is None: value.pop('research_request')
        if 'source_resolution' in value and self.source_resolution is None:value.pop('source_resolution')
        if hasattr(self, 'schema_version') and self.schema_version is None:
            value.pop('schema_version'); value.pop('recommendation_ref')
        return value


class AnalysisPlanDecisionRequest(StrictModel):
    operation: Literal['approve','revise']
    expected_task_revision: int = Field(ge=1,lt=2147483647)
    input_version: AnalysisPlanInputVersion
    checkpoint_id: str = Field(min_length=1,max_length=64)
    wait_id: str = Field(min_length=1,max_length=64)
    plan_revision: int = Field(ge=1,lt=2147483647)
    resolutions: dict[str,str]
    selection: ModernSelection | None = None
    research_request: ResearchRequest | None = None
    source_resolution: dict | None = None

    @model_validator(mode='before')
    @classmethod
    def operation_shape(cls,value):
        if isinstance(value,dict):
            version=value.get('input_version')
            v4=(version.get('workflow_version') if isinstance(version,dict) else getattr(version,'workflow_version',None)) in ('analysis_plan_v4','analysis_plan_v5')
            if 'source_resolution' in value:
                from app.domain.analysis_plan.requirements import SourceResolution
                if (version.get('workflow_version') if isinstance(version,dict) else getattr(version,'workflow_version',None))!='analysis_plan_v5':raise ValueError('Source decisions require v5.')
                SourceResolution.model_validate(value['source_resolution'],strict=True)
                if 'selection' in value or 'research_request' in value:raise ValueError('Source clarification is independent of research revision.')
            if value.get('operation')=='approve' and ('selection' in value or 'research_request' in value or 'source_resolution' in value):
                raise ValueError('Approval cannot change the displayed selection.')
            if 'research_request' in value and value['research_request'] is None:
                raise ValueError('Research request must be a complete object.')
            if value.get('operation')=='revise' and 'selection' in value and value['selection'] is None and not v4:
                raise ValueError('Selection revision must be a complete object.')
            if value.get('operation')=='revise' and (
                    value.get('selection') is None and value.get('research_request') is None and not(v4 and 'selection' in value) and value.get('source_resolution') is None or value.get('resolutions')):
                raise ValueError('Revision requires selection or research request and empty resolutions.')
        return value

    @model_serializer(mode='wrap')
    def legacy_shape(self, handler):
        value = handler(self)
        if self.research_request is None: value.pop('research_request')
        if 'source_resolution' in value and self.source_resolution is None:value.pop('source_resolution')
        if hasattr(self, 'schema_version') and self.schema_version is None:
            value.pop('schema_version'); value.pop('recommendation_ref')
        return value


class AnalysisPlanSnapshot(StrictModel):
    schema_version: Literal[1]
    kind: Literal['analysis_plan']
    workflow_version: Literal['analysis_plan_v1']
    rules_version: Literal['analysis_plan_rules_v1']
    project_id: str
    filename: str
    source: PreparedDatasetAnalysisSourceV3 | PreparedDatasetAnalysisSourceV2 | PreparedDatasetAnalysisSource
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
    source: PreparedDatasetAnalysisSourceV3 | PreparedDatasetAnalysisSourceV2 | PreparedDatasetAnalysisSource
    selection: AnalysisSelection
    check: AnalysisPlanCheck
    resolutions: dict[str,str]
    plan_revision: int = Field(ge=1)
    setup_revision: int = Field(ge=1)
    created_at: str


class ConfirmedPlan(PlanContent):
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class ResearchPlanCheck(AnalysisPlanCheck):
    rules_version: Literal['analysis_plan_rules_v2']
    research_missing: list[Literal['population', 'study_design', 'observation_unit',
        'observation_structure', 'relationship_description']]


class ResearchPlanSnapshot(AnalysisPlanSnapshot):
    schema_version: Literal[2]
    workflow_version: Literal['analysis_plan_v2']
    rules_version: Literal['analysis_plan_rules_v2']
    research_request: ResearchRequest


class ResearchPlanState(AnalysisPlanState):
    check: ResearchPlanCheck | None = None
    research_request: ResearchRequest


class ResearchPlanContent(PlanContent):
    schema_version: Literal[2]
    workflow_version: Literal['analysis_plan_v2']
    rules_version: Literal['analysis_plan_rules_v2']
    check: ResearchPlanCheck
    research_request: ResearchRequest


class ConfirmedResearchPlan(ResearchPlanContent):
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class ModernPlanCheck(ResearchPlanCheck):
    rules_version: Literal['analysis_plan_rules_v3']
    selected_fields: list[SelectedField] = Field(max_length=10)
    research_missing: list[Literal['population', 'study_design', 'observation_unit',
        'observation_structure', 'relationship_description', 'independent_observations',
        'relationship_form', 'inference_assumptions_confirmed','independent_units','distribution','inference_confirmed',
        'outcome_column','covariates','positive','negative','direction','score_source','score_version','formation','evaluation_role',
        'id_column','time_column','status_column','event','censored','time_unit','time_origin','noninformative_censoring',
        'independence_confirmed','covariate_reference','covariate_levels','score_column','score_kind','outcome_time','groups']]


class ModernPlanSnapshot(ResearchPlanSnapshot):
    schema_version: Literal[3]
    workflow_version: Literal['analysis_plan_v3']
    rules_version: Literal['analysis_plan_rules_v3']
    selection: ModernSelection
    recommendation_ref: RecommendationReference | None


class ModernPlanState(ResearchPlanState):
    selection: ModernSelection
    check: ModernPlanCheck | None = None
    recommendation_ref: RecommendationReference | None


class ModernPlanContent(ResearchPlanContent):
    schema_version: Literal[3]
    workflow_version: Literal['analysis_plan_v3']
    rules_version: Literal['analysis_plan_rules_v3']
    selection: ModernSelection
    check: ModernPlanCheck
    recommendation_ref: RecommendationReference | None


class ConfirmedModernPlan(ModernPlanContent):
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


def snapshot_model(value):
    if value.get('schema_version')==5:
        from app.domain.analysis_plan.requirements import SourceRequirementSnapshot
        return SourceRequirementSnapshot
    if value.get('schema_version') == 4:
        from app.domain.analysis_plan.requirements import RequirementSnapshot
        return RequirementSnapshot
    if value.get('schema_version') == 3: return ModernPlanSnapshot
    return ResearchPlanSnapshot if value.get('schema_version') == 2 else AnalysisPlanSnapshot


def state_model(value):
    if value.get('input_version',{}).get('workflow_version')=='analysis_plan_v5':
        from app.domain.analysis_plan.requirements import SourceRequirementState
        return SourceRequirementState
    if value.get('input_version', {}).get('workflow_version') == 'analysis_plan_v4':
        from app.domain.analysis_plan.requirements import RequirementState
        return RequirementState
    if value.get('input_version', {}).get('workflow_version') == 'analysis_plan_v3': return ModernPlanState
    return ResearchPlanState if value.get('input_version', {}).get('workflow_version') == 'analysis_plan_v2' else AnalysisPlanState


def content_model(value):
    if value.get('schema_version')==5:
        from app.domain.analysis_plan.requirements import SourceRequirementPlanContent
        return SourceRequirementPlanContent
    if value.get('schema_version') == 4:
        from app.domain.analysis_plan.requirements import RequirementPlanContent
        return RequirementPlanContent
    if value.get('schema_version') == 3: return ModernPlanContent
    return ResearchPlanContent if value.get('schema_version') == 2 else PlanContent


class AnalysisPlanReview(StrictModel):
    task: TaskView
    source: PreparedDatasetAnalysisSourceV3 | PreparedDatasetAnalysisSourceV2 | PreparedDatasetAnalysisSource
    checkpoint_id: str
    wait_id: str | None
    plan_revision: int
    input_version: AnalysisPlanInputVersion
    selection: ModernSelection
    check: ModernPlanCheck | ResearchPlanCheck | AnalysisPlanCheck | None
    resolutions: dict[str,str]
    result: ConfirmedModernPlan | ConfirmedResearchPlan | ConfirmedPlan | None
    research_request: ResearchRequest | None = None
    recommendation_ref: RecommendationReference | None = None

    @model_serializer(mode='wrap')
    def legacy_shape(self, handler):
        value = handler(self)
        if self.research_request is None: value.pop('research_request')
        if self.input_version.workflow_version != 'analysis_plan_v3': value.pop('recommendation_ref')
        return value


class AnalysisPlanPage(StrictModel):
    items: list[AnalysisPlanReview]
    total: int
    page: int
    page_size: Literal[5]
