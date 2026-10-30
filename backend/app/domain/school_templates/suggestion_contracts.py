"""Separate school advice contracts; no parser or manuscript permissions."""
from typing import Literal
from pydantic import Field, model_validator,field_validator
from .contracts import StrictModel

WORKFLOW='school_rule_suggestion_v1'

class SuggestionPreview(StrictModel):
    analysis_sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
    note_ids:list[str]=Field(min_length=1,max_length=100)

    @model_validator(mode='after')
    def unique(self):
        if len(set(self.note_ids))!=len(self.note_ids):raise ValueError('Duplicate selected notes')
        return self

class SuggestionRequest(SuggestionPreview):
    bundle_sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
    confirmed:Literal[True]

    @field_validator('confirmed',mode='before')
    @classmethod
    def explicit_confirmation(cls,value):
        if value is not True:raise ValueError('Explicit boolean confirmation required')
        return value

class Candidate(StrictModel):
    id:str=Field(min_length=1,max_length=100)
    target_id:str|None
    value:str|None
    note_alias:str=Field(pattern=r'^n[1-9][0-9]*$')
    start:int=Field(ge=0)
    end:int=Field(gt=0)
    quote:str=Field(min_length=1,max_length=10000)
    status:Literal['proposed','unknown','unsupported']
    reason:str=Field(min_length=1,max_length=2000)

class SuggestionDraft(StrictModel):
    candidates:list[Candidate]=Field(min_length=1,max_length=300)

class SuggestionDecision(StrictModel):
    candidate_id:str=Field(min_length=1,max_length=100)
    action:Literal['accept','reject','defer']
    reason:str=Field(min_length=1,max_length=2000)

class SuggestionInputVersion(StrictModel):
    kind:Literal['school_rule_suggestion']='school_rule_suggestion'
    suggestion_id:str
    template_version_id:str
    analysis_sha256:str
    bundle_sha256:str
    workflow_version:Literal['school_rule_suggestion_v1']=WORKFLOW
