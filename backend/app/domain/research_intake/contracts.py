"""Strict version-one research intake contracts; unknown is an explicit state."""
from typing import Literal
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, model_validator

DeliveryKind = Literal['analysis','sci_draft','thesis_draft']


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)


class DeclaredText(StrictModel):
    state: Literal['known','pending','not_applicable'] = 'pending'
    value: str | None = Field(default=None,max_length=4000)

    @model_validator(mode='after')
    def coherent(self):
        if self.state == 'known' and not (self.value and self.value.strip()):
            raise ValueError('Known values need explicit text')
        if self.state != 'known' and self.value is not None:
            raise ValueError('Pending and inapplicable values are null')
        return self


def pending():
    return DeclaredText()


class Contact(StrictModel):
    alias: DeclaredText = Field(default_factory=pending)
    email: DeclaredText = Field(default_factory=pending)
    phone: DeclaredText = Field(default_factory=pending)
    organization: DeclaredText = Field(default_factory=pending)
    discipline: DeclaredText = Field(default_factory=pending)
    filled_date: DeclaredText = Field(default_factory=pending)

    @model_validator(mode='after')
    def lengths(self):
        for key, maximum in {'alias':200,'email':320,'phone':64,'organization':500,'discipline':500,'filled_date':40}.items():
            if len(getattr(self,key).value or '') > maximum:
                raise ValueError(f'{key} exceeds {maximum} characters')
        return self


class Progress(StrictModel):
    stages: list[Literal['protocol','raw_data','report','figures','manuscript','feedback']] = Field(default_factory=list,max_length=6)
    notes: str = Field(default='',max_length=10000)


class ScopeItem(StrictModel):
    id: str = Field(min_length=1,max_length=128)
    title: str = Field(min_length=1,max_length=500)
    delivery_kind: DeliveryKind
    status: Literal['planned','completed','pending_review','not_included'] = 'planned'
    source: str = Field(default='',max_length=4000)


class Schedule(StrictModel):
    first_delivery: DeclaredText = Field(default_factory=pending)
    final_delivery: DeclaredText = Field(default_factory=pending)
    priority: DeclaredText = Field(default_factory=pending)

    @model_validator(mode='after')
    def timezone_required(self):
        for field in ('first_delivery','final_delivery'):
            value = getattr(self,field)
            if value.state == 'known':
                moment = datetime.fromisoformat(value.value.replace('Z','+00:00'))
                if moment.tzinfo is None or moment.utcoffset() is None:
                    raise ValueError('Delivery timestamps require a timezone')
        return self


class AnalysisRequest(StrictModel):
    data_type: DeclaredText = Field(default_factory=pending)
    starting_point: DeclaredText = Field(default_factory=pending)
    core_question: DeclaredText = Field(default_factory=pending)
    expected_analysis: DeclaredText = Field(default_factory=pending)
    focus_objects: list[str] = Field(default_factory=list,max_length=100)
    comparisons: DeclaredText = Field(default_factory=pending)
    existing_standards: DeclaredText = Field(default_factory=pending)
    notes: str = Field(default='',max_length=10000)


class FigureRequest(StrictModel):
    required_figures: list[str] = Field(default_factory=list,max_length=100)
    strategy: Literal['original','redraw','mixed','pending'] = 'pending'
    existing_file_ids: list[str] = Field(default_factory=list,max_length=100)
    specifications: DeclaredText = Field(default_factory=pending)


class SciRequest(StrictModel):
    journal: DeclaredText = Field(default_factory=pending)
    candidates: list[str] = Field(default_factory=list,max_length=100)
    positioning: DeclaredText = Field(default_factory=pending)
    length: DeclaredText = Field(default_factory=pending)
    abstract: DeclaredText = Field(default_factory=pending)
    figure_table_limits: DeclaredText = Field(default_factory=pending)
    storyline: DeclaredText = Field(default_factory=pending)
    research_declaration: DeclaredText = Field(default_factory=pending)
    references: DeclaredText = Field(default_factory=pending)
    terminology: DeclaredText = Field(default_factory=pending)


class ThesisRequest(StrictModel):
    school: DeclaredText = Field(default_factory=pending)
    college: DeclaredText = Field(default_factory=pending)
    major: DeclaredText = Field(default_factory=pending)
    degree: DeclaredText = Field(default_factory=pending)
    template: DeclaredText = Field(default_factory=pending)
    word_count: DeclaredText = Field(default_factory=pending)
    deadline: DeclaredText = Field(default_factory=pending)
    chapters: DeclaredText = Field(default_factory=pending)
    included_work: DeclaredText = Field(default_factory=pending)
    excluded_work: DeclaredText = Field(default_factory=pending)
    language: DeclaredText = Field(default_factory=pending)


MaterialPurpose = Literal['protocol','sample_sheet','raw_data','existing_results','figures','other']


class MaterialChecklistItem(StrictModel):
    purpose: MaterialPurpose
    availability: Literal['provided','pending','none']
    note: str = Field(default='',max_length=4000)


class RequirementContent(StrictModel):
    schema_version: Literal[1]
    contact: Contact = Field(default_factory=Contact)
    services: list[DeliveryKind] = Field(default_factory=list,max_length=3)
    progress: Progress = Field(default_factory=Progress)
    scope_items: list[ScopeItem] = Field(default_factory=list,max_length=100)
    schedule: Schedule = Field(default_factory=Schedule)
    analysis_request: AnalysisRequest = Field(default_factory=AnalysisRequest)
    figure_request: FigureRequest = Field(default_factory=FigureRequest)
    sci_request: SciRequest = Field(default_factory=SciRequest)
    thesis_request: ThesisRequest = Field(default_factory=ThesisRequest)
    material_checklist: list[MaterialChecklistItem] = Field(default_factory=list,max_length=6)
    notes: str = Field(default='',max_length=10000)

    @model_validator(mode='after')
    def unique(self):
        for values in (self.services,[x.id for x in self.scope_items],[x.purpose for x in self.material_checklist]):
            if len(values) != len(set(values)):
                raise ValueError('Duplicate identities are not allowed')
        return self


class Experiment(StrictModel):
    id: str = Field(min_length=1,max_length=128)
    data_type: str = Field(min_length=1,max_length=200)
    species: DeclaredText = Field(default_factory=pending)
    tissue: DeclaredText = Field(default_factory=pending)
    model: DeclaredText = Field(default_factory=pending)
    technology: DeclaredText = Field(default_factory=pending)
    reference: DeclaredText = Field(default_factory=pending)
    processing_stage: DeclaredText = Field(default_factory=pending)
    source: DeclaredText = Field(default_factory=pending)


class Group(StrictModel):
    id: str = Field(min_length=1,max_length=128)
    experiment_id: str = Field(min_length=1,max_length=128)
    name: str = Field(min_length=1,max_length=500)
    abbreviation: str = Field(default='',max_length=100)
    meaning: str = Field(default='',max_length=4000)


class Sample(StrictModel):
    id: str = Field(min_length=1,max_length=128)
    experiment_id: str = Field(min_length=1,max_length=128)
    group_id: str = Field(min_length=1,max_length=128)
    donor: DeclaredText = Field(default_factory=pending)
    tissue: DeclaredText = Field(default_factory=pending)
    section: DeclaredText = Field(default_factory=pending)
    batch: DeclaredText = Field(default_factory=pending)
    time: DeclaredText = Field(default_factory=pending)
    dose: DeclaredText = Field(default_factory=pending)
    sex: DeclaredText = Field(default_factory=pending)
    age: DeclaredText = Field(default_factory=pending)
    file_id: str | None = Field(default=None,max_length=128)
    bio_dataset_version_id: str | None = Field(default=None,max_length=128)


class Observation(StrictModel):
    statistical_unit: DeclaredText = Field(default_factory=pending)
    biological_replicate: DeclaredText = Field(default_factory=pending)
    technical_replicate: DeclaredText = Field(default_factory=pending)
    structure: Literal['pending','independent','paired','repeated','time','dose'] = 'pending'


class Comparison(StrictModel):
    id: str = Field(min_length=1,max_length=128)
    experiment_id: str = Field(min_length=1,max_length=128)
    group_id: str = Field(min_length=1,max_length=128)
    reference_group_id: str = Field(min_length=1,max_length=128)
    positive_meaning: DeclaredText = Field(default_factory=pending)
    effect_threshold: DeclaredText = Field(default_factory=pending)
    p_value: DeclaredText = Field(default_factory=pending)
    adjusted_p_value: DeclaredText = Field(default_factory=pending)
    standard_source: DeclaredText = Field(default_factory=pending)


class DatasetLink(StrictModel):
    id: str = Field(min_length=1,max_length=128)
    relationship: Literal['same_sample','same_individual_different_tissue','independent','partial','pending']
    sample_ids: list[str] = Field(default_factory=list,max_length=10000)
    note: str = Field(default='',max_length=4000)


class Declarations(StrictModel):
    confirmed_by: DeclaredText = Field(default_factory=pending)
    version: DeclaredText = Field(default_factory=pending)
    known_gaps: list[str] = Field(default_factory=list,max_length=100)
    source: DeclaredText = Field(default_factory=pending)


class DesignContent(StrictModel):
    schema_version: Literal[1]
    experiments: list[Experiment] = Field(default_factory=list,max_length=50)
    groups: list[Group] = Field(default_factory=list,max_length=500)
    samples: list[Sample] = Field(default_factory=list,max_length=10000)
    observation: Observation = Field(default_factory=Observation)
    comparisons: list[Comparison] = Field(default_factory=list,max_length=100)
    exclusions: list[str] = Field(default_factory=list,max_length=100)
    cross_dataset_links: list[DatasetLink] = Field(default_factory=list,max_length=100)
    declarations: Declarations = Field(default_factory=Declarations)

    @model_validator(mode='after')
    def coherent(self):
        for values in (self.experiments,self.groups,self.samples,self.comparisons,self.cross_dataset_links):
            if len({x.id for x in values}) != len(values):
                raise ValueError('Duplicate identities are not allowed')
        experiments = {x.id for x in self.experiments}
        groups = {x.id:x.experiment_id for x in self.groups}
        for group in self.groups:
            if group.experiment_id not in experiments:
                raise ValueError('Unknown experiment')
        for item in [*self.samples,*self.comparisons]:
            if item.experiment_id not in experiments or groups.get(item.group_id) != item.experiment_id:
                raise ValueError('Group and experiment must match')
        for item in self.comparisons:
            if groups.get(item.reference_group_id) != item.experiment_id or item.group_id == item.reference_group_id:
                raise ValueError('Invalid comparison reference group')
        samples = {x.id for x in self.samples}
        if any(sample not in samples for link in self.cross_dataset_links for sample in link.sample_ids):
            raise ValueError('Unknown linked sample')
        return self


class MaterialRef(StrictModel):
    delivery_id: str | None = Field(default=None,max_length=128)
    file_id: str | None = Field(default=None,max_length=128)
    bio_dataset_version_id: str | None = Field(default=None,max_length=128)
    locator: str | None = Field(default=None,max_length=4000)
    availability: Literal['provided','pending','none']
    purpose: str = Field(min_length=1,max_length=200)
    note: str = Field(default='',max_length=4000)

    @model_validator(mode='after')
    def coherent(self):
        count = sum(x is not None for x in (self.file_id,self.bio_dataset_version_id))
        if count != (1 if self.availability == 'provided' else 0):
            raise ValueError('Provided material needs exactly one persisted object; pending/none cannot bind an object')
        return self


class RequirementWrite(StrictModel):
    expected_revision: int = Field(ge=1)
    operation: Literal['save','confirm']
    content: RequirementContent
    material_refs: list[MaterialRef] = Field(default_factory=list,max_length=500)


class DesignWrite(StrictModel):
    expected_revision: int = Field(ge=1)
    operation: Literal['save','confirm']
    content: DesignContent
    material_refs: list[MaterialRef] = Field(default_factory=list,max_length=1000)


class DesignTablePreview(StrictModel):
    format: Literal['csv','tsv'] | None = None
    text: str | None = Field(default=None,max_length=2097152)
    file_id: str | None = Field(default=None,min_length=1,max_length=128)
    sheet: int | str = 0
    mapping: dict[str,str]
    experiment_id: str = Field(min_length=1,max_length=128)
    group_ids: list[str] = Field(max_length=500)

    @model_validator(mode='after')
    def source_shape(self):
        if (self.file_id is None)==(self.text is None):
            raise ValueError('Supply exactly one stored file or inline text')
        if self.text is not None and self.format is None:
            raise ValueError('Inline text requires csv/tsv format')
        if isinstance(self.sheet,int) and not 0<=self.sheet<50:
            raise ValueError('Sheet index out of range')
        if isinstance(self.sheet,str) and not 1<=len(self.sheet)<=100:
            raise ValueError('Sheet name invalid')
        if not 2<=len(self.mapping)<=10 or any(not value or len(value)>500 for value in self.mapping.values()):
            raise ValueError('Invalid mapping')
        return self
