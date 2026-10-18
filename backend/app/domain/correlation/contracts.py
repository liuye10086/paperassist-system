"""Explicit correlation selections; no model output can confirm assumptions."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

ColumnId = Annotated[str, Field(pattern=r'^[A-Z]{1,3}$')]
ENGINE = 'correlation_statistics_dataset_v1'


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', allow_inf_nan=False)


class CorrelationAssumptions(StrictModel):
    independent_observations: bool
    relationship_form: Literal['unknown', 'linear', 'monotonic']
    inference_assumptions_confirmed: bool


class CorrelationSelection(StrictModel):
    task_type: Literal['correlation']
    sheet_name: str = Field(min_length=1, max_length=31)
    method: Literal['pearson', 'spearman']
    mode: Literal['pair', 'matrix']
    columns: list[ColumnId] = Field(min_length=2, max_length=10)
    units: dict[ColumnId, Annotated[str, Field(max_length=80)]]
    missing_policy: Literal['complete_cases']
    assumptions: CorrelationAssumptions

    @model_validator(mode='after')
    def coherent(self):
        if len(set(self.columns)) != len(self.columns) or set(self.units) != set(self.columns):
            raise ValueError('Selected fields and units must correspond exactly.')
        if self.mode == 'pair' and len(self.columns) != 2:
            raise ValueError('A pair requires exactly two fields.')
        return self


class RecommendationReference(StrictModel):
    task_id: str = Field(min_length=1, max_length=64)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class PValue(StrictModel):
    value: float | None = Field(ge=0, le=1)
    method: Literal['pearson_beta_two_sided','spearman_pairings_exact','spearman_pairings_monte_carlo','spearman_asymptotic'] | None
    reason: Literal['exploratory_matrix'] | None


class ConfidenceInterval(StrictModel):
    low: float | None = Field(ge=-1,le=1)
    high: float | None = Field(ge=-1,le=1)
    level: Literal[0.95]
    method: Literal['fisher_z'] | None
    reason: Literal['exploratory_matrix','insufficient_for_fisher_interval','degenerate_correlation','spearman_interval_not_implemented'] | None


class Inference(StrictModel):
    alternative: Literal['two-sided']
    rank_method: Literal['average'] | None
    permutation_type: Literal['pairings'] | None
    n_resamples: int | None = Field(ge=1)
    seed: int | None = Field(ge=0,le=4294967295)
    exact: bool | None


class CorrelationStatistics(StrictModel):
    method: Literal['pearson','spearman']
    mode: Literal['pair','matrix']
    n: int = Field(ge=3,le=10000)
    coefficient: float | None = Field(ge=-1,le=1)
    matrix: list[list[Annotated[float,Field(ge=-1,le=1)]]] | None
    p_value: PValue
    confidence_interval: ConfidenceInterval
    inference: Inference
    warnings: list[Literal['correlation_not_causation','small_sample','monte_carlo_p_value','asymptotic_p_value','exploratory_matrix']]

    @model_validator(mode='after')
    def coherent(self):
        if self.mode=='matrix':
            if (self.coefficient is not None or self.matrix is None or not 2<=len(self.matrix)<=10
                    or any(len(row)!=len(self.matrix) for row in self.matrix)
                    or self.p_value.value is not None or self.p_value.reason!='exploratory_matrix'
                    or self.confidence_interval.reason!='exploratory_matrix'):
                raise ValueError('An exploratory matrix has no inferential result.')
        elif self.matrix is not None or self.coefficient is None or self.p_value.value is None:
            raise ValueError('A pair requires a coefficient and explicit P-value method.')
        if self.method=='spearman' and self.inference.rank_method!='average':
            raise ValueError('Spearman uses average ranks.')
        return self


def selection_model(value):
    if isinstance(value,dict) and value.get('task_type') in ('regression','roc','survival'):
        from importlib import import_module
        return import_module('app.domain.'+value['task_type']+'.contracts').Selection
    if isinstance(value, dict) and value.get('task_type') == 'group_comparison':
        from app.domain.comparison.contracts import ComparisonSelection
        return ComparisonSelection
    if isinstance(value, dict) and value.get('task_type') == 'correlation':
        return CorrelationSelection
    if not isinstance(value, dict) or value.get('task_type') != 'descriptive_boxplot':
        raise ValueError('Unknown analysis task type.')
    from app.domain.analysis import AnalysisSelection
    return AnalysisSelection


def parse_selection(value):
    if isinstance(value, BaseModel):
        value = value.model_dump(mode='json')
    return selection_model(value).model_validate(value, strict=True)
