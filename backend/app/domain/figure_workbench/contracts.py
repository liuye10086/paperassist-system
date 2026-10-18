"""Closed configuration vocabulary; no arbitrary code or numerical overrides."""
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator

RENDERER='openai_figure_workbench_v1'
KINDS=('boxplot','correlation_heatmap','scatter','line','bar','violin','forest','roc_curve','kaplan_meier')
class Strict(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid',allow_inf_nan=False)
class ProjectionRules(Strict):
    x_column:str|None=Field(default=None,pattern=r'^[A-Z]{1,3}$')
    y_column:str|None=Field(default=None,pattern=r'^[A-Z]{1,3}$')
    group_column:str|None=Field(default=None,pattern=r'^[A-Z]{1,3}$')
    category_column:str|None=Field(default=None,pattern=r'^[A-Z]{1,3}$')
    x_type:Literal['numeric','datetime','ordered']='numeric'
    x_order:list[str|float|int|bool]=Field(default_factory=list,max_length=100)
    expected_x:list[str|float|int|bool]=Field(default_factory=list,max_length=2000)
    aggregation:Literal['unique','mean']='unique'
    bar_stat:Literal['count','proportion','mean']='count'
    error_bars:Literal['none','sd']='none'
    missing_group:Literal['block','exclude']='block'
    included_categories:list[str|float|int|bool]=Field(default_factory=list,max_length=100)
    @model_validator(mode='after')
    def validate_values(self):
        from app.domain.figure_workbench.kernel import validate_rule_values
        validate_rule_values(self.model_dump())
        return self
class FigureStyle(Strict):
    title:str=Field(default='',max_length=160)
    caption:str=Field(default='',max_length=1000)
    aliases:dict[str,str]=Field(default_factory=dict,max_length=100)
    palette:Literal['blue','colorblind','gray']='colorblind'
    width:int=Field(default=2400,ge=1600,le=5000)
    height:int=Field(default=1600,ge=1000,le=4000)
    font_size:int=Field(default=12,ge=8,le=24)
    display_order:list[str]=Field(default_factory=list,max_length=100)
    @model_validator(mode='after')
    def validate_labels(self):
        if any(not 1<=len(k)<=160 or not 1<=len(v)<=160 for k,v in self.aliases.items()): raise ValueError('Invalid alias')
        if len(set(self.display_order))!=len(self.display_order): raise ValueError('Duplicate order')
        return self
class FigureConfig(Strict):
    figure_kind:Literal['boxplot','correlation_heatmap','scatter','line','bar','violin','forest','roc_curve','kaplan_meier']
    language:Literal['zh-CN','en']
    projection:ProjectionRules|None=None
    style:FigureStyle=Field(default_factory=FigureStyle)
    @model_validator(mode='after')
    def semantic_fields(self):
        p=self.projection;k=self.figure_kind
        if k in ('line','bar','violin'):
            if p is None: return self
            if p.error_bars=='sd' and not (k=='bar' and p.bar_stat=='mean'): raise ValueError('SD only for record means')
        elif p is not None and not (k=='scatter' and p.group_column and p.missing_group=='block'):
            raise ValueError('Original statistics cannot change population')
        return self
class SaveConfiguration(Strict):
    configuration_id:str|None=Field(default=None,max_length=64)
    expected_revision:int|None=Field(default=None,ge=1)
    config:FigureConfig
class ConfirmProjection(Strict):
    input_sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
    approved:Literal[True]
class GenerateFigure(Strict):
    idempotency_key:str=Field(min_length=1,max_length=128,pattern=r'^[\x21-\x7e]+$')
    external_processing:dict
class ReuseExplanation(Strict):
    source_explanation_id:str=Field(min_length=1,max_length=64)
