"""Single-cell composition on a fixed processed axis and manual annotation."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier=Annotated[str,Field(min_length=1,max_length=200,pattern=r'^[^/\\\x00-\x1f]+$')]

class SingleCellSelection(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid',frozen=True)
    processed_source_id: Identifier
    annotation_source_id: Identifier
    label_ids: list[Identifier]=Field(min_length=1,max_length=100)
    labels_confirmed: bool=False
    label_basis: str=Field(default='',max_length=4000)

    @model_validator(mode='after')
    def unique_labels(self):
        if len(set(self.label_ids))!=len(self.label_ids):raise ValueError('duplicate_label_ids')
        return self

class SingleCellCompositionConfig(SingleCellSelection):
    kind: Literal['comparison']='comparison'
    schema_version: Literal[5]=5
    method: Literal['single_cell_composition']='single_cell_composition'
    output_language: Literal['zh-CN','en']='zh-CN'
    mode: Literal['descriptive','donor_unpaired','donor_paired']='descriptive'
    numerator: Identifier
    denominator: Identifier
    mapping_confirmed: bool=False
    independence_confirmed: bool=False
    independence_basis: str=Field(default='',max_length=4000)
    batch_adjustment: bool=False
    transform: Literal['asin']='asin'
    purpose: str=Field(default='',max_length=4000)

    @model_validator(mode='after')
    def direction(self):
        if self.mode!='descriptive' and self.numerator==self.denominator:raise ValueError('composition_conditions_equal')
        if self.mode=='donor_paired' and self.batch_adjustment:raise ValueError('paired_model_supports_donor_condition_only')
        return self
