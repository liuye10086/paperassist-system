from typing import Literal
from pydantic import Field, model_validator
from app.domain.correlation.contracts import StrictModel,ColumnId
from app.domain.comparison.contracts import GroupIdentity
from app.domain.regression.contracts import Assumptions
ENGINE='roc_statistics_dataset_v1'
class RocSelection(StrictModel):
    task_type:Literal['roc']
    method:Literal['roc_auc']
    sheet_name:str=Field(min_length=1,max_length=31)
    outcome_column:ColumnId|None
    score_column:ColumnId|None
    positive:GroupIdentity|None
    negative:GroupIdentity|None
    direction:Literal['higher_is_positive','lower_is_positive']|None
    score_kind:Literal['probability','general']|None
    score_source:str=Field(max_length=500)
    score_version:str=Field(max_length=200)
    formation:str=Field(max_length=2000)
    evaluation_role:Literal['external_validation','held_out_validation','apparent_exploratory','unknown']
    independence_confirmed:bool
    outcome_time:str=Field(max_length=500)
    missing_policy:Literal['complete_cases']
    assumptions:Assumptions
    @model_validator(mode='after')
    def coherent(self):
        if self.outcome_column and self.outcome_column==self.score_column: raise ValueError('Distinct roles required.')
        if self.positive and self.positive==self.negative: raise ValueError('Distinct categories required.')
        return self
ROCSelection=RocSelection
Selection=RocSelection
def selected_columns(s): return [x for x in [s.outcome_column,s.score_column] if x]
class AucInterval(StrictModel):
    low:float|None=Field(ge=0,le=1)
    high:float|None=Field(ge=0,le=1)
    level:Literal[0.95]
    method:Literal['delong_normal_clipped']
    reason:str|None
class RocPoint(StrictModel):
    threshold_kind:Literal['above_all','below_all','value']
    threshold:float|None
    tpr:float=Field(ge=0,le=1)
    fpr:float=Field(ge=0,le=1)
    sensitivity:float=Field(ge=0,le=1)
    specificity:float=Field(ge=0,le=1)
class RocStatistics(StrictModel):
    method:Literal['roc_auc']
    n:int=Field(ge=2,le=10000)
    positive_n:int
    negative_n:int
    auc:float=Field(ge=0,le=1)
    variance:float|None=Field(ge=0)
    confidence_interval:AucInterval
    points:list[RocPoint]
    direction:Literal['higher_is_positive','lower_is_positive']
    evaluation_role:Literal['external_validation','held_out_validation','apparent_exploratory','unknown']
    warnings:list[str]

    @model_validator(mode='after')
    def coherent(self):
        if self.positive_n<1 or self.negative_n<1 or self.positive_n+self.negative_n!=self.n:raise ValueError('Class counts mismatch.')
        if len(self.points)<2 or self.points[0].threshold is not None or self.points[0].threshold_kind != ('above_all' if self.direction=='higher_is_positive' else 'below_all'):raise ValueError('ROC sentinel mismatch.')
        if (self.points[0].tpr,self.points[0].fpr)!=(0,0) or (self.points[-1].tpr,self.points[-1].fpr)!=(1,1):raise ValueError('ROC endpoints mismatch.')
        for a,b in zip(self.points,self.points[1:]):
            if b.tpr<a.tpr or b.fpr<a.fpr or b.threshold_kind!='value' or b.threshold is None:raise ValueError('ROC points mismatch.')
        for point in self.points:
            if point.sensitivity!=point.tpr or point.specificity!=1-point.fpr:raise ValueError('ROC rates mismatch.')
        ci=self.confidence_interval
        if (ci.low is None)!=(ci.high is None) or (ci.low is None)!=(ci.reason is not None):raise ValueError('Interval reason mismatch.')
        return self
