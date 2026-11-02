"""Strict identifiers-only delivery inputs."""
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)

class FigureMapping(Strict):
    figure_number:str=Field(min_length=1,max_length=80)
    panel_order:list[str]=Field(default_factory=list,max_length=100)
    caption:str=Field(default='',max_length=8000)
    confirmed:bool=False

class Selection(Strict):
    kind:Literal['manuscript_export','pdf_export','research_report_member','research_figure_member','file']
    version_id:str|None=None
    member_id:str|None=None
    export_id:str|None=None
    manuscript_id:str|None=None
    file_id:str|None=None
    figure_mapping:FigureMapping|None=None

    @model_validator(mode='after')
    def exact_ids(self):
        required={'file':{'file_id'},'pdf_export':{'export_id'},'manuscript_export':{'export_id','version_id','manuscript_id'},'research_report_member':{'version_id','member_id'},'research_figure_member':{'version_id','member_id'}}[self.kind]
        if {k for k in ('version_id','member_id','export_id','manuscript_id','file_id') if getattr(self,k) is not None}!=required:raise ValueError('Exact source identifiers required')
        return self

class NewSelection(Selection):
    kind:Literal['manuscript_export','research_report_member','research_figure_member','file']


class SnapshotWrite(Strict):
    stage:Literal['first','revision','final']
    parent_snapshot_id:str|None=None
    expected_revision:int=Field(ge=0)
    requirement_version_id:str
    change_note:str=Field(min_length=1,max_length=8000)
    opinion_round:str=Field(min_length=1,max_length=200)
    opinion_round_id:str|None=None
    opinion_round_event_id:str|None=None
    mode:Literal['complete','blind']='complete'
    required_formats:list[str]=Field(default_factory=list,max_length=30)
    quality_items:list[str]=Field(default_factory=list,max_length=100)
    members:list[NewSelection]=Field(min_length=1,max_length=200)

class AcceptanceWrite(Strict):
    snapshot_sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    kind:Literal['accept','correction']
    scope:str=Field(min_length=1,max_length=8000)
    reservations:str=Field(max_length=8000)
    comment:str=Field(min_length=1,max_length=8000)
    customer_reply:str|None=Field(default=None,max_length=16000)
    corrects_event_id:str|None=None
