from datetime import date
from typing import Literal
from pydantic import Field,model_validator
from .contracts import Strict,Manuscript

WORKFLOW='journal_adaptation_v1'
class FixedManuscript(Manuscript):
    version_id:str=Field(min_length=1,max_length=64)
class PreviewRequest(Strict):
    target_id:str=Field(min_length=1,max_length=64)
    check_id:str=Field(min_length=1,max_length=64)
    manuscript:FixedManuscript
class AdaptationRequest(PreviewRequest):
    expected_current_revision:int=Field(strict=True,ge=1)
    preview_sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
    selected_action_ids:list[str]=Field(min_length=1,max_length=30)
    @model_validator(mode='after')
    def unique(self):
        if len(set(self.selected_action_ids))!=len(self.selected_action_ids):raise ValueError('Repeated action')
        return self
class AdaptationInputVersion(Strict):
    kind:Literal['journal_adaptation']='journal_adaptation'
    adaptation_id:str
    target_id:str
    check_id:str
    manuscript_version_id:str
    requirements_version:str
    workflow_version:Literal['journal_adaptation_v1']=WORKFLOW
class SubmissionRequest(Strict):
    target_id:str=Field(min_length=1,max_length=64)
    status:Literal['submitted','revision','accepted','published','withdrawn','not_recorded']
    event_date:date
    note:str=Field(default='',max_length=4000)
    manuscript:FixedManuscript|None=None
    export_id:str|None=None
    corrects_event_id:str|None=None
