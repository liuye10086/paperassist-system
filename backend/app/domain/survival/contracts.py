from typing import Literal
from pydantic import Field,model_validator
from app.domain.correlation.contracts import StrictModel,ColumnId
from app.domain.comparison.contracts import GroupIdentity
from app.domain.regression.contracts import Assumptions
ENGINE='survival_statistics_dataset_v1'
class SurvivalSelection(StrictModel):
    task_type:Literal['survival']
    method:Literal['kaplan_meier']
    sheet_name:str=Field(min_length=1,max_length=31)
    id_column:ColumnId|None
    time_column:ColumnId|None
    status_column:ColumnId|None
    group_column:ColumnId|None
    event:GroupIdentity|None
    censored:GroupIdentity|None
    groups:list[GroupIdentity]=Field(max_length=6)
    time_unit:str=Field(max_length=80)
    time_origin:str=Field(max_length=500)
    noninformative_censoring:bool
    missing_policy:Literal['complete_cases']
    assumptions:Assumptions
    @model_validator(mode='after')
    def coherent(self):
        cols=selected_columns(self)
        if len(cols)!=len(set(cols)): raise ValueError('Distinct roles required.')
        if self.event and self.event==self.censored: raise ValueError('Distinct status required.')
        if len({(g.kind,g.value) for g in self.groups})!=len(self.groups): raise ValueError('Duplicate groups.')
        if self.groups and not self.group_column: raise ValueError('Groups need group role.')
        return self
Selection=SurvivalSelection
def selected_columns(s): return [x for x in [s.id_column,s.time_column,s.status_column,s.group_column] if x]
class SurvivalPoint(StrictModel):
    time:float=Field(ge=0)
    n_at_risk:int
    n_event:int
    n_censored:int
    survival:float=Field(ge=0,le=1)
    greenwood_variance:float|None=Field(ge=0)
    ci_low:float|None=Field(ge=0,le=1)
    ci_high:float|None=Field(ge=0,le=1)
    ci_reason:str|None
class RiskPoint(StrictModel):
    time:float=Field(ge=0)
    n_at_risk:int
    events_before:int
    censored_before:int
class SurvivalGroup(StrictModel):
    identity:GroupIdentity|None
    label:str
    n:int
    event_n:int
    censored_n:int
    max_time:float
    median:float|None
    median_reason:str|None
    points:list[SurvivalPoint]
    risk_table:list[RiskPoint]
    @model_validator(mode='after')
    def coherent(self):
        if self.n<1 or self.event_n<0 or self.censored_n<0 or self.event_n+self.censored_n!=self.n:raise ValueError('Survival counts mismatch.')
        if not self.points or self.points[-1].time!=self.max_time:raise ValueError('Survival endpoint mismatch.')
        previous_risk=self.n;previous_survival=1.;previous_time=-1.
        event_sum=censor_sum=0
        for point in self.points:
            if point.time<=previous_time or point.n_at_risk!=previous_risk or point.n_event<0 or point.n_censored<0 or point.n_event+point.n_censored>point.n_at_risk:raise ValueError('Survival risk set mismatch.')
            if abs(point.survival-previous_survival*(1-point.n_event/point.n_at_risk))>1e-14:raise ValueError('Product limit mismatch.')
            if (point.ci_low is None)!=(point.ci_high is None) or (point.ci_low is None)!=(point.ci_reason is not None):raise ValueError('Point interval reason mismatch.')
            previous_risk-=point.n_event+point.n_censored;previous_survival=point.survival;previous_time=point.time;event_sum+=point.n_event;censor_sum+=point.n_censored
        if event_sum!=self.event_n or censor_sum!=self.censored_n:raise ValueError('Event totals mismatch.')
        if any(r.n_at_risk<0 or r.events_before<0 or r.censored_before<0 or r.n_at_risk+r.events_before+r.censored_before!=self.n for r in self.risk_table):raise ValueError('Risk table identity mismatch.')
        median=next((p.time for p in self.points if p.survival<=.5),None)
        if self.median!=median or (self.median is None)!=(self.median_reason=='not_reached'):raise ValueError('Median semantics mismatch.')
        return self

class SurvivalStatistics(StrictModel):
    method:Literal['kaplan_meier']
    n:int=Field(ge=1,le=10000)
    groups:list[SurvivalGroup]
    time_unit:str
    warnings:list[str]

    @model_validator(mode='after')
    def coherent(self):
        if not 1<=len(self.groups)<=6 or sum(g.n for g in self.groups)!=self.n:raise ValueError('Survival group counts mismatch.')
        if any([r.time for r in g.risk_table]!=[r.time for r in self.groups[0].risk_table] for g in self.groups):raise ValueError('Risk tables require common axis.')
        return self
