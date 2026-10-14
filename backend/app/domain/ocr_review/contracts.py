from typing import Literal
from pydantic import Field, model_validator, model_serializer
from app.domain.documents.ocr_contracts import Model, OcrText

WORKFLOW_VERSION = 'ocr_review_v1'
MAX_OBJECT_BYTES = 16777216
MAX_REPLACEMENT_BYTES = 4194304


class OcrReviewSource(Model):
    file_id: str = Field(min_length=1, max_length=64)
    parse_id: str = Field(min_length=1, max_length=64)
    parse_version: int = Field(ge=1)
    source_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    document_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    parser_version: str
    selected_pages: list[int] = Field(min_length=1, max_length=10)

    @model_validator(mode='after')
    def coherent(self):
        if self.selected_pages != sorted(set(self.selected_pages)) or any(not 1 <= p <= 100 for p in self.selected_pages):
            raise ValueError('Invalid selected pages')
        return self


class OcrReviewInputVersion(Model):
    kind: Literal['ocr_review']
    source: OcrReviewSource
    workflow_version: Literal['ocr_review_v1']


class OcrReviewEdit(Model):
    block_id: str = Field(min_length=1, max_length=128)
    action: Literal['accept_original', 'replace_text', 'unreadable']
    text: str | None = Field(default=None, max_length=20000)

    @model_serializer(mode='wrap')
    def serialize(self, handler):
        material = handler(self)
        if self.action != 'replace_text': material.pop('text', None)
        return material

    @model_validator(mode='after')
    def coherent(self):
        if self.action == 'replace_text':
            if self.text is None or not self.text.strip():
                raise ValueError('替换文字不能为空；无法辨认请使用 unreadable。')
        elif 'text' in self.model_fields_set:
            raise ValueError('Only replacement may include text')
        return self


def dump_edits(edits):
    return [e.model_dump(mode='json', exclude_unset=True) for e in edits]


class OcrReviewSummary(Model):
    total_blocks: int = Field(gt=0, le=20000)
    reviewed_blocks: int = Field(ge=0)
    unreviewed_blocks: int = Field(ge=0)
    accepted_blocks: int = Field(ge=0)
    corrected_blocks: int = Field(ge=0)
    unreadable_blocks: int = Field(ge=0)
    no_text_pages: list[int]

    @model_validator(mode='after')
    def coherent(self):
        if self.total_blocks != self.reviewed_blocks + self.unreviewed_blocks or self.reviewed_blocks != self.accepted_blocks + self.corrected_blocks + self.unreadable_blocks:
            raise ValueError('Invalid review counts')
        if self.no_text_pages != sorted(set(self.no_text_pages)) or any(type(p) is not int or not 1 <= p <= 100 for p in self.no_text_pages):
            raise ValueError('Invalid no-text pages')
        return self


class OcrReviewedBlock(Model):
    original: OcrText
    action: Literal['accept_original', 'replace_text', 'unreadable'] | None
    effective_text: str | None


class OcrReviewDocument(Model):
    schema_version: Literal[1] = 1
    kind: Literal['ocr_review_document'] = 'ocr_review_document'
    parent_source: OcrReviewSource
    workflow_version: Literal['ocr_review_v1'] = WORKFLOW_VERSION
    edits: list[OcrReviewEdit]
    blocks: list[OcrReviewedBlock] = Field(min_length=1, max_length=20000)
    summary: OcrReviewSummary

    @model_validator(mode='after')
    def coherent(self):
        ids = [b.original.id for b in self.blocks]
        edits = {e.block_id:e for e in self.edits}
        if len(set(ids)) != len(ids) or len(edits) != len(self.edits) or not set(edits) <= set(ids):
            raise ValueError('Invalid block identities')
        if sum(len(e.text.encode('utf-8')) for e in self.edits if e.text is not None) > MAX_REPLACEMENT_BYTES:
            raise ValueError('Replacement text exceeds total limit')
        counts = dict(accept_original=0, replace_text=0, unreadable=0)
        for block in self.blocks:
            edit = edits.get(block.original.id)
            action = edit.action if edit else None
            effective = block.original.text if action == 'accept_original' else edit.text if action == 'replace_text' else None
            if (block.action, block.effective_text) != (action, effective) or block.original.source.page_number not in self.parent_source.selected_pages:
                raise ValueError('Effective text differs from decision')
            if action: counts[action] += 1
        expected = (len(ids), len(edits), len(ids)-len(edits), counts['accept_original'], counts['replace_text'], counts['unreadable'])
        if tuple(getattr(self.summary,k) for k in ('total_blocks','reviewed_blocks','unreviewed_blocks','accepted_blocks','corrected_blocks','unreadable_blocks')) != expected:
            raise ValueError('Summary differs from decisions')
        text_pages = {b.original.source.page_number for b in self.blocks}
        if self.summary.no_text_pages != [p for p in self.parent_source.selected_pages if p not in text_pages]:
            raise ValueError('No-text page evidence differs')
        return self

    def require_publishable(self):
        if self.summary.unreviewed_blocks:
            raise ValueError('Every existing block requires an explicit review decision')

    def json_material(self):
        material = self.model_dump(mode='json')
        material['edits'] = dump_edits(self.edits)
        return material
