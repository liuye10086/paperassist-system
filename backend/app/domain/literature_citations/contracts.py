"""Server resolves text, sources, evidence and numbering; clients supply stable IDs."""
from typing import Annotated, Literal
from pydantic import Field, field_validator, model_validator
from app.domain.literature.contracts import StrictModel


class Author(StrictModel):
    family: str = Field(default='',max_length=1000)
    given: str = Field(default='',max_length=1000)
    initials: str = Field(default='',max_length=100)
    collective: str = Field(default='',max_length=2000)


class Metadata(StrictModel):
    article_type: Literal['journal','unsupported']='journal'
    authors: list[Author] = Field(default_factory=list,max_length=1000)
    title: str = Field(default='',max_length=12000)
    journal_title: str = Field(default='',max_length=4000)
    journal_abbreviation: str = Field(default='',max_length=4000)
    year: str = Field(default='',max_length=100)
    date: str = Field(default='',max_length=200)
    volume: str = Field(default='',max_length=200)
    issue: str = Field(default='',max_length=200)
    pages: str = Field(default='',max_length=500)
    article_number: str = Field(default='',max_length=500)
    doi: str = Field(default='',max_length=2000)
    pmid: str = Field(default='',max_length=12)


class MetadataRequest(StrictModel):
    expected_revision: int = Field(ge=0,lt=2147483647)
    mode: Literal['extract','manual']
    search_id: str = Field(min_length=1,max_length=128)
    metadata: Metadata | None = None
    material_id: str | None = Field(default=None,min_length=1,max_length=128)
    source_description: str = Field(default='',max_length=4000)
    basis: str = Field(default='',max_length=4000)
    confirm_source: bool = False

    @model_validator(mode='after')
    def explicit_source(self):
        if self.mode=='manual':
            if self.metadata is None or not self.source_description.strip() or not self.basis.strip():
                raise ValueError('Manual entry requires source and basis')
        elif self.metadata is not None or self.material_id or self.source_description or self.basis or self.confirm_source:
            raise ValueError('Extraction reads only actual saved receipt')
        return self


class MaterialConfirmationRequest(StrictModel):
    expected_revision: int = Field(ge=0,lt=2147483647)
    completeness: Literal['full_paper','fragment','unconfirmed']
    basis: str = Field(min_length=1,max_length=4000)

    @field_validator('basis')
    @classmethod
    def nonempty(cls,value):
        if not value.strip():
            raise ValueError('Explicit basis required')
        return value


class Binding(StrictModel):
    review_id: str = Field(min_length=1,max_length=128)
    metadata_version_id: str = Field(min_length=1,max_length=128)


class TextFragment(StrictModel):
    kind: Literal['text']
    text: str = Field(max_length=20000)


class ClaimFragment(StrictModel):
    kind: Literal['claim']
    claim_id: str = Field(min_length=1,max_length=128)
    claim_revision: int = Field(ge=1)
    bindings: list[Binding] = Field(min_length=1,max_length=20)

    @model_validator(mode='after')
    def unique_bindings(self):
        if len({b.review_id for b in self.bindings})!=len(self.bindings):
            raise ValueError('Duplicate decision')
        return self


class Paragraph(StrictModel):
    id: str = Field(min_length=1,max_length=128,pattern=r'^[A-Za-z0-9_-]+$')
    fragments: list[Annotated[TextFragment | ClaimFragment,Field(discriminator='kind')]] = Field(min_length=1,max_length=200)


class DraftRequest(StrictModel):
    title: str = Field(min_length=1,max_length=500)
    output_language: Literal['zh-CN','en']='zh-CN'
    format: Literal['nlm_numeric_journal_v1']='nlm_numeric_journal_v1'
    paragraphs: list[Paragraph] = Field(min_length=1,max_length=200)

    @model_validator(mode='after')
    def stable_unique_ids(self):
        if not self.title.strip() or len({p.id for p in self.paragraphs})!=len(self.paragraphs):
            raise ValueError('Nonempty title and unique paragraph IDs required')
        if sum(len(f.text) if isinstance(f,TextFragment) else 6000 for p in self.paragraphs for f in p.fragments)>500000:
            raise ValueError('Sample too large')
        return self


class DraftVersionRequest(DraftRequest):
    expected_revision: int = Field(ge=1,lt=2147483647)
