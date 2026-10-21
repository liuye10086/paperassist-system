from typing import Literal
from pydantic import Field, model_validator
from app.domain.manuscripts.contracts import Strict, SourceSelection

RULES_VERSION = 'manuscript-review-v1'

class Decision(Strict):
    target_id: str = Field(min_length=1, max_length=300)
    status: Literal['supplied','selected','pending','not_applicable']
    value: str = Field(default='', max_length=6000)
    reason: str = Field(min_length=1, max_length=3000)
    evidence: str = Field(default='', max_length=6000)

    @model_validator(mode='after')
    def evidence_required(self):
        if not self.reason.strip() or self.status in ('supplied','selected') and (not self.value.strip() or not self.evidence.strip()):
            raise ValueError('A supplied/selected value requires explicit evidence and reason')
        return self

class Metadata(Strict):
    target_id: str = Field(min_length=1, max_length=500)
    field: Literal['unit','display_precision','object','group','acronym','statistical_mark','error_bar']
    value: str = Field(min_length=1, max_length=2000)
    evidence: str = Field(min_length=1, max_length=6000)

    @model_validator(mode='after')
    def validate_evidence(self):
        if not self.evidence.strip() or not self.value.strip(): raise ValueError('Metadata evidence is required')
        if self.field=='display_precision' and self.value not in {str(n) for n in range(13)}: raise ValueError('Precision must be 0..12')
        return self

class Association(Strict):
    id: str = Field(min_length=1, max_length=100)
    research_question: str = Field(min_length=1, max_length=6000)
    method_ids: list[str] = Field(default_factory=list, max_length=100)
    source_ids: list[str] = Field(default_factory=list, max_length=100)
    paragraph_ids: list[str] = Field(default_factory=list, max_length=100)
    figure_ids: list[str] = Field(default_factory=list, max_length=100)
    evidence: str = Field(min_length=1, max_length=6000)

class NumericBinding(Strict):
    fact_id: str = Field(min_length=1, max_length=1000)
    value: str = Field(min_length=1, max_length=100)

class Correction(Strict):
    paragraph_id: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=12000)
    source_ids: list[str] = Field(default_factory=list, max_length=50)
    numeric_bindings: list[NumericBinding] = Field(default_factory=list, max_length=200)

class ReviewRequest(Strict):
    base_revision: int = Field(ge=1)
    decisions: list[Decision] = Field(default_factory=list, max_length=100)
    metadata: list[Metadata] = Field(default_factory=list, max_length=200)
    associations: list[Association] = Field(default_factory=list, max_length=100)
    corrections: list[Correction] = Field(default_factory=list, max_length=100)
    selected_sources: list[SourceSelection] = Field(default_factory=list, max_length=50)

    @model_validator(mode='after')
    def unique(self):
        for ids in ([d.target_id for d in self.decisions],[(m.target_id,m.field) for m in self.metadata], [a.id for a in self.associations], [c.paragraph_id for c in self.corrections], [s.id for s in self.selected_sources]):
            if len(ids)!=len(set(ids)): raise ValueError('Duplicate review input identity')
        return self

class PublishRequest(Strict):
    expected_revision: int = Field(ge=1)
