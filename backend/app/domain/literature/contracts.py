"""Versioned retrieval inputs; selection never asserts scientific support."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

WORKFLOW = 'literature_search_v1'
PUBLICATION_TYPES = ('Clinical Trial', 'Randomized Controlled Trial', 'Review', 'Systematic Review',
                     'Meta-Analysis', 'Observational Study', 'Case Reports')


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', frozen=True)


class SearchContext(StrictModel):
    kind: Literal['project_topic', 'section', 'feedback'] = 'project_topic'
    label: str = Field(default='', max_length=200)
    text: str = Field(default='', max_length=6000)


class SearchRequest(StrictModel):
    research_topic: str = Field(min_length=1, max_length=2000)
    source_context: SearchContext = Field(default_factory=SearchContext)
    query: str = Field(min_length=1, max_length=4000)
    year_from: int | None = Field(default=None, ge=1800, le=3000)
    year_to: int | None = Field(default=None, ge=1800, le=3000)
    publication_types: list[str] = Field(default_factory=list, max_length=7)
    sort: Literal['relevance', 'pub_date'] = 'relevance'
    limit: Literal[20, 50, 100] = 20
    output_language: Literal['zh-CN', 'en'] = 'zh-CN'

    @field_validator('research_topic', 'query')
    @classmethod
    def required_text(cls, value):
        if not value.strip() or '\x00' in value:
            raise ValueError('Nonempty text is required.')
        return value.strip()

    @model_validator(mode='after')
    def confirmed_conditions(self):
        if self.year_from is not None and self.year_to is not None and self.year_from > self.year_to:
            raise ValueError('Publication year range is reversed.')
        if len(set(self.publication_types)) != len(self.publication_types) or any(t not in PUBLICATION_TYPES for t in self.publication_types):
            raise ValueError('Publication types must be distinct supported PubMed types.')
        return self


def effective_query(request):
    terms = ['(' + request.query + ')']
    if request.year_from is not None or request.year_to is not None:
        terms.append(f'({request.year_from or 1800}:{request.year_to or 3000}[Date - Publication])')
    if request.publication_types:
        terms.append('(' + ' OR '.join('"' + t + '"[Publication Type]' for t in request.publication_types) + ')')
    return ' AND '.join(terms)


class LiteratureInputVersion(StrictModel):
    kind: Literal['literature_search'] = 'literature_search'
    workflow_version: Literal['literature_search_v1'] = WORKFLOW
    search_id: str
    input_digest: str = Field(pattern=r'^[0-9a-f]{64}$')
    output_language: Literal['zh-CN', 'en']


class SelectionRequest(StrictModel):
    expected_revision: int = Field(ge=1, lt=2147483647)
    status: Literal['candidate', 'shortlisted', 'excluded']
    note: str = Field(default='', max_length=2000)


class EvidenceBindingContract(StrictModel):
    """Reserved business contract; not a claim-verification implementation."""
    schema_version: Literal[1] = 1
    project_reference_id: str
    reference_id: str
    claim_id: str
    source_receipt_id: str
    reading_scope: Literal['abstract', 'full_text', 'user_material']
    status: Literal['supported', 'partial', 'unsupported', 'needs_review']


class CitationBindingContract(StrictModel):
    schema_version: Literal[1] = 1
    project_reference_id: str
    reference_id: str
    paragraph_id: str
    manuscript_version_key: str
    evidence_id: str
