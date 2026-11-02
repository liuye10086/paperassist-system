"""User-provided presentation metadata; never an alternative body editing path."""
from typing import Literal
from pydantic import Field, model_validator
from .contracts import Strict, SchoolExportOptions
from app.domain.manuscript_writing.language_contracts import SchoolLanguageDecision

class ParagraphGroup(Strict):
    id:str=Field(min_length=1,max_length=100)
    zh_ids:list[str]=Field(default_factory=list,max_length=100)
    en_ids:list[str]=Field(default_factory=list,max_length=100)
    status:Literal['paired','missing','unpaired']='paired'
    @model_validator(mode='after')
    def shape(self):
        if not self.zh_ids and not self.en_ids:raise ValueError('Empty paragraph group')
        if self.status=='paired' and (not self.zh_ids or not self.en_ids):raise ValueError('Paired group requires both languages')
        if len(self.zh_ids)>1 and len(self.en_ids)>1:raise ValueError('Split N:N into explicit paragraph groups')
        if any(len(v)!=len(set(v)) or any(not x for x in v) for v in (self.zh_ids,self.en_ids)):raise ValueError('Duplicate paragraph identities')
        return self

class Term(Strict):
    zh:str=Field(min_length=1,max_length=300)
    en:str=Field(min_length=1,max_length=300)
    variants:list[str]=Field(default_factory=list,max_length=30)
    source:str=Field(default='',max_length=2000)
    state:Literal['known','pending']='pending'
    @model_validator(mode='after')
    def evidence(self):
        if any(not value.strip() for value in self.variants):raise ValueError('Terminology variants must not be blank')
        if self.state=='known' and not self.source.strip():raise ValueError('Known terminology requires source')
        return self

class FigurePair(Strict):
    figure_id:str=Field(min_length=1,max_length=200)
    zh_figure_id:str=Field(min_length=1,max_length=200)
    en_figure_id:str=Field(min_length=1,max_length=200)
    caption_identity:str=Field(min_length=1,max_length=300)
    source:str=Field(default='',max_length=2000)
    language_status:Literal['known','pending']='pending'

class Supplement(Strict):
    chapter_id:str=Field(min_length=1,max_length=300)
    purpose:Literal['abbreviations','appendix','achievements','acknowledgements']
    required:bool=True
    source:str=Field(default='',max_length=2000)

class LengthRequirement(Strict):
    kind:Literal['minimum','maximum']
    value:int=Field(ge=0,le=10000000)
    scope:Literal['body','abstract','whole']
    language:Literal['zh-CN','en']
    unit:Literal['words','characters']
    source:str=Field(min_length=1,max_length=2000)

class SchoolPresentation(Strict):
    options:SchoolExportOptions=Field(default_factory=SchoolExportOptions)
    supplements:list[Supplement]=Field(default_factory=list,max_length=300)
    include_chapter_ids:list[str]=Field(default_factory=list,max_length=300)
    exclude_chapter_ids:list[str]=Field(default_factory=list,max_length=300)
    length_requirements:list[LengthRequirement]=Field(default_factory=list,max_length=30)
    guide_version_id:str|None=None

class Affiliation(Strict):
    id:str=Field(min_length=1,max_length=100)
    name:str=Field(min_length=1,max_length=1000)
    source:str=Field(min_length=1,max_length=2000)

class Author(Strict):
    name:str=Field(min_length=1,max_length=300)
    order:int=Field(ge=1,le=500)
    corresponding:bool=False
    affiliation_ids:list[str]=Field(default_factory=list,max_length=30)
    source:str=Field(min_length=1,max_length=2000)

STATEMENT_KINDS=('funding','ethics','registration','conflict','data_availability')
class Statement(Strict):
    kind:Literal['funding','ethics','registration','conflict','data_availability']
    state:Literal['known','pending','not_applicable']='pending'
    text:str=Field(default='',max_length=30000)
    source:str=Field(default='',max_length=2000)
    reason:str=Field(default='',max_length=3000)
    @model_validator(mode='after')
    def evidence(self):
        if self.state=='known' and (not self.text.strip() or not self.source.strip()):raise ValueError('Known statement requires supplied text and source')
        if self.state=='not_applicable' and (not self.reason.strip() or not self.source.strip()):raise ValueError('Not applicable requires reason and source')
        return self

class BlindException(Strict):
    term:str=Field(min_length=1,max_length=300)
    reason:str=Field(min_length=1,max_length=3000)
class BlindOptions(Strict):
    identity_terms:list[str]=Field(default_factory=list,max_length=500)
    hidden_chapter_ids:list[str]=Field(default_factory=list,max_length=300)
    exceptions:list[BlindException]=Field(default_factory=list,max_length=100)
    manual_image_review:bool=False
    @model_validator(mode='after')
    def valid_terms(self):
        if any(not s.strip() or len(s)>300 for s in self.identity_terms):raise ValueError('Identity terms must be explicit nonempty strings')
        if len(self.identity_terms)!=len(set(self.identity_terms)):raise ValueError('Duplicate identity terms')
        if not {s.term for s in self.exceptions}<=set(self.identity_terms):raise ValueError('Blind exception must identify an explicit identity term')
        return self

class PresentationLanguageReview(Strict):
    source_export_id:str=Field(min_length=1,max_length=100)
    source_sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
    language_view:Literal['zh-CN','en','zh-CN-en']
    review_mode:Literal['identified','blind']
    decisions:list[SchoolLanguageDecision]=Field(min_length=1,max_length=10000)

class PresentationConfig(Strict):
    language_review:PresentationLanguageReview|None=None
    guide_version_id:str|None=None
    paragraph_groups:list[ParagraphGroup]=Field(default_factory=list,max_length=1000)
    terminology:list[Term]=Field(default_factory=list,max_length=500)
    figure_pairs:list[FigurePair]=Field(default_factory=list,max_length=300)
    school:SchoolPresentation|None=None
    authors:list[Author]=Field(default_factory=list,max_length=500)
    affiliations:list[Affiliation]=Field(default_factory=list,max_length=500)
    statements:list[Statement]=Field(default_factory=list,max_length=5)
    blind:BlindOptions=Field(default_factory=BlindOptions)
    @model_validator(mode='after')
    def identities(self):
        if self.guide_version_id and self.school and self.school.guide_version_id and self.guide_version_id!=self.school.guide_version_id:raise ValueError('Conflicting fixed guide identities')
        for items,key in ((self.paragraph_groups,'id'),(self.authors,'order'),(self.affiliations,'id'),(self.statements,'kind'),(self.figure_pairs,'figure_id')):
            ids=[getattr(i,key) for i in items]
            if len(ids)!=len(set(ids)):raise ValueError('Duplicate presentation identity')
        if sorted(a.order for a in self.authors)!=list(range(1,len(self.authors)+1)):raise ValueError('Author order must be contiguous')
        affiliations={a.id for a in self.affiliations}
        if any(not set(a.affiliation_ids)<=affiliations for a in self.authors):raise ValueError('Unknown affiliation')
        for key in ('zh_ids','en_ids'):
            ids=[i for g in self.paragraph_groups for i in getattr(g,key)]
            if len(ids)!=len(set(ids)):raise ValueError('Paragraph belongs to multiple groups')
        return self

class PresentationRequest(Strict):
    expected_revision:int=Field(default=0,ge=0)
    base_version_id:str=Field(min_length=1,max_length=100)
    peer_version_id:str|None=None
    config:PresentationConfig=Field(default_factory=PresentationConfig)
    @model_validator(mode='after')
    def distinct(self):
        if self.peer_version_id==self.base_version_id:raise ValueError('Peer must be a distinct fixed version')
        return self
