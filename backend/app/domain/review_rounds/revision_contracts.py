"""Narrow fixed-plan revision inputs, always local and explicitly adopted."""
from typing import Literal
from pydantic import Field, model_validator
from .contracts import Strict
WORKFLOW='review_revision_v1'
class RevisionInputVersion(Strict):
    kind:Literal['review_revision']='review_revision'
    revision_id:str
    round_id:str
    base_version_id:str
    workflow_version:Literal['review_revision_v1']=WORKFLOW
class Operation(Strict):
    item_id:str
    kind:Literal['replace_paragraph','split_paragraph','reorder_paragraphs','figure_caption','remove_figure','bind_citation','section_title']
    location_id:str
    text:str|None=None
    paragraph_ids:list[str]=Field(default_factory=list)
    evidence_ids:list[str]=Field(default_factory=list)
    numeric_bindings:list['NumericBinding']|None=None
    reason:str=Field(min_length=1,max_length=4000)
class NumericBinding(Strict):
    fact_id:str
    value:str
class RevisionPreview(Strict):
    plan_revision:int=Field(ge=1)
    expected_current_revision:int=Field(ge=1)
    operations:list[Operation]=Field(default_factory=list,max_length=200)
    analysis_adoption_ids:list[str]=Field(default_factory=list,max_length=50)
    figure_adoption_ids:list[str]=Field(default_factory=list,max_length=50)
    @model_validator(mode='after')
    def actual_selection(self):
        if not self.operations and not self.figure_adoption_ids:
            raise ValueError('Select concrete edits or an explicit saved figure adoption.')
        return self
class RevisionAdopt(RevisionPreview):
    preview_sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
