"""Finite, evidence-backed author-guide and read-only formatting contracts."""
from datetime import date
from typing import Any,Literal
from pydantic import Field,model_validator
from .contracts import Strict,Material,Manuscript
from .display import STYLE_KEYS,validate_style

FORMAT_WORKFLOW='journal_format_check_v1'
CHECK_VERSION=1
RULE_KEYS=('word_limit','required_sections','section_order','abstract_required','abstract_headings','abstract_word_limit','figure_limit','table_limit','figure_captions','table_captions','figure_numbering','table_numbering','figure_references','table_references','reference_style','reference_limit','dpi','section_display_names',*STYLE_KEYS)
COUNT_METHODS=('en_whitespace_body','zh_hanzi_latin_body','en_whitespace_abstract','zh_hanzi_latin_abstract')
STATUSES=('pass','mismatch','pending_verification','manual','unsupported')

class Requirement(Strict):
    id:str=Field(min_length=1,max_length=100)
    key:Literal[*RULE_KEYS]
    value:Any=None
    status:Literal['known','unknown','unsupported']='unknown'
    quote:str=Field(min_length=1,max_length=10000)
    location:str=Field(min_length=1,max_length=2000)
    article_type:str|None=Field(default=None,max_length=100)
    count_method:Literal[*COUNT_METHODS]|None=None
    origin:str=Field(default='journal',min_length=1,max_length=200)
    note:str=Field(default='',max_length=4000)

    @model_validator(mode='after')
    def finite_value(self):
        if not self.quote.strip() or not self.location.strip():raise ValueError('Requirements need exact quotation and location.')
        if self.status=='unknown':
            if self.value is not None:raise ValueError('Unknown requirements must keep null values.')
            return self
        if self.key in STYLE_KEYS:
            validate_style(self.key,self.value)
            import re
            unit=r'(?:multiple|倍)' if self.key.endswith('line_spacing') else r'pt'
            if not re.search(r'(?<![\d.])'+str(self.value).removesuffix('.0')+r'(?:\.0)?\s*'+unit+r'\b',self.quote,re.I):raise ValueError('Explicit numeric value and unit required in original quote')
        elif self.key=='section_display_names':
            from app.domain.manuscript_writing.contracts import SECTION_IDS
            if not isinstance(self.value,list) or len(self.value)!=7 or any(not isinstance(v,dict) or set(v)!= {'section_id','display_name'} or not isinstance(v['display_name'],str) or not v['display_name'].strip() or len(v['display_name'])>300 for v in self.value):raise ValueError('Seven explicit semantic display mappings required')
            if {v['section_id'] for v in self.value}!=set(SECTION_IDS) or len({v['display_name'] for v in self.value})!=7:raise ValueError('Mappings must be one-to-one')
            if any(v['section_id']+'='+v['display_name'] not in self.quote for v in self.value):raise ValueError('Each semantic mapping must be explicit in original quote')
        elif self.key in ('word_limit','abstract_word_limit','figure_limit','table_limit','reference_limit','dpi'):
            valid=type(self.value) is int and 0<=self.value<=1000000
            if isinstance(self.value,dict) and set(self.value)<= {'min','max'} and self.value:
                valid=all(type(v) is int and 0<=v<=1000000 for v in self.value.values()) and self.value.get('min',0)<=self.value.get('max',1000000)
            if not valid:raise ValueError('Counts require a nonnegative integer or finite min/max range.')
        elif self.key in ('required_sections','section_order','abstract_headings'):
            if not isinstance(self.value,list) or not self.value or len(self.value)>100 or any(not isinstance(v,str) or not v.strip() or len(v)>300 for v in self.value):raise ValueError('Explicit heading lists are required.')
        elif self.key=='reference_style':
            if not isinstance(self.value,str) or not self.value.strip() or len(self.value)>200:raise ValueError('Reference style needs an explicit name.')
        elif type(self.value) is not bool:raise ValueError('Presence rules require a boolean.')
        return self

class GuideRequest(Strict):
    profile_id:str=Field(min_length=1,max_length=64)
    name:str=Field(min_length=1,max_length=300)
    previous_version_id:str|None=None
    source_type:Literal['official_local','open_local','user_provided','synthetic']
    source_text:str=Field(default='',max_length=60000)
    material:Material|None=None
    source_url:str=Field(default='',max_length=2000)
    official_url:str=Field(default='',max_length=2000)
    source_version:str=Field(min_length=1,max_length=300)
    acquired_on:date
    verified_on:date
    article_types:list[str]=Field(min_length=1,max_length=30)
    conditions:str=Field(min_length=1,max_length=4000)
    permission:str=Field(min_length=1,max_length=2000)
    permission_status:Literal['allowed','unknown','disallowed']='unknown'
    source_status:Literal['available','unavailable','expired']='available'
    requirements:list[Requirement]=Field(default_factory=list,max_length=200)
    extract:bool=True

    @model_validator(mode='after')
    def evidence_shape(self):
        from urllib.parse import urlsplit
        if not self.source_text.strip() and not self.material:raise ValueError('Guide requires saved local text/material; URL registration does not read a URL.')
        if len({r.id for r in self.requirements})!=len(self.requirements):raise ValueError('Duplicate requirement IDs.')
        if any(not t.strip() for t in self.article_types):raise ValueError('Explicit article types are required.')
        for url in (self.source_url,self.official_url):
            if not url:continue
            u=urlsplit(url)
            if u.scheme not in ('http','https') or not u.hostname or u.username or u.password:raise ValueError('Invalid guide URL.')
            if self.source_type=='synthetic' and not u.hostname.endswith(('.test','.invalid')):raise ValueError('Synthetic URLs must use .test or .invalid.')
        if self.source_type=='synthetic' and 'synthetic' not in self.name.casefold():raise ValueError('Synthetic guide name must include synthetic.')
        return self

class Resolution(Strict):
    key:Literal[*RULE_KEYS]
    requirement_id:str|None=None
    reason:str=Field(min_length=1,max_length=4000)

class TargetRequest(Strict):
    recommendation_id:str=Field(min_length=1,max_length=64)
    profile_id:str=Field(min_length=1,max_length=64)
    guide_id:str=Field(min_length=1,max_length=64)
    additional_guide_ids:list[str]=Field(default_factory=list,max_length=10)
    requirements_version:str=Field(pattern=r'^[0-9a-f]{64}$')
    article_type:str=Field(min_length=1,max_length=100)
    resolutions:list[Resolution]=Field(default_factory=list,max_length=30)

    @model_validator(mode='after')
    def unique(self):
        if len({r.key for r in self.resolutions})!=len(self.resolutions):raise ValueError('Only one finite decision per rule key.')
        if len(set([self.guide_id,*self.additional_guide_ids]))!=1+len(self.additional_guide_ids):raise ValueError('Guide versions must not repeat.')
        return self

class FormatCheckRequest(Strict):
    target_id:str=Field(min_length=1,max_length=64)
    manuscript:Manuscript
    check_version:Literal[1]=1

class FormatInputVersion(Strict):
    kind:Literal['journal_format_check']='journal_format_check'
    check_id:str
    target_id:str
    guide_id:str
    requirements_version:str
    manuscript_version_id:str
    check_version:Literal[1]=1
    workflow_version:Literal['journal_format_check_v1']=FORMAT_WORKFLOW
