"""Local v2 result provenance; never forwarded to model material builders."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, model_serializer
from app.domain.analysis import AnalysisSelection
from app.domain.analysis_plan.contracts import ConfirmedResearchPlan, ConfirmedModernPlan
from app.domain.regression.contracts import RegressionSelection
from app.domain.roc.contracts import RocSelection
from app.domain.survival.contracts import SurvivalSelection


class StrictContext(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')


class DescriptiveMethod(StrictContext):
    id: Literal['descriptive']
    parameters: AnalysisSelection
    observation_basis: Literal['rows']


class Rounding(StrictContext):
    display_significant_digits: Literal[6]
    stored_values: Literal['full_precision']


class NotComputedMetric(StrictContext):
    value: None
    reason: Literal['not_applicable_descriptive']


class NotComputed(StrictContext):
    p_value: NotComputedMetric
    effect_size: NotComputedMetric
    confidence_interval: NotComputedMetric


class AnalysisContext(StrictContext):
    plan: ConfirmedResearchPlan
    method: DescriptiveMethod
    rounding: Rounding
    not_computed: NotComputed


class CorrelationMethod(StrictContext):
    id: Literal['pearson', 'spearman']
    parameters: dict
    observation_basis: Literal['independent_rows']


class ComparisonMethod(StrictContext):
    id: Literal['welch_t','mann_whitney_u','paired_t','wilcoxon','welch_anova','kruskal_wallis']
    parameters: dict
    observation_basis: Literal['independent_rows','paired_rows']


class ModelingMethod(StrictContext):
    id: Literal['ols','logistic','roc_auc','kaplan_meier']
    parameters: RegressionSelection | RocSelection | SurvivalSelection
    observation_basis: Literal['independent_rows']


from app.domain.analysis_plan.requirements import ConfirmedRequirementPlan,ConfirmedSourceRequirementPlan


class ModernAnalysisContext(StrictContext):
    plan: ConfirmedSourceRequirementPlan | ConfirmedRequirementPlan | ConfirmedModernPlan
    method: ModelingMethod | ComparisonMethod | CorrelationMethod | DescriptiveMethod
    rounding: Rounding
    not_computed: NotComputed | None = None


    @model_serializer(mode='wrap')
    def omit_inapplicable(self, handler):
        value=handler(self)
        if self.not_computed is None: value.pop('not_computed')
        return value


def result_context(plan):
    if plan['selection']['task_type'] in ('regression','roc','survival'):
        return dict(plan=plan,method=dict(id=plan['selection']['method'],parameters=plan['selection'],
            observation_basis='independent_rows'),rounding=dict(display_significant_digits=6,stored_values='full_precision'))
    if plan['selection']['task_type']=='group_comparison':
        return dict(plan=plan,method=dict(id=plan['selection']['method'],parameters=plan['selection'],
            observation_basis='paired_rows' if plan['selection']['design']=='paired' else 'independent_rows'),
            rounding=dict(display_significant_digits=6,stored_values='full_precision'))
    if plan['selection']['task_type']=='correlation':
        return dict(plan=plan,method=dict(id=plan['selection']['method'],parameters=plan['selection'],
            observation_basis='independent_rows'),rounding=dict(display_significant_digits=6,stored_values='full_precision'))
    return dict(plan=plan,method=dict(id='descriptive',parameters=plan['selection'],observation_basis='rows'),
        rounding=dict(display_significant_digits=6,stored_values='full_precision'),
        not_computed={key:dict(value=None,reason='not_applicable_descriptive')
                      for key in ('p_value','effect_size','confidence_interval')})


def plan_selection_check(plan):
    check=plan['check']['data_check'] if plan['schema_version'] in (4,5) else plan['check']
    if check is None:
        raise ValueError('A confirmed plan requires a numerical check.')
    return check['selection_check']


def validate_result_context(value,plan):
    if 'setup_revision' not in value:
        return
    if plan['schema_version'] in (2,3,4,5):
        parsed=(ModernAnalysisContext if plan['schema_version'] in (3,4,5) else AnalysisContext).model_validate(value['analysis_context'],strict=True).model_dump(mode='json')
        version=4 if plan['schema_version'] in (3,4,5) and plan['selection']['task_type']=='group_comparison' else (3 if plan['schema_version'] in (4,5) else plan['schema_version'])
        if plan['schema_version'] in (3,4,5) and plan['selection']['task_type'] in ('regression','roc','survival'):version=5
        if type(value['schema_version']) is not int or value['schema_version']!=version or parsed!=result_context(plan):
            raise ValueError('Research result context differs from confirmed plan.')
    elif 'analysis_context' in value or 'schema_version' in value:
        raise ValueError('Legacy plan cannot become a research result.')
