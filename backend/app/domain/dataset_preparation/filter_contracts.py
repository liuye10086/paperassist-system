"""Bounded, typed population predicates and complete three-valued receipts."""
from decimal import Decimal
from typing import Literal
from pydantic import Field, model_validator
from app.domain.datasets.contracts import StrictModel, a1
from app.domain.dataset_preparation.contracts import validate_value

class FilterCondition(StrictModel):
    column: int = Field(ge=1,le=256)
    kind: Literal['number','text','boolean','missing']
    operator: Literal['eq','ne','gt','ge','lt','le','between','in','is_missing','is_not_missing']
    value: str | bool | None = None
    values: list[str | bool] | None = Field(default=None,max_length=20,min_length=1)
    lower: str | None = None
    upper: str | None = None

    @model_validator(mode='after')
    def coherent(self):
        op=self.operator
        if self.kind=='missing':
            if op not in ('is_missing','is_not_missing') or any(x is not None for x in (self.value,self.values,self.lower,self.upper)):
                raise ValueError('Explicit missing predicate requires no operand')
            return self
        allowed=('eq','ne','gt','ge','lt','le','between') if self.kind=='number' else ('eq','ne','in')
        if op not in allowed:raise ValueError('Unsupported typed operator')
        if op=='between':
            if self.value is not None or self.values is not None or self.lower is None or self.upper is None:raise ValueError('Invalid interval')
            operands=[self.lower,self.upper]
        elif op=='in':
            if self.value is not None or self.values is None or self.lower is not None or self.upper is not None:raise ValueError('Invalid set')
            operands=self.values
        else:
            if self.value is None or self.values is not None or self.lower is not None or self.upper is not None:raise ValueError('Invalid scalar')
            operands=[self.value]
        for value in operands:
            if isinstance(value,str) and len(value)>4000:raise ValueError('Operand too large')
            validate_value(self.kind,value)
        if op=='between' and Decimal(self.lower)>Decimal(self.upper):raise ValueError('Reversed interval')
        if op=='in' and len(set(operands))!=len(operands):raise ValueError('Duplicate set operand')
        return self

class FilterRecipe(StrictModel):
    conditions: list[FilterCondition] = Field(min_length=1,max_length=10)
    reason: str = Field(min_length=1,max_length=1000)
    unit_acknowledged: bool = False

    @model_validator(mode='after')
    def coherent(self):
        if not self.reason.strip():raise ValueError('Explicit population reason required')
        return self

class ConditionCounts(StrictModel):
    condition_index: int = Field(ge=0,le=9)
    true_count: int = Field(ge=0)
    false_count: int = Field(ge=0)
    unknown_count: int = Field(ge=0)

class FilterSummary(StrictModel):
    root_record_count: int = Field(ge=1,le=100000)
    base_record_count: int = Field(ge=1,le=100000)
    retained_record_count: int = Field(ge=0,le=100000)
    inherited_excluded_row_count: int = Field(ge=0)
    mismatch_excluded_row_count: int = Field(ge=0)
    unknown_excluded_row_count: int = Field(ge=0)
    cumulative_excluded_row_count: int = Field(ge=0)
    impact_count: int = Field(ge=1,le=100000)
    condition_counts: list[ConditionCounts] = Field(min_length=1,max_length=10)

    @model_validator(mode='after')
    def coherent(self):
        if (self.root_record_count-self.inherited_excluded_row_count!=self.base_record_count
            or self.base_record_count-self.mismatch_excluded_row_count-self.unknown_excluded_row_count!=self.retained_record_count
            or self.root_record_count-self.cumulative_excluded_row_count!=self.retained_record_count
            or self.impact_count!=self.base_record_count
            or [c.condition_index for c in self.condition_counts]!=list(range(len(self.condition_counts)))
            or any(c.true_count+c.false_count+c.unknown_count!=self.base_record_count for c in self.condition_counts)):
            raise ValueError('Inconsistent filter counts')
        return self

class FilterEvaluation(StrictModel):
    condition_index: int = Field(ge=0,le=9)
    coordinate: str
    status: Literal['true','false','unknown']

class FilterImpact(StrictModel):
    row: int = Field(ge=1,le=100000)
    classification: Literal['retained','mismatch','unknown']
    failed_conditions: list[int]
    unknown_conditions: list[int]
    evaluations: list[FilterEvaluation] = Field(min_length=1,max_length=10)

    @model_validator(mode='after')
    def coherent(self):
        failed=[e.condition_index for e in self.evaluations if e.status=='false']
        unknown=[e.condition_index for e in self.evaluations if e.status=='unknown']
        if (self.failed_conditions!=failed or self.unknown_conditions!=unknown
            or [e.condition_index for e in self.evaluations]!=list(range(len(self.evaluations)))
            or any(a1(e.coordinate)[0]!=self.row for e in self.evaluations)
            or self.classification!=('mismatch' if failed else 'unknown' if unknown else 'retained')):
            raise ValueError('Invalid three-valued row receipt')
        return self
