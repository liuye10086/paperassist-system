"""Explicit six-method comparison selections and bounded frozen statistics."""
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal
from pydantic import Field, model_validator
from app.domain.correlation.contracts import StrictModel, ColumnId

ENGINE = 'group_comparison_statistics_dataset_v1'
ComparisonMethod = Literal['welch_t','mann_whitney_u','paired_t','wilcoxon','welch_anova','kruskal_wallis']


def canonical_number(value):
    if not isinstance(value,str) or len(value)>500:
        raise ValueError('Numeric category exceeds the 500-character limit.')
    try:
        number=Decimal(value)
        if not number.is_finite(): raise ValueError('Nonfinite category.')
    except (InvalidOperation, TypeError):
        raise ValueError('Invalid numeric category.') from None
    if not number: return '0'
    # Check the fixed-point expansion before format(); a short exponent such as
    # 1e100000000 must not allocate an attacker-sized category string.
    sign, digits, exponent = number.as_tuple()
    length = sign + (len(digits)+exponent if exponent>=0 else max(1,len(digits)+exponent)+1-exponent)
    if length>500:
        raise ValueError('Numeric category exceeds the 500-character limit.')
    text=format(number,'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


class GroupIdentity(StrictModel):
    kind: Literal['text','number','boolean']
    value: str = Field(max_length=500)

    @model_validator(mode='after')
    def canonical(self):
        if self.kind=='number': self.value=canonical_number(self.value)
        elif self.kind=='boolean' and self.value not in ('true','false'): raise ValueError('Invalid boolean category.')
        elif self.kind=='text' and not self.value.strip(): raise ValueError('A missing category cannot participate.')
        return self


class ComparisonAssumptions(StrictModel):
    independent_units: bool
    distribution: Literal['unknown','normal','symmetric_differences','rank']
    inference_confirmed: bool


class ComparisonSelection(StrictModel):
    task_type: Literal['group_comparison']
    sheet_name: str = Field(min_length=1,max_length=31)
    design: Literal['independent','paired','multiple']
    method: ComparisonMethod
    numeric_column: ColumnId | None
    group_column: ColumnId | None
    groups: list[GroupIdentity] = Field(max_length=6)
    pair_id_column: ColumnId | None
    before_column: ColumnId | None
    after_column: ColumnId | None
    unit: str = Field(max_length=80)
    missing_policy: Literal['complete_cases','complete_pairs']
    posthoc: Literal['none','all_pairs_holm']
    assumptions: ComparisonAssumptions

    @model_validator(mode='after')
    def coherent(self):
        methods={'independent':('welch_t','mann_whitney_u'),'paired':('paired_t','wilcoxon'),'multiple':('welch_anova','kruskal_wallis')}
        if self.method not in methods[self.design]: raise ValueError('Method does not match design.')
        if self.design=='paired':
            columns=[self.pair_id_column,self.before_column,self.after_column]
            if (None in columns or len(set(columns))!=3 or self.numeric_column is not None or self.group_column is not None
                    or self.groups or self.missing_policy!='complete_pairs' or self.posthoc!='none'):
                raise ValueError('A wide paired design needs exactly three distinct roles.')
        else:
            if (self.numeric_column is None or self.group_column is None or self.numeric_column==self.group_column
                    or any(v is not None for v in (self.pair_id_column,self.before_column,self.after_column))
                    or self.missing_policy!='complete_cases' or self.design=='independent' and (len(self.groups)!=2 or self.posthoc!='none')
                    or self.design=='multiple' and not 3<=len(self.groups)<=6):
                raise ValueError('Independent comparison roles and participating groups are required.')
            if len({(g.kind,g.value) for g in self.groups})!=len(self.groups): raise ValueError('Participating groups must be distinct.')
        return self


def selected_columns(selection):
    return [selection.pair_id_column,selection.before_column,selection.after_column] if selection.design=='paired' else [selection.numeric_column,selection.group_column]


class GroupOption(GroupIdentity):
    label: str
    count: int = Field(ge=1)


class GroupOptions(StrictModel):
    dataset_id: str
    sheet_name: str
    group_column: ColumnId
    row_count: int = Field(ge=1)
    missing_count: int = Field(ge=0)
    options: list[GroupOption]


class Statistic(StrictModel):
    name: Literal['t','U','W','F','H']
    value: float
    df_numerator: float | None
    df_denominator: float | None


class Estimate(StrictModel):
    name: Literal['mean_difference','rank_biserial'] | None
    value: float | None
    unit: Literal['outcome','dimensionless'] | None
    reason: Literal['omnibus_no_single_effect'] | None


class PValue(StrictModel):
    value: float = Field(ge=0,le=1)
    method: Literal['welch_t_two_sided','paired_t_two_sided','mann_whitney_exact_two_sided','mann_whitney_asymptotic_two_sided',
        'wilcoxon_sign_exact_two_sided','wilcoxon_asymptotic_two_sided','welch_anova_f','kruskal_chi_square']


class ConfidenceInterval(StrictModel):
    low: float | None
    high: float | None
    level: Literal[0.95]
    method: Literal['welch_t','paired_t'] | None
    reason: Literal['rank_interval_not_implemented','omnibus_no_interval'] | None
    simultaneous: Literal[False]


class Inference(StrictModel):
    alternative: Literal['two-sided','omnibus']
    rank_method: Literal['average'] | None
    zero_method: Literal['wilcox'] | None
    continuity_correction: bool
    exact: bool
    zero_count: int = Field(ge=0)


class Family(StrictModel):
    policy: Literal['none','all_pairs_holm']
    size: int = Field(ge=0,le=15)
    alpha: Literal[0.05]


class Pairwise(StrictModel):
    left_index: int = Field(ge=0,le=5)
    right_index: int = Field(ge=1,le=5)
    method: Literal['welch_t','mann_whitney_u']
    statistic: Statistic
    estimate: Estimate
    p_value: PValue
    confidence_interval: ConfidenceInterval
    inference: Inference
    adjusted_p_value: float = Field(ge=0,le=1)
    adjustment: Literal['holm']


class ComparisonStatistics(StrictModel):
    method: ComparisonMethod
    design: Literal['independent','paired','multiple']
    sample_sizes: list[Annotated[int,Field(ge=3,le=10000)]] = Field(min_length=2,max_length=6)
    statistic: Statistic
    estimate: Estimate
    p_value: PValue
    confidence_interval: ConfidenceInterval
    inference: Inference
    family: Family
    pairwise: list[Pairwise] = Field(max_length=15)
    warnings: list[Literal['small_sample','asymptotic_p_value','rank_interval_unavailable','pairwise_intervals_unadjusted','observational_not_causal','zero_differences_excluded']]

    @model_validator(mode='after')
    def coherent(self):
        paired=self.method in ('paired_t','wilcoxon');multiple=self.method in ('welch_anova','kruskal_wallis')
        if self.design!=('paired' if paired else 'multiple' if multiple else 'independent'): raise ValueError('Statistics design differs.')
        if not multiple and len(self.sample_sizes)!=2 or paired and self.sample_sizes[0]!=self.sample_sizes[1]: raise ValueError('Invalid sample dimensions.')
        if (max(self.sample_sizes) if paired else sum(self.sample_sizes))>10000: raise ValueError('Input exceeds limit.')
        if self.method=='kruskal_wallis' and min(self.sample_sizes)<5: raise ValueError('Kruskal approximation needs at least five per group.')
        expected=[(i,j) for i in range(len(self.sample_sizes)) for j in range(i+1,len(self.sample_sizes))] if self.family.policy=='all_pairs_holm' else []
        if self.family.size!=len(expected) or [(p.left_index,p.right_index) for p in self.pairwise]!=expected or expected and not multiple: raise ValueError('Incomplete predeclared family.')
        return self


class ExcludedRow(StrictModel):
    row: int = Field(ge=1)
    coordinates: list[str]
    reason: Literal['selected_missing','group_not_selected']


class RowAudit(StrictModel):
    included_rows: list[int]
    excluded_rows: list[ExcludedRow]
    missing_policy: Literal['complete_cases','complete_pairs']
    group_rows: list[list[int]]
    pair_id_column: ColumnId | None


class Variable(StrictModel):
    column: ColumnId
    name: str
    unit: str
