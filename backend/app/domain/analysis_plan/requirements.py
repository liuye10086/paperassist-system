"""Version four local requirements, separate from executable numeric checks."""
from __future__ import annotations
from typing import Literal
from pydantic import Field, model_validator
from app.domain.analysis_plan.contracts import StrictModel, ModernSelection, ModernPlanCheck, ModernPlanContent,AnalysisPlanReview
from app.domain.analysis_plan.research import ResearchRequest, missing_research
from app.domain.correlation.contracts import RecommendationReference
from app.domain.analysis_sources import AnyDatasetAnalysisSource
from app.domain.tasks.contracts import AnalysisPlanInputVersion,TaskView


class RequirementCreateRequest(StrictModel):
    schema_version: Literal[4]
    input_kind: Literal['data','materials']
    file_id: str | None = Field(default=None,min_length=1,max_length=64)
    dataset_id: str | None = Field(default=None,min_length=1,max_length=64)
    expected_setup_revision: int = Field(ge=0,lt=2147483647)
    selection: ModernSelection | None
    research_request: ResearchRequest
    evidence_version_ids: list[str] = Field(default_factory=list,max_length=10)
    recommendation_ref: RecommendationReference | None = None
    origin_recommendation_ref: RecommendationReference | None = None

    @model_validator(mode='before')
    @classmethod
    def exact_version(cls,value):
        if isinstance(value,dict) and type(value.get('schema_version')) is not int:
            raise ValueError('Version must be an integer.')
        return value

    @model_validator(mode='after')
    def boundaries(self):
        if len(set(self.evidence_version_ids))!=len(self.evidence_version_ids) or any(not x or len(x)>64 for x in self.evidence_version_ids):
            raise ValueError('Evidence references must be distinct identifiers.')
        if self.input_kind=='materials':
            if self.file_id is not None or self.dataset_id is not None or self.selection is not None or not self.evidence_version_ids or self.recommendation_ref is not None or self.origin_recommendation_ref is not None:
                raise ValueError('Material requirements cannot manufacture a data source or method.')
        elif not self.file_id or not self.dataset_id:
            raise ValueError('Data requirements must freeze an explicit file and dataset.')
        if self.recommendation_ref is not None and self.origin_recommendation_ref is not None:
            raise ValueError('Active recommendations cannot also be origin-only.')
        return self


class RequirementCheck(StrictModel):
    rules_version: Literal['analysis_plan_rules_v4']
    research_missing: list[str]
    data_check: ModernPlanCheck | None
    limitations: list[str]


def requirement_check(source,selection,research_request,sheet=None,*,schema_version=4,source_resolution=None):
    missing=missing_research(research_request)
    if source is None:missing.insert(0,'source')
    if selection is None:missing.append('selection')
    if schema_version==5 and (source is None or source_resolution is None):missing.append('source_confirmation')
    numeric=None
    if not missing and sheet is not None:
        from app.domain.analysis_plan.checks import build_check
        from app.domain.correlation.contracts import parse_selection
        numeric=build_check(sheet,parse_selection(selection),research_request,schema_version=3)
        missing=list(numeric['research_missing'])
    model=SourceRequirementCheck if schema_version==5 else RequirementCheck
    return model(rules_version=f'analysis_plan_rules_v{schema_version}',research_missing=missing,data_check=numeric,
        limitations=['外部材料仅为来源证据，未由本系统重新计算。','补充资料及采纳候选不等于批准分析计划。']).model_dump(mode='json')


class RequirementSnapshot(StrictModel):
    schema_version: Literal[4]
    kind: Literal['analysis_plan']
    workflow_version: Literal['analysis_plan_v4']
    rules_version: Literal['analysis_plan_rules_v4']
    project_id: str
    filename: str | None
    source: AnyDatasetAnalysisSource | None
    expected_setup_revision: int = Field(ge=0)
    input_kind: Literal['data','materials']
    selection: ModernSelection | None
    research_request: ResearchRequest
    evidence_versions: list[dict] = Field(max_length=10)
    recommendation_ref: RecommendationReference | None
    origin_recommendation_ref: RecommendationReference | None
    parent_requirement_task_id: str | None = None
    request_material: dict


class RequirementState(StrictModel):
    input_version: AnalysisPlanInputVersion
    plan_revision: int = Field(ge=1)
    selection: ModernSelection | None
    research_request: ResearchRequest
    recommendation_ref: RecommendationReference | None
    origin_recommendation_ref: RecommendationReference | None
    check: RequirementCheck | None = None
    resolutions: dict[str,str] = Field(default_factory=dict)
    decision_id: str | None = None
    result_id: str | None = None
    continuation: dict | None = None


class RequirementPlanContent(ModernPlanContent):
    schema_version: Literal[4]
    workflow_version: Literal['analysis_plan_v4']
    rules_version: Literal['analysis_plan_rules_v4']
    check: RequirementCheck
    source: AnyDatasetAnalysisSource
    evidence_versions: list[dict]
    origin_recommendation_ref: RecommendationReference | None


class ConfirmedRequirementPlan(RequirementPlanContent):
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class RequirementReview(StrictModel):
    task: TaskView
    source: AnyDatasetAnalysisSource | None
    checkpoint_id: str
    wait_id: str | None
    plan_revision: int
    input_version: AnalysisPlanInputVersion
    selection: ModernSelection | None
    check: RequirementCheck | None
    resolutions: dict[str,str]
    result: ConfirmedRequirementPlan | None
    research_request: ResearchRequest
    recommendation_ref: RecommendationReference | None
    origin_recommendation_ref: RecommendationReference | None
    input_kind: Literal['data','materials']
    evidence_versions: list[dict]
    continuation: dict | None


class RequirementPage(StrictModel):
    items: list[SourceRequirementReview | RequirementReview | AnalysisPlanReview]
    total: int
    page: int
    page_size: Literal[5]


class ContinuationRequest(StrictModel):
    expected_task_revision: int = Field(ge=1,lt=2147483647)
    input_version: AnalysisPlanInputVersion
    checkpoint_id: str = Field(min_length=1,max_length=64)
    wait_id: str = Field(min_length=1,max_length=64)
    plan_revision: int = Field(ge=1)
    file_id: str = Field(min_length=1,max_length=64)
    dataset_id: str = Field(min_length=1,max_length=64)
    expected_setup_revision: int = Field(ge=0,lt=2147483647)
    selection: ModernSelection | None
    research_request: ResearchRequest
    origin_recommendation_ref: RecommendationReference | None = None


def validate_requirement_resolutions(check,resolutions):
    from app.core.exceptions import StorageError
    from app.domain.analysis_plan.checks import validate_resolutions
    model=SourceRequirementCheck if check.get('rules_version')=='analysis_plan_rules_v5' else RequirementCheck
    parsed=model.model_validate(check,strict=True)
    if parsed.research_missing or parsed.data_check is None:
        raise StorageError('task_input_invalid','需求或计算来源不完整，请补充后独立确认。',422)
    validate_resolutions(parsed.data_check.model_dump(mode='json'),resolutions)


class SourceResolution(StrictModel):
    confirmed: Literal[True]
    note: str = Field(min_length=1,max_length=4000)

    @model_validator(mode='after')
    def explicit_note(self):
        if not self.note.strip():raise ValueError('Source clarification must be explicit.')
        return self

class SourceRequirementCreateRequest(RequirementCreateRequest):
    schema_version: Literal[5]

class SourceRequirementCheck(RequirementCheck):
    rules_version: Literal['analysis_plan_rules_v5']

class SourceRequirementSnapshot(RequirementSnapshot):
    schema_version: Literal[5]
    workflow_version: Literal['analysis_plan_v5']
    rules_version: Literal['analysis_plan_rules_v5']
    source_reference: dict | None

class SourceRequirementState(RequirementState):
    check: SourceRequirementCheck | None = None
    source_resolution: SourceResolution | None = None

class SourceRequirementPlanContent(RequirementPlanContent):
    schema_version: Literal[5]
    workflow_version: Literal['analysis_plan_v5']
    rules_version: Literal['analysis_plan_rules_v5']
    check: SourceRequirementCheck
    source_reference: dict | None
    source_resolution: SourceResolution

class ConfirmedSourceRequirementPlan(SourceRequirementPlanContent):
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')

class SourceRequirementReview(RequirementReview):
    source_mapping: list[dict]
    check: SourceRequirementCheck | None
    result: ConfirmedSourceRequirementPlan | None
    source_reference: dict | None
    source_resolution: SourceResolution | None

class SourceDecisionRequest(StrictModel):
    expected_task_revision: int = Field(ge=1,lt=2147483647)
    input_version: AnalysisPlanInputVersion
    checkpoint_id: str = Field(min_length=1,max_length=64)
    wait_id: str = Field(min_length=1,max_length=64)
    plan_revision: int = Field(ge=1)
    source_resolution: SourceResolution

RequirementPage.model_rebuild()
