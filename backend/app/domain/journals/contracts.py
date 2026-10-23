"""Small explicit journal contracts; metrics are deliberately absent."""
from datetime import date
from typing import Literal, Any
from pydantic import BaseModel, ConfigDict, Field, model_validator

WORKFLOW='journal_recommendation_v1'
FIELDS=('topics','scope','article_types','languages','oa','fee','disciplines','unit_requirements','review_duration')
SOURCE_TYPES=('official_local','open_local','user_provided','synthetic')

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')

class Money(Strict):
    amount: float=Field(ge=0,allow_inf_nan=False,strict=True)
    currency: str=Field(pattern=r'^[A-Z]{3}$')

class Applicability(Strict):
    unconditional: bool=False
    article_types: list[str]=Field(default_factory=list,max_length=30)
    oa: bool|None=None

class Evidence(Strict):
    value: Any=None
    status: Literal['verified','unknown','unavailable']='unknown'
    location: str=Field(default='',max_length=2000)
    quote: str=Field(default='',max_length=10000)
    conditions: str=Field(default='',max_length=4000)
    verified_on: date|None=None
    applicability: Applicability|None=None
    @model_validator(mode='after')
    def evidence_required(self):
        if self.status=='verified' and (not self.location.strip() or not self.quote.strip() or self.value is None):
            raise ValueError('Verified fields require a value, quotation and location.')
        if self.status!='verified' and self.value is not None:raise ValueError('Unknown/unavailable fields must keep null values.')
        return self

class Material(Strict):
    kind: Literal['original','document_version','ocr_review_version','external_evidence_version']
    id: str=Field(min_length=1,max_length=64)
    file_id: str=Field(min_length=1,max_length=64)

class ProfileRequest(Strict):
    name: str=Field(min_length=1,max_length=300)
    previous_version_id: str|None=None
    source_type: Literal['official_local','open_local','user_provided','synthetic']
    source_text: str=Field(default='',max_length=60000)
    source_url: str=Field(default='',max_length=2000)
    official_url: str=Field(default='',max_length=2000)
    material: Material|None=None
    source_status: Literal['available','unavailable','expired']='available'
    verified_on: date
    conditions: str=Field(min_length=1,max_length=4000)
    permission: str=Field(min_length=1,max_length=2000)
    fields: dict[str,Evidence]=Field(default_factory=dict,max_length=20)
    @model_validator(mode='after')
    def limited_fields(self):
        from urllib.parse import urlsplit
        if set(self.fields)-set(FIELDS):raise ValueError('SCI/SCIE/JIF/JCR/quartiles and other metrics are disabled; PubMed does not prove SCI.')
        if not self.source_text.strip() and self.material is None:raise ValueError('Source text or local material is required; URL alone is not evidence.')
        for url in (self.source_url,self.official_url):
            if not url:continue
            u=urlsplit(url)
            if u.scheme not in ('http','https') or not u.hostname or u.username or u.password:raise ValueError('Invalid source URL.')
        if self.source_type=='synthetic':
            if 'synthetic' not in self.name.casefold():raise ValueError('Synthetic names must explicitly include synthetic.')
            if any(url and not urlsplit(url).hostname.endswith(('.test','.invalid')) for url in (self.source_url,self.official_url)):raise ValueError('Synthetic URLs must use .test or .invalid.')
        for key,e in self.fields.items():
            if e.status!='verified':continue
            if key=='fee':Money.model_validate(e.value)
            elif key=='oa':
                if not isinstance(e.value,bool):raise ValueError('OA must be boolean.')
            elif key!='review_duration':
                if not isinstance(e.value,list) or not e.value or any(not isinstance(v,str) or not v.strip() for v in e.value):raise ValueError('Tag fields require nonempty string arrays.')
            elif not isinstance(e.value,str):raise ValueError('Duration is a conditional source statement, not a promise.')
        return self

class Manuscript(Strict):
    id: str=Field(min_length=1,max_length=64)
    revision: int=Field(ge=1,strict=True)

class RecommendationRequest(Strict):
    title: str=Field(min_length=1,max_length=1000)
    abstract: str=Field(default='',max_length=20000)
    main_results: str=Field(default='',max_length=20000)
    domain: str=Field(default='',max_length=300)
    topics: list[str]=Field(min_length=1,max_length=30)
    article_type: str=Field(min_length=1,max_length=100)
    discipline: str=Field(default='',max_length=100)
    language: str=Field(default='',max_length=100)
    oa: bool|None=None
    budget: Money|None=None
    unit_requirements: list[str]=Field(default_factory=list,max_length=30)
    hard_filters: list[Literal['article_types','languages','oa','fee','disciplines','unit_requirements']]=Field(default_factory=lambda:['article_types','fee','unit_requirements'],max_length=6)
    materials: list[Material]=Field(default_factory=list,max_length=20)
    manuscript: Manuscript|None=None
    profile_ids: list[str]|None=Field(default=None,max_length=100)
    limit: int=Field(default=3,ge=1,le=5,strict=True)

class JournalInputVersion(Strict):
    kind: Literal['journal_recommendation']='journal_recommendation'
    recommendation_id: str
    workflow_version: Literal['journal_recommendation_v1']=WORKFLOW

class EmptyRequest(Strict):pass
