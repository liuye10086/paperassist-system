"""Strict inputs: source and location are always reconstructed by the server."""
from typing import Literal
from pydantic import Field, field_validator, model_validator
from app.domain.literature.contracts import StrictModel


class ClaimRequest(StrictModel):
    content: str = Field(min_length=1, max_length=6000)
    context: str = Field(default='', max_length=6000)
    output_language: Literal['zh-CN', 'en'] = 'zh-CN'

    @field_validator('content')
    @classmethod
    def content_required(cls, value):
        if not value.strip() or '\x00' in value:
            raise ValueError('Nonempty claim required')
        return value


class ClaimVersionRequest(ClaimRequest):
    expected_revision: int = Field(ge=1, lt=2147483647)


class MaterialRequest(StrictModel):
    project_reference_id: str = Field(min_length=1, max_length=128)
    file_id: str = Field(min_length=1, max_length=128)
    source_kind: Literal['document_version', 'ocr_review_version']
    version_id: str = Field(min_length=1, max_length=128)
    source_description: str = Field(min_length=1, max_length=2000)
    match_note: str = Field(min_length=1, max_length=2000)

    @field_validator('source_description', 'match_note')
    @classmethod
    def confirmation_required(cls, value):
        if not value.strip():
            raise ValueError('Explicit source and bibliographic correspondence required')
        return value


class QuoteRequest(StrictModel):
    claim_revision: int = Field(ge=1)
    project_reference_id: str = Field(min_length=1, max_length=128)
    source_kind: Literal['abstract', 'material', 'pmc']
    pmc_receipt_id: str | None = Field(default=None, min_length=1, max_length=128)
    search_id: str | None = Field(default=None, min_length=1, max_length=128)
    material_id: str | None = Field(default=None, min_length=1, max_length=128)
    item_id: str | None = Field(default=None, min_length=1, max_length=256)
    quote: str = Field(min_length=1, max_length=12000)

    @model_validator(mode='after')
    def actual_source(self):
        if not self.quote.strip():
            raise ValueError('Nonempty exact quote required')
        if self.source_kind == 'pmc':
            if not self.pmc_receipt_id or not self.item_id or self.search_id or self.material_id:
                raise ValueError('PMC requires its saved receipt and item')
        elif self.pmc_receipt_id:
            raise ValueError('PMC receipt requires PMC source')
        elif self.source_kind == 'abstract':
            if not self.search_id or self.material_id or self.item_id:
                raise ValueError('Abstract requires exactly its search history')
        elif not self.material_id or not self.item_id or self.search_id:
            raise ValueError('Material requires its actual item')
        return self

    def model_dump(self, **kwargs):
        result = super().model_dump(**kwargs)
        # Historic request JSON and digests remain byte-structurally unchanged.
        if self.source_kind != 'pmc': result.pop('pmc_receipt_id', None)
        return result


class ReviewRequest(StrictModel):
    claim_revision: int = Field(ge=1)
    project_reference_id: str = Field(min_length=1, max_length=128)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    status: Literal['supported', 'partial', 'unsupported', 'needs_review']
    relevance: Literal['related', 'unrelated', 'uncertain']
    reason: str = Field(min_length=1, max_length=4000)
    narrowed_statement: str = Field(default='', max_length=6000)
    limitations: str = Field(default='', max_length=4000)

    @model_validator(mode='after')
    def bounded_decision(self):
        if not self.reason.strip() or len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError('Reason and distinct evidence required')
        if self.status != 'needs_review' and not self.evidence_ids:
            raise ValueError('Missing evidence requires needs_review')
        if self.status in ('supported', 'partial') and self.relevance != 'related':
            raise ValueError('Unrelated or uncertain material cannot confirm support')
        if self.status == 'partial' and not self.narrowed_statement.strip():
            raise ValueError('Partial support requires narrowed statement')
        return self


class SupplementRequest(StrictModel):
    claim_revision: int = Field(ge=1)
    query: str = Field(min_length=1, max_length=4000)
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator('query', 'reason')
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError('Nonempty text required')
        return value
