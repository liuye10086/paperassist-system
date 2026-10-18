from typing import Literal
from pydantic import Field, model_validator, model_serializer
from app.domain.correlation.contracts import StrictModel, ColumnId
from app.domain.comparison.contracts import GroupIdentity
ENGINE='regression_statistics_dataset_v1'
class Assumptions(StrictModel):
    independent_units: bool
    inference_confirmed: bool
class Covariate(StrictModel):
    column: ColumnId
    type: Literal['continuous','categorical']
    unit: str=Field(max_length=80)
    levels: list[GroupIdentity]=Field(max_length=6)
    reference: GroupIdentity|None
    @model_validator(mode='after')
    def coherent(self):
        if self.type=='continuous' and (self.levels or self.reference): raise ValueError('Continuous encoding has no levels.')
        if len({(x.kind,x.value) for x in self.levels})!=len(self.levels): raise ValueError('Duplicate levels.')
        if self.reference and self.reference not in self.levels: raise ValueError('Reference must be a frozen level.')
        return self
class RegressionSelection(StrictModel):
    task_type: Literal['regression']
    method: Literal['ols','logistic']
    sheet_name: str=Field(min_length=1,max_length=31)
    outcome_column: ColumnId|None
    covariates: list[Covariate]=Field(max_length=8)
    outcome_unit: str=Field(max_length=80)
    positive: GroupIdentity|None
    negative: GroupIdentity|None
    id_column: ColumnId|None
    missing_policy: Literal['complete_cases']
    assumptions: Assumptions
    @model_validator(mode='after')
    def coherent(self):
        cols=selected_columns(self)
        if len(cols)!=len(set(cols)): raise ValueError('Roles must be distinct.')
        if self.positive and self.positive==self.negative: raise ValueError('Binary categories must differ.')
        if self.method=='ols' and (self.positive or self.negative): raise ValueError('OLS has no binary mapping.')
        return self
Selection=RegressionSelection
def selected_columns(s): return [x for x in [s.outcome_column,*[c.column for c in s.covariates],s.id_column] if x]
class Coefficient(StrictModel):
    term:str
    column:str|None
    level:GroupIdentity|None
    reference:GroupIdentity|None
    unit:str
    beta:float
    se:float=Field(ge=0)
    statistic:float
    p_value:float=Field(ge=0,le=1)
    ci_low:float
    ci_high:float
    or_value:float|None
    or_ci_low:float|None
    or_ci_high:float|None
class Diagnostics(StrictModel):
    rank:int
    centers:list[float]
    scales:list[float]
    condition_number:float
    converged:bool
    gradient_max:float|None
    residuals:list[float]
    fitted:list[float]
    leverage:list[float]
    cooks_distance:list[float]
class RegressionStatistics(StrictModel):
    method:Literal['ols','logistic']
    n:int=Field(ge=10,le=10000)
    p:int=Field(ge=2,le=21)
    df_residual:int
    coefficients:list[Coefficient]
    covariance:list[list[float]]
    r_squared:float|None
    adjusted_r_squared:float|None
    residual_sd:float|None
    log_likelihood:float|None
    deviance:float|None
    aic:float|None
    diagnostics:Diagnostics
    warnings:list[str]
    @model_validator(mode='after')
    def coherent(self):
        if len(self.diagnostics.centers)!=self.p-1 or len(self.diagnostics.scales)!=self.p-1 or any(x<=0 for x in self.diagnostics.scales):raise ValueError('Scaling metadata mismatch.')
        if len(self.coefficients)!=self.p or len(self.covariance)!=self.p or any(len(row)!=self.p for row in self.covariance):raise ValueError('Model dimensions mismatch.')
        if self.df_residual!=self.n-self.p or self.df_residual<2 or self.diagnostics.rank!=self.p:raise ValueError('Model degrees of freedom mismatch.')
        if len(self.diagnostics.residuals)!=self.n or len(self.diagnostics.fitted)!=self.n:raise ValueError('Observation diagnostics length mismatch.')
        if self.coefficients[0].term!='intercept' or self.coefficients[0].column is not None:raise ValueError('Fixed intercept required.')
        for i,c in enumerate(self.coefficients):
            if c.se<=0 or c.ci_low>c.beta or c.ci_high<c.beta or self.covariance[i][i]<=0:raise ValueError('Invalid coefficient inference.')
            if abs(self.covariance[i][i]-c.se*c.se)>1e-12*max(1,self.covariance[i][i]):raise ValueError('Covariance and standard error mismatch.')
            if self.method=='ols' and any(x is not None for x in (c.or_value,c.or_ci_low,c.or_ci_high)):raise ValueError('OLS has no OR.')
            if self.method=='logistic' and (c.or_value is None or c.or_ci_low is None or c.or_ci_high is None or not 0<c.or_ci_low<=c.or_value<=c.or_ci_high):raise ValueError('Logistic OR inference required.')
        if self.method=='ols':
            if any(x is None for x in (self.r_squared,self.adjusted_r_squared,self.residual_sd)) or len(self.diagnostics.leverage)!=self.n or len(self.diagnostics.cooks_distance)!=self.n:raise ValueError('OLS diagnostics required.')
            if any(x is not None for x in (self.log_likelihood,self.deviance,self.aic,self.diagnostics.gradient_max)):raise ValueError('OLS metadata mismatch.')
        else:
            if any(x is None for x in (self.log_likelihood,self.deviance,self.aic,self.diagnostics.gradient_max)) or not self.diagnostics.converged:raise ValueError('Logistic convergence metadata required.')
            if any(x is not None for x in (self.r_squared,self.adjusted_r_squared,self.residual_sd)) or self.diagnostics.leverage or self.diagnostics.cooks_distance:raise ValueError('Logistic metadata mismatch.')
        return self

class Variable(StrictModel):
    column:ColumnId
    name:str=Field(min_length=1,max_length=160)
    unit:str=Field(max_length=80)
class ExcludedRow(StrictModel):
    row:int=Field(ge=1,le=100000)
    coordinates:list[str]=Field(min_length=1,max_length=10)
    reason:Literal['selected_missing','group_not_selected']
class RowAudit(StrictModel):
    included_rows:list[int]=Field(max_length=10000)
    excluded_rows:list[ExcludedRow]=Field(max_length=10000)
    missing_policy:Literal['complete_cases']
    encoding_counts:dict[ColumnId,dict[str,int]]
    @model_validator(mode='after')
    def coherent(self):
        rows=self.included_rows+[r.row for r in self.excluded_rows]
        if len(set(rows))!=len(rows) or any(not 1<=r<=100000 for r in rows):raise ValueError('Audit original rows must be unique.')
        if len(rows)>10000:raise ValueError('Audit row limit.')
        if any(len(v)>6 or any(n<0 or n>10000 for n in v.values()) for v in self.encoding_counts.values()):raise ValueError('Encoding count bound.')
        return self
class StatisticalEngine(StrictModel):
    id:Literal['regression_statistics_dataset_v1','roc_statistics_dataset_v1','survival_statistics_dataset_v1']
    python_version:str=Field(pattern=r'^3\.11\.\d+$')
    scipy_version:Literal['1.17.1']
    numpy_version:Literal['2.4.6']
    parser_version:str=Field(min_length=1,max_length=100)
    encoding_version:Literal['typed_reference_dummy_v1']
    timeout_seconds:Literal[30]
    statsmodels_version:Literal['0.15.0']|None=None
    solver:Literal['qr','newton']|None=None
    max_iterations:Literal[100]|None=None
    tolerance:Literal[1e-10]|None=None
    scale:Literal['center_scale_restored_original_units']|None=None
    separation_solver:Literal['highs']|None=None
    separation_timeout_seconds:Literal[5]|None=None
    execution_contract:Literal['fixed_statistics_v2']|None=None
    @model_serializer(mode='wrap')
    def serialize_contract(self,handler):
        value=handler(self)
        if self.execution_contract is None:value.pop('execution_contract',None)
        return value
    @model_validator(mode='after')
    def coherent(self):
        if self.id=='regression_statistics_dataset_v1':
            if self.statsmodels_version is None or self.scale is None or self.solver is None or self.separation_solver is None or self.separation_timeout_seconds!=5:raise ValueError('Regression engine metadata incomplete.')
            if self.solver=='newton' and (self.max_iterations!=100 or self.tolerance!=1e-10):raise ValueError('Logit settings mismatch.')
            if self.solver=='qr' and (self.max_iterations is not None or self.tolerance is not None):raise ValueError('OLS settings mismatch.')
        elif any(getattr(self,k) is not None for k in ('statsmodels_version','solver','max_iterations','tolerance','scale','separation_solver','separation_timeout_seconds')):raise ValueError('Nonregression engine settings mismatch.')
        return self
