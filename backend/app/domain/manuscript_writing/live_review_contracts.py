"""Exact manual science decisions; neither aliases nor old decisions certify new prose."""
from typing import Literal
from pydantic import Field, field_validator
from .contracts import Strict
from app.domain.literature_citations.contracts import ClaimFragment

class NumericDecision(Strict):
    occurrence: int = Field(ge=0)
    value: str = Field(min_length=1,max_length=100)
    kind: Literal['study','literature','context']
    source_alias: str | None = None
    fact_path: str | None = None
    evidence_id: str | None = None

class ClaimBinding(ClaimFragment):
    kind: Literal['claim'] = 'claim'

class ParagraphDecision(Strict):
    paragraph_id: str = Field(min_length=1,max_length=200)
    text_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    corrected_text: str | None = Field(default=None,min_length=1,max_length=10000)
    classification: Literal['non_claim','study_claim','literature_claim','mixed_claim','context_claim']
    scientific_basis: str = Field(min_length=1,max_length=4000)
    claim: ClaimBinding | None = None
    numeric_bindings: list[NumericDecision] = Field(max_length=1000)

    @field_validator('scientific_basis','corrected_text')
    @classmethod
    def nonempty(cls,value):
        if value is not None and not value.strip(): raise ValueError('Explicit text required')
        return value

class TitleDecision(Strict):
    subject: bool
    direction: bool
    strength: bool
    basis: str = Field(min_length=1,max_length=4000)

class AbstractDecision(Strict):
    objective: bool
    methods: bool
    key_results: bool
    conclusion: bool
    basis: str = Field(min_length=1,max_length=4000)

class ConsistencyDecision(Strict):
    body_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    title: TitleDecision
    abstract: AbstractDecision

class ScientificReviewRequest(Strict):
    schema_version: Literal[2]
    candidate_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    paragraphs: list[ParagraphDecision] = Field(min_length=1,max_length=1200)
    consistency: ConsistencyDecision

class SchoolConsistencyDecision(Strict):
    body_sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
    title:TitleDecision
    abstracts:dict[str,AbstractDecision]

class SchoolScientificReviewRequest(ScientificReviewRequest):
    schema_version:Literal[3]
    consistency:SchoolConsistencyDecision

def scientific_request_model(value):
    return SchoolScientificReviewRequest if isinstance(value,dict) and value.get('schema_version')==3 else ScientificReviewRequest

class ReviewedPublishRequest(Strict):
    schema_version: Literal[2]
    expected_revision: int = Field(ge=1)
    review_id: str = Field(min_length=1,max_length=128)
    review_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')

    language_review_id: str | None = Field(default=None,min_length=1,max_length=128)
    language_review_sha256: str | None = Field(default=None,pattern=r"^[0-9a-f]{64}$")
