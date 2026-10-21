"""Strict per-export-item human language decisions."""
from typing import Literal
from pydantic import Field, field_validator
from .contracts import Strict

class LanguageException(Strict):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    kind: Literal['proper_name','unit','reference_metadata']
    reason: str = Field(min_length=1,max_length=1000)

class LanguageDecision(Strict):
    location: str = Field(min_length=1,max_length=500)
    content_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    decision: Literal['target_language','no_text']
    reason: str = Field(min_length=1,max_length=2000)
    exceptions: list[LanguageException] = Field(default_factory=list,max_length=100)

class LanguageEdit(Strict):
    path: str = Field(min_length=1,max_length=500)
    original_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    text: str = Field(min_length=1,max_length=10000)
    reason: str = Field(min_length=1,max_length=2000)

class FigureVersionDecision(Strict):
    figure_id: str = Field(min_length=1,max_length=200)
    version_id: str = Field(min_length=1,max_length=128)
    original_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')

class LanguagePreparation(Strict):
    schema_version: Literal[2]
    review_id: str = Field(min_length=1,max_length=128)
    review_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    edits: list[LanguageEdit] = Field(default_factory=list,max_length=5000)
    figure_versions: list[FigureVersionDecision] = Field(default_factory=list,max_length=100)

class LanguageReviewRequest(LanguagePreparation):
    inventory_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    decisions: list[LanguageDecision] = Field(min_length=1,max_length=10000)
