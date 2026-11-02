"""Version two consent and raw candidate contracts. Aliases are suggestions only."""
from typing import Literal
from pydantic import Field, field_validator, model_validator
from .contracts import Strict, SectionId, WritingRequest

WORKFLOW = 'manuscript_writing_v2'

class PreviewRequest(WritingRequest):
    schema_version: Literal[2]
    output_language: Literal['en', 'zh-CN']
    selected_source_ids: list[str] = Field(max_length=100)
    selected_evidence_ids: list[str] = Field(max_length=100)

    @model_validator(mode='after')
    def unique_selection(self):
        for selected in (self.selected_source_ids, self.selected_evidence_ids):
            if len(selected) != len(set(selected)): raise ValueError('Duplicate selection')
        if self.target_section == 'references': raise ValueError('References are server constructed')
        return self

class BundleRef(Strict):
    bundle_id: str = Field(min_length=1, max_length=64)
    bundle_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')

class SchoolPreviewRequest(WritingRequest):
    schema_version:Literal[3]
    output_language:Literal['en','zh-CN']
    selected_source_ids:list[str]=Field(max_length=100)
    selected_evidence_ids:list[str]=Field(max_length=100)

    @model_validator(mode='after')
    def unique_school_selection(self):
        if any(len(v)!=len(set(v)) for v in (self.selected_source_ids,self.selected_evidence_ids)):raise ValueError('Duplicate school material selection')
        if self.keywords or self.acknowledgements:raise ValueError('School keywords and acknowledgements remain explicit local export material')
        return self

def preview_data(value):
    model=ArticlePreviewRequest if isinstance(value,dict) and value.get('schema_version')==4 else SchoolPreviewRequest if isinstance(value,dict) and value.get('schema_version')==3 else PreviewRequest
    return model.model_validate(value).model_dump(mode='json') if isinstance(value,dict) else preview_data(value.model_dump(mode='json'))

class LiveWritingRequest(BundleRef):
    schema_version: Literal[2]
    authorization_id: str = Field(min_length=1, max_length=64)
    logical_task_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')

class AuthorizedTask(Strict):
    logical_task_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    bundles: list[BundleRef] = Field(min_length=1, max_length=3)

class AuthorizationRequest(Strict):
    schema_version: Literal[2]
    confirmed: Literal[True]
    tasks: list[AuthorizedTask] = Field(min_length=1, max_length=4)

    @field_validator('confirmed',mode='before')
    @classmethod
    def literal_confirmation(cls,value):
        if value is not True: raise ValueError('Explicit boolean confirmation required')
        return value

    @model_validator(mode='after')
    def unique_tasks(self):
        if len({t.logical_task_id for t in self.tasks}) != len(self.tasks): raise ValueError('Distinct logical tasks required')
        for task in self.tasks:
            if len({b.bundle_id for b in task.bundles}) != len(task.bundles): raise ValueError('Duplicate bundle')
        return self

class StudyNumericBinding(Strict):
    source_alias: str
    fact_path: str
    value: str

class LiveParagraph(Strict):
    id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=10000)
    source_aliases: list[str] = Field(max_length=100)
    evidence_aliases: list[str] = Field(max_length=100)
    study_numeric_bindings: list[StudyNumericBinding] = Field(max_length=1000)

class LiveSection(Strict):
    id: SectionId
    paragraphs: list[LiveParagraph] = Field(max_length=200)

class LiveOutput(Strict):
    sections: list[LiveSection] = Field(min_length=1, max_length=6)


class ParagraphPlan(Strict):
    id:str=Field(min_length=1,max_length=200)
    section_id:str=Field(min_length=1,max_length=200)
    source_paragraph_ids:list[str]=Field(max_length=200)


class BriefLimits(Strict):
    max_words:int|None=Field(default=None,ge=1,le=100000)
    max_figures:int|None=Field(default=None,ge=0,le=1000)


class ArticlePreviewRequest(PreviewRequest):
    """Opt-in W1 only; historical preview dumps and schema3 remain unchanged."""
    schema_version:Literal[4]
    document_kind:Literal['sci','thesis']='sci'
    article_type:Literal['research','brief','narrative_review','methods']='research'
    mode:Literal['full_draft','rewrite_section','results_discussion','expand_restructure','polish']
    target_sections:list[str]=Field(default_factory=list,max_length=300)
    target_paragraph_ids:list[str]=Field(default_factory=list,max_length=1000)
    paragraph_plan:list[ParagraphPlan]=Field(default_factory=list,max_length=1000)
    brief_limits:BriefLimits|None=None
    validation_source_ids:list[str]=Field(default_factory=list,max_length=100)

    @model_validator(mode='after')
    def target_gate(self):
        if (self.mode=='rewrite_section')!=(self.target_section is not None):raise ValueError('A rewrite requires exactly one target section')
        if any(not w.strip() or len(w)>200 for w in self.keywords):raise ValueError('Invalid keywords')
        if self.mode in ('polish','expand_restructure') and not self.target_sections:raise ValueError('Explicit target sections required')
        if self.mode not in ('polish','expand_restructure') and self.target_sections:raise ValueError('Mode derives its section targets')
        if (self.mode=='expand_restructure')!=bool(self.paragraph_plan):raise ValueError('Restructure requires an explicit paragraph plan')
        if self.mode=='full_draft' and self.target_paragraph_ids:raise ValueError('Full draft cannot select paragraph subsets')
        for ids in (self.target_sections,self.target_paragraph_ids,[p.id for p in self.paragraph_plan]):
            if len(ids)!=len(set(ids)):raise ValueError('Duplicate scope identity')
        if self.document_kind=='thesis' and (self.article_type!='research' or self.keywords or self.acknowledgements or self.brief_limits):raise ValueError('School structure and export material remain frozen')
        if self.article_type!='brief' and self.brief_limits is not None:raise ValueError('Brief limits require brief type')
        if self.validation_source_ids and (self.article_type!='methods' or not set(self.validation_source_ids)<=set(self.selected_source_ids) or len(set(self.validation_source_ids))!=len(self.validation_source_ids)):
            raise ValueError('Validation sources must be distinct selected methods-article sources')
        return self
