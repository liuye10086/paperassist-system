"""Explicit, bounded extraction without invented comparison statistics."""
from typing import Annotated, Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator
Id=Annotated[str,Field(min_length=1,max_length=200,pattern=r'^[^/\\\x00-\x1f]+$')]

class FeatureModel(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid',frozen=True,allow_inf_nan=False)

class StructureSelection(FeatureModel):
    resource_source_id:Id
    model_id:int=Field(ge=1,le=2147483647)
    chain_id:str=Field(min_length=1,max_length=200)

class FeatureStep(FeatureModel):
    operation:Literal['annotation','include','exclude']
    feature_ids:list[Id]=Field(default_factory=list,max_length=10000)
    annotation_field:Id|None=None
    annotation_operator:Literal['eq','ne','gt','ge','lt','le','known','unknown']|None=None
    annotation_value:str|float|bool|None=None
    @model_validator(mode='after')
    def coherent(self):
        if self.operation=='annotation':
            if not self.annotation_field or not self.annotation_operator or self.feature_ids:raise ValueError('feature_filter_requires_field_and_operator')
            if self.annotation_operator not in ('known','unknown') and self.annotation_value is None:raise ValueError('feature_filter_value_required')
        elif self.annotation_field is not None or self.annotation_operator is not None or self.annotation_value is not None:raise ValueError('feature_id_filter_only')
        return self

class FeatureExtractConfig(FeatureModel):
    kind:Literal['feature_extract']='feature_extract'
    output_language:Literal['zh-CN','en']='zh-CN'
    resource_source_ids:list[Id]=Field(min_length=1,max_length=10)
    structure_selections:list[StructureSelection]=Field(default_factory=list,max_length=10)
    steps:list[FeatureStep]=Field(default_factory=list,max_length=20)
    rank_field:Id|None=None
    rank_direction:Literal['ascending','descending']='descending'
    @model_validator(mode='after')
    def sources(self):
        ids=self.resource_source_ids;selected=[s.resource_source_id for s in self.structure_selections]
        if len(ids)!=len(set(ids)) or len(selected)!=len(set(selected)) or set(selected)-set(ids):raise ValueError('feature_source_selection_invalid')
        return self
