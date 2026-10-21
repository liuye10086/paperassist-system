from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

WORKFLOW='manuscript_fact_draft_v1'
METHOD_FIELDS=('research_question','purpose','hypothesis','study_design','population','samples','groups','materials','procedures','conditions','statistical_methods','ethics')
MethodField=Literal['research_question','purpose','hypothesis','study_design','population','samples','groups','materials','procedures','conditions','statistical_methods','ethics']
SourceKind=Literal['original','document_version','ocr_review_version','external_evidence_version','analysis_run','figure','figure_language_version']
Role=Literal['methods','user_results','literature','image_observation','computed_results']

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)

class SourceSelection(Strict):
    kind: SourceKind
    id:str=Field(min_length=1,max_length=100)
    file_id:str=Field(min_length=1,max_length=100)
    role:Role

    @model_validator(mode='after')
    def origin_gate(self):
        if (self.role=='computed_results') != (self.kind=='analysis_run'):
            raise ValueError('Only saved computation can be computed results.')
        if self.kind in ('figure','figure_language_version') and self.role!='image_observation':
            raise ValueError('Figures are observations only.')
        return self

class Methods(Strict):
    research_question:str=Field(default='',max_length=6000)
    purpose:str=Field(default='',max_length=6000)
    hypothesis:str=Field(default='',max_length=6000)
    study_design:str=Field(default='',max_length=6000)
    population:str=Field(default='',max_length=6000)
    samples:str=Field(default='',max_length=6000)
    groups:str=Field(default='',max_length=6000)
    materials:str=Field(default='',max_length=6000)
    procedures:str=Field(default='',max_length=6000)
    conditions:str=Field(default='',max_length=6000)
    statistical_methods:str=Field(default='',max_length=6000)
    ethics:str=Field(default='',max_length=6000)

class MethodConflict(Strict):
    field:MethodField
    values:list[str]=Field(min_length=2,max_length=10)
    note:str=Field(default='',max_length=3000)

class ResultGroup(Strict):
    id:str=Field(min_length=1,max_length=100,pattern=r'^[A-Za-z0-9_-]+$')
    title:str=Field(min_length=1,max_length=200)
    analysis_run_ids:list[str]=Field(default_factory=list,max_length=30)
    figure_ids:list[str]=Field(default_factory=list,max_length=30)

class CitationDraft(Strict):
    id:str=Field(min_length=1,max_length=100)
    revision:int=Field(ge=1)

class Panel(Strict):
    label:str=Field(min_length=1,max_length=30)
    description:str=Field(min_length=1,max_length=2000)

class FigureNote(Strict):
    figure_id:str=Field(min_length=1,max_length=100)
    caption:str=Field(default='',max_length=6000)
    panels:list[Panel]=Field(default_factory=list,max_length=26)

class ManuscriptRequest(Strict):
    title:str=Field(min_length=1,max_length=200)
    output_language:Literal['zh-CN','en']
    expected_revision:int=Field(default=0,ge=0)
    sources:list[SourceSelection]=Field(default_factory=list,max_length=50)
    methods:Methods=Field(default_factory=Methods)
    method_source_ids:dict[MethodField,list[str]]=Field(default_factory=dict)
    method_conflicts:list[MethodConflict]=Field(default_factory=list,max_length=12)
    results_groups:list[ResultGroup]=Field(default_factory=list,max_length=20)
    figure_notes:list[FigureNote]=Field(default_factory=list,max_length=50)
    citation_draft:CitationDraft|None=None

    @model_validator(mode='after')
    def unique_inputs(self):
        for ids in ([s.id for s in self.sources],[g.id for g in self.results_groups],
                    [f.figure_id for f in self.figure_notes],[c.field for c in self.method_conflicts]):
            if len(ids)!=len(set(ids)): raise ValueError('Duplicate input identities.')
        selected={s.id for s in self.sources}
        if any(g.id=='source-observations' for g in self.results_groups): raise ValueError('Reserved observation group identity.')
        if any(not set(ids)<=selected for ids in self.method_source_ids.values()):
            raise ValueError('Method sources must be selected.')
        return self

class EmptyRequest(Strict):
    pass

class ManuscriptInputVersion(Strict):
    kind:Literal['manuscript']
    manuscript_version_id:str
    output_language:Literal['zh-CN','en']
    workflow_version:Literal['manuscript_fact_draft_v1']
