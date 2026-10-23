"""Frozen review-round inputs; no model or scientific revision execution."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
WORKFLOW='review_round_plan_v1'
class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')
class ReviewInputVersion(Strict):
    kind:Literal['review_round_plan']='review_round_plan'
    round_id:str
    base_version_id:str
    workflow_version:Literal['review_round_plan_v1']=WORKFLOW
class Segment(Strict):
    start:int=Field(ge=0)
    end:int=Field(ge=1)
    original_number:str=''
class Source(Strict):
    role:Literal['editor','reviewer','advisor','evaluator','defense']
    label:str=Field(min_length=1,max_length=200)
    format:Literal['text','document']
    text:str|None=None
    file_id:str|None=None
    document_version_id:str|None=None
    received_on:str|None=None
    segments:list[Segment]|None=None
class Material(Strict):
    kind:Literal['document_version']
    file_id:str
    id:str
class Manuscript(Strict):
    id:str
    revision:int=Field(ge=1)
    version_id:str
class CreateRequest(Strict):
    title:str=Field(min_length=1,max_length=300)
    project_type:Literal['sci','thesis']
    manuscript:Manuscript
    synthetic:bool
    sources:list[Source]=Field(min_length=1,max_length=100)
    materials:list[Material]=Field(default_factory=list,max_length=100)
    journal_target_id:str|None=None
    school_confirmation_id:str|None=None
    previous_round_id:str|None=None
    user_return_id:str|None=None
class Location(Strict):
    kind:Literal['section','paragraph','figure','table']
    id:str
class Translation(Strict):
    language:Literal['zh-CN','en']
    text:str
class Need(Strict):
    kind:Literal['material','analysis','experiment','literature']
    description:str=Field(min_length=1)
class ItemEdit(Strict):
    id:str
    category:Literal['expression','structure','literature','statistics','figure','method','format','experiment','uncategorized']
    locations:list[Location]
    translation:Translation|None=None
    plan:str
    evidence_ids:list[str]
    needs:list[Need]
    flags:list[Literal['ambiguous','conflict','conclusion_change']]
    conflicting_item_ids:list[str]
    proposed_action:Literal['modify','not_adopt']='modify'
    not_adopt_reason:str=''
class PlansRequest(Strict):
    expected_revision:int=Field(ge=1)
    items:list[ItemEdit]
    materials:list[Material]|None=None
class Decision(Strict):
    item_id:str
    action:Literal['accept','clarify','not_adopt','defer']
    reason:str=''
class DecisionsRequest(Strict):
    expected_revision:int=Field(ge=1)
    decisions:list[Decision]=Field(min_length=1)
