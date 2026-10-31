"""Bounded version-one contracts. Request idempotency remains an HTTP header."""
from typing import Annotated, Literal
import json
import re

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
from app.domain.manuscripts.contracts import ThesisSelection

Identifier = Annotated[str, Field(min_length=1, max_length=200, pattern=r'^[^/\\\x00-\x1f]+$')]
Hash = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
ShortText = Annotated[str, Field(max_length=4000)]
SourceKind = Literal['bio_processed_dataset_version','bio_analysis_artifact','bio_figure_version',
                     'original_file','external_evidence_version','research_finding_version',
                     'research_figure_version','research_report_version',
                     'bio_insight_result_version','bio_insight_result_member']
Language = Literal['zh-CN','en']
Section = Literal['results','materials_and_methods']


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', allow_inf_nan=False)

    @model_validator(mode='after')
    def bounded_document(self):
        if len(self.model_dump_json().encode('utf-8')) > 4 * 1024 * 1024:
            raise ValueError('Research contract exceeds 4 MiB; select fewer sources')
        return self


class ResearchLocator(StrictModel):
    schema_version: Literal[1] = 1
    kind: Literal['object','field','row','cell','page','image'] = 'object'
    field_path: str | None = Field(default=None,min_length=1,max_length=500,
                                  pattern=r'^[A-Za-z0-9_][A-Za-z0-9_.\[\]-]*$')
    row_key: dict[Identifier, Identifier] | None = Field(default=None,min_length=1,max_length=8)
    column: Identifier | None = None
    sheet: str | None = Field(default=None,min_length=1,max_length=100)
    cell: str | None = Field(default=None,pattern=r'^[A-Z]{1,3}[1-9][0-9]{0,6}$')
    page: int | None = Field(default=None,ge=1,le=100000)
    table: str | None = Field(default=None,min_length=1,max_length=200)
    parse_version_id: Identifier | None = None
    original_sha256: Hash | None = None

    @model_validator(mode='after')
    def typed_location(self):
        fields = {key for key in ('field_path','row_key','column','sheet','cell','page','table')
                  if getattr(self,key) is not None}
        required = {'object':set(),'image':set(),'field':{'field_path'},'row':{'row_key','column'},
                    'cell':{'sheet','cell'},'page':{'page'}}[self.kind]
        allowed = required | ({'table'} if self.kind in ('page','row') else set())
        if not required <= fields or not fields <= allowed:
            raise ValueError('Locator fields do not match their kind')
        if self.cell:
            letters = re.match(r'[A-Z]+',self.cell).group()
            index = 0
            for char in letters:
                index = index*26+ord(char)-64
            row = int(self.cell[len(letters):])
            if index>16384 or row>1048576:
                raise ValueError('Cell exceeds XLSX bounds')
        return self


class ResearchSourceSelection(StrictModel):
    schema_version: Literal[1] = 1
    source_kind: SourceKind
    source_id: Identifier
    locator: ResearchLocator = Field(default_factory=ResearchLocator)
    sha256: Hash | None = None


class ResearchFact(StrictModel):
    id: Identifier
    source_kind: SourceKind
    source_id: Identifier
    source_sha256: Hash
    locator: ResearchLocator
    raw_value: str | int | float | bool | None
    raw_type: Literal['string','integer','number','boolean','null'] | None = None
    display_value: str = Field(max_length=1000)
    unit: str = Field(default='',max_length=100)
    observation_level: Literal['spot','region','sample','donor','cell','dataset','unknown'] = 'unknown'
    comparison: str = Field(default='',max_length=1000)
    verification_status: Literal['verified','unverified','conflict','missing','transcribed'] = 'unverified'
    origin: Literal['system_computed','public_reanalysis','external_result','manual_transcription','image_observation'] = 'external_result'
    limitations: list[ShortText] = Field(default_factory=list,max_length=30)

    @model_validator(mode='after')
    def raw_identity(self):
        actual = ('null' if self.raw_value is None else 'boolean' if isinstance(self.raw_value,bool)
                  else 'integer' if isinstance(self.raw_value,int) else 'number' if isinstance(self.raw_value,float) else 'string')
        if self.raw_type is not None and self.raw_type != actual:
            raise ValueError('Raw value and raw type differ')
        if isinstance(self.raw_value,str) and len(self.raw_value)>4000:
            raise ValueError('Raw value is too long')
        self.raw_type = actual
        return self


class ResearchMethod(StrictModel):
    id: Identifier
    title: str = Field(min_length=1,max_length=500)
    description: ShortText = ''
    source: ResearchSourceSelection
    parameters: dict[Identifier, JsonValue] = Field(default_factory=dict,max_length=100)
    software: dict[Identifier, Annotated[str, Field(max_length=200)]] = Field(default_factory=dict,max_length=50)
    executed: bool = True


class FrozenResearchSource(ResearchSourceSelection):
    project_id: Identifier
    sha256: Hash
    title: str = Field(default='',max_length=500)
    provenance: Literal['system_computed','public_reanalysis','external_result','manual_transcription','research_derived']
    content: dict[Identifier, JsonValue] = Field(default_factory=dict,max_length=100)
    source_file_ids: list[Identifier] = Field(default_factory=list,max_length=100)
    methods: list[ResearchMethod] = Field(default_factory=list,max_length=100)
    figures: list[dict[Identifier, JsonValue]] = Field(default_factory=list,max_length=50)


class ResearchFactCatalog(StrictModel):
    schema_version: Literal[1] = 1
    source: FrozenResearchSource
    facts: list[ResearchFact] = Field(default_factory=list,max_length=1000)
    methods: list[ResearchMethod] = Field(default_factory=list,max_length=100)
    gaps: list[ShortText] = Field(default_factory=list,max_length=100)
    warnings: list[ShortText] = Field(default_factory=list,max_length=100)
    limitations: list[ShortText] = Field(default_factory=list,max_length=100)
    conflicts: list[ShortText] = Field(default_factory=list,max_length=100)

    @model_validator(mode='after')
    def unique_catalog(self):
        for values in (self.facts,self.methods):
            if len({item.id for item in values}) != len(values):
                raise ValueError('Duplicate catalog IDs')
        return self


class ResearchClaim(StrictModel):
    id: Identifier
    statement: str = Field(min_length=1,max_length=10000)
    fact_ids: list[Identifier] = Field(default_factory=list,max_length=100)
    figure_refs: list[Identifier] = Field(default_factory=list,max_length=50)
    origin: Literal['system_candidate','user_text','public_reanalysis','external_result','literature'] = 'system_candidate'
    strength: Literal['exploratory','descriptive','supported','unresolved'] = 'exploratory'
    limitations: list[ShortText] = Field(default_factory=list,max_length=30)
    conflicts: list[Identifier] = Field(default_factory=list,max_length=30)
    review_decision: Literal['pending','adopt','exclude','needs_evidence'] = 'pending'


class ResearchConflict(StrictModel):
    id: Identifier
    fact_ids: list[Identifier] = Field(min_length=2,max_length=20)
    note: ShortText = ''
    decision: Literal['unresolved','use_first','use_second','exclude','explained'] = 'unresolved'
    basis: ShortText = ''


class ResearchReview(StrictModel):
    target_id: Identifier
    decision: Literal['checked','adopt','exclude','needs_evidence']
    basis: str = Field(min_length=1,max_length=4000)
    evidence: list[ResearchSourceSelection] = Field(default_factory=list,max_length=20)


class FindingVersionRequest(StrictModel):
    schema_version: Literal[1] = 1
    title: str = Field(min_length=1,max_length=200)
    set_id: Identifier | None = None
    expected_revision: int = Field(default=0,ge=0,lt=2147483647)
    requirement_version_id: Identifier | None = None
    design_version_id: Identifier | None = None
    sources: list[ResearchSourceSelection] = Field(min_length=1,max_length=100)
    selected_fact_ids: list[Identifier] = Field(default_factory=list,max_length=1000)
    claims: list[ResearchClaim] = Field(default_factory=list,max_length=100)
    conflicts: list[ResearchConflict] = Field(default_factory=list,max_length=100)
    reviews: list[ResearchReview] = Field(default_factory=list,max_length=200)
    notes: str = Field(default='',max_length=10000)

    @model_validator(mode='after')
    def root_cas(self):
        if (self.set_id is None) != (self.expected_revision == 0):
            raise ValueError('New set uses revision 0; existing set requires its revision')
        for values in (self.selected_fact_ids,[x.id for x in self.claims],[x.id for x in self.conflicts]):
            if len(values)!=len(set(values)):
                raise ValueError('Duplicate finding identity')
        identities=[json.dumps(x.model_dump(mode='json'),sort_keys=True) for x in self.sources]
        if len(identities)!=len(set(identities)):
            raise ValueError('Duplicate source selection')
        return self


class ResearchFigurePanel(StrictModel):
    source: ResearchSourceSelection
    member_key: Identifier | None = None
    label: str = Field(default='',max_length=8,pattern=r'^[A-Za-z0-9]*$')
    note: ShortText = ''


class ResearchFigureRequest(StrictModel):
    schema_version: Literal[1] = 1
    root_id: Identifier | None = None
    expected_revision: int = Field(default=0,ge=0,lt=2147483647)
    mode: Literal['reuse','composite']
    panels: list[ResearchFigurePanel] = Field(min_length=1,max_length=6)
    title: str = Field(default='',max_length=200)
    caption: str = Field(default='',max_length=10000)
    caption_fact_ids: list[Identifier] = Field(default_factory=list,max_length=100)
    caption_sources: list[ResearchSourceSelection] = Field(default_factory=list,max_length=20)
    language: Language = 'zh-CN'
    figure_language: Literal['zh-CN','en','original','unknown'] = 'original'
    width_mm: float = Field(default=180,ge=85,le=240)
    dpi: Literal[150,300,600] = 300
    columns: int = Field(default=2,ge=1,le=3)
    background: str = Field(default='#ffffff',pattern=r'^#[0-9a-fA-F]{6}$')
    margin_mm: float = Field(default=3,ge=0,le=20)
    font_size_pt: int = Field(default=10,ge=6,le=24)
    formats: list[Literal['png','tiff','pdf','svg']] = Field(default_factory=lambda:['png','tiff'],min_length=1,max_length=4)

    @model_validator(mode='after')
    def figure_identity(self):
        if (self.root_id is None) != (self.expected_revision==0):
            raise ValueError('Figure root requires an expected revision')
        if (self.mode=='reuse' and len(self.panels)!=1) or (self.mode=='composite' and len(self.panels)<2):
            raise ValueError('Reuse needs one panel; composite needs 2 to 6 panels')
        labels=[p.label for p in self.panels if p.label]
        if len(labels)!=len(set(labels)) or len(self.formats)!=len(set(self.formats)):
            raise ValueError('Duplicate panel labels or formats')
        if any(p.source.source_kind not in ('original_file','bio_figure_version','research_figure_version','bio_insight_result_version','bio_insight_result_member') for p in self.panels):
            raise ValueError('Panel requires a fixed image source')
        if round(self.width_mm/25.4*self.dpi)>8000:
            raise ValueError('Figure exceeds 8000 pixel longest edge')
        return self


class ResearchReportRequest(StrictModel):
    schema_version: Literal[1] = 1
    title: str = Field(min_length=1,max_length=200)
    finding_version_id: Identifier
    figure_version_ids: list[Identifier] = Field(default_factory=list,max_length=50)
    language: Language = 'zh-CN'
    root_id: Identifier | None = None
    expected_revision: int = Field(default=0,ge=0,lt=2147483647)
    include_pdf_id: Identifier | None = None

    @model_validator(mode='after')
    def report_identity(self):
        if (self.root_id is None) != (self.expected_revision==0):
            raise ValueError('Report root requires an expected revision')
        if len(self.figure_version_ids)!=len(set(self.figure_version_ids)):
            raise ValueError('Duplicate figure version')
        return self


class ResearchHandoffRequest(StrictModel):
    schema_version: Literal[1] = 1
    delivery_id: Identifier
    finding_version_ids: list[Identifier] = Field(default_factory=list,max_length=100)
    figure_version_ids: list[Identifier] = Field(default_factory=list,max_length=50)
    report_version_ids: list[Identifier] = Field(default_factory=list,max_length=20)
    manuscript_id: Identifier | None = None
    expected_revision: int = Field(default=0,ge=0,lt=2147483647)
    output_language: Language = 'zh-CN'
    thesis: ThesisSelection | None = None
    base_version_id: Identifier | None = None
    sections: list[Section] = Field(default_factory=lambda:['results','materials_and_methods'],min_length=1,max_length=2)
    manual_notes: str = Field(default='',max_length=10000)

    @model_validator(mode='after')
    def handoff_identity(self):
        if not (self.finding_version_ids or self.report_version_ids):
            raise ValueError('Select a fixed finding or report version')
        if (self.manuscript_id is None)!=(self.expected_revision==0):
            raise ValueError('Existing manuscript requires expected revision')
        for ids in (self.finding_version_ids,self.figure_version_ids,self.report_version_ids):
            if len(ids)!=len(set(ids)):
                raise ValueError('Duplicate selected version')
        if len(self.sections)!=len(set(self.sections)):raise ValueError('Duplicate writing section')
        return self


class ResearchCandidateRequest(ResearchHandoffRequest):
    base_version_id: Identifier | None = None
    sections: list[Section] = Field(default_factory=lambda:['results','materials_and_methods'],min_length=1,max_length=2)
    manual_notes: str = Field(default='',max_length=10000)

    @model_validator(mode='after')
    def candidate_scope(self):
        if (self.base_version_id is None)!=(self.manuscript_id is None):
            raise ValueError('Existing candidate needs a paired manuscript and base version')
        if len(self.sections)!=len(set(self.sections)):
            raise ValueError('Duplicate writing section')
        return self


class ResearchPublishRequest(StrictModel):
    schema_version: Literal[1] = 1
    candidate_id: Identifier
    expected_revision: int = Field(ge=0,lt=2147483647)
