"""Explicit fixed DOCX returns and user-entered progress contracts."""
from datetime import date
from typing import Literal
from pydantic import Field
from .contracts import Strict, Manuscript


class RegisterReturn(Strict):
    manuscript: Manuscript
    revision_id: str | None = None
    file_id: str = Field(min_length=1, max_length=64)
    document_version_id: str = Field(min_length=1, max_length=64)
    base_export_id: str | None = None
    synthetic: bool


class ReturnMapping(Strict):
    input_section_id: str = Field(min_length=1, max_length=300)
    chapter_id: str = Field(min_length=1, max_length=300)


class PreviewReturn(Strict):
    mappings: list[ReturnMapping] = Field(max_length=300)


class AdoptReturn(PreviewReturn):
    expected_current_revision: int = Field(strict=True, ge=1, le=2147483646)
    preview_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class ProgressRequest(Strict):
    status: Literal['submitted', 'revision', 'accepted', 'published', 'withdrawn', 'not_recorded']
    event_date: date
    note: str = Field(default='', max_length=4000)
    synthetic: bool
    target_id: str | None = None
    round_id: str | None = None
    manuscript: Manuscript | None = None
    export_id: str | None = None
    corrects_event_id: str | None = None
