"""Strict frozen manuscript writing contracts. No real provider authorization."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

WORKFLOW = 'manuscript_writing_v1'
PROMPT_VERSION = 'sci-writing-v1'
POLICY_VERSION = 'offline-only-v1'
SECTION_IDS = ('title','abstract','introduction','results','discussion','materials_and_methods','references')
SectionId = Literal['title','abstract','introduction','results','discussion','materials_and_methods','references']


class Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')


class WritingRequest(Strict):
    base_revision: int = Field(ge=1)
    mode: Literal['full_draft','rewrite_section']
    target_section: str | None = Field(default=None,min_length=1,max_length=200)
    instructions: str = Field(default='',max_length=10000)
    keywords: list[str] = Field(default_factory=list,max_length=30)
    acknowledgements: str = Field(default='',max_length=10000)

    @model_validator(mode='after')
    def target_gate(self):
        if (self.mode=='rewrite_section') != (self.target_section is not None):
            raise ValueError('A rewrite requires exactly one target section')
        if any(not word.strip() or len(word)>200 for word in self.keywords):
            raise ValueError('Keywords must be explicit nonempty user text')
        return self


class PublishRequest(Strict):
    expected_revision: int = Field(ge=1)


class WritingInputVersion(Strict):
    kind: Literal['manuscript_writing'] = 'manuscript_writing'
    workflow_version: Literal['manuscript_writing_v1','manuscript_writing_v2'] = WORKFLOW
    base_version_id: str
    base_revision: int = Field(ge=1)
    output_language: Literal['zh-CN','en']


class NumericBinding(Strict):
    value: str = Field(min_length=1,max_length=100)
    source_id: str = Field(min_length=1,max_length=100)

class PreservedReviewBinding(Strict):
    """Only exact unchanged reviewed paragraphs may retain this binding form."""
    value: str = Field(min_length=1,max_length=100)
    fact_id: str = Field(min_length=1,max_length=1000)


class OutputParagraph(Strict):
    id: str = Field(min_length=1,max_length=200)
    text: str = Field(min_length=1,max_length=10000)
    source_ids: list[str] = Field(default_factory=list,max_length=100)
    citations: list[dict] = Field(default_factory=list,max_length=100)
    numeric_bindings: list[NumericBinding | PreservedReviewBinding] = Field(default_factory=list,max_length=1000)
    origin: str | None = None


class OutputSection(Strict):
    id: str = Field(min_length=1,max_length=200)
    paragraphs: list[OutputParagraph] = Field(max_length=200)


class WritingOutput(Strict):
    sections: list[OutputSection] = Field(min_length=1,max_length=300)
