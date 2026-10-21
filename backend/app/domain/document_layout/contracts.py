from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Formula(StrictModel):
    id: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9_]{0,31}$')
    anchor_id: str = Field(min_length=1, max_length=100)
    expression: str = Field(min_length=1, max_length=2000)
    placement: Literal['after', 'inline'] = 'after'


class Reference(StrictModel):
    anchor_id: str = Field(min_length=1, max_length=100)
    target_id: str = Field(min_length=1, max_length=100)
    kind: Literal['text', 'number', 'page'] = 'text'
    prefix: str = Field(default='', max_length=100)


class Heading(StrictModel):
    anchor_id: str = Field(min_length=1, max_length=100)
    level: int = Field(ge=1, le=3)


class Toc(StrictModel):
    depth: int = Field(default=3, ge=1, le=3)


class Pagination(StrictModel):
    mode: Literal['continuous', 'roman_front'] = 'continuous'
    body_anchor_id: str | None = Field(default=None, max_length=100)

    @model_validator(mode='after')
    def body_required(self):
        if self.mode == 'roman_front' and not self.body_anchor_id:
            raise ValueError('roman_front requires body_anchor_id')
        if self.mode == 'continuous' and self.body_anchor_id is not None:
            raise ValueError('continuous does not accept body_anchor_id')
        return self


class LayoutOptions(StrictModel):
    source_sha256: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')
    formulas: list[Formula] = Field(default_factory=list, max_length=40)
    references: list[Reference] = Field(default_factory=list, max_length=60)
    headings: list[Heading] = Field(default_factory=list, max_length=100)
    toc: Toc | None = None
    pagination: Pagination | None = None
    landscape_anchor_ids: list[str] = Field(default_factory=list, max_length=16)

    @model_validator(mode='after')
    def unique_objects(self):
        for values in ([f.id for f in self.formulas], [h.anchor_id for h in self.headings],
                       self.landscape_anchor_ids):
            if len(values) != len(set(values)):
                raise ValueError('duplicate layout identity')
        return self
