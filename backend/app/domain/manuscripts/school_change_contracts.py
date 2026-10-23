from typing import Literal
from pydantic import Field,model_validator
from .contracts import Strict

class RegisterChange(Strict):
    kind:Literal['template_migration','docx_return']
    target_confirmation_id:str|None=Field(default=None,min_length=1,max_length=64)
    file_id:str|None=Field(default=None,min_length=1,max_length=64)
    document_version_id:str|None=Field(default=None,min_length=1,max_length=64)
    base_export_id:str|None=Field(default=None,min_length=1,max_length=64)

    @model_validator(mode='after')
    def bounded(self):
        if self.kind=='template_migration':
            if not self.target_confirmation_id or self.file_id or self.document_version_id or self.base_export_id:raise ValueError('模板迁移须且仅须目标确认。')
        elif not self.file_id or not self.document_version_id or self.target_confirmation_id:raise ValueError('回传须固定DOCX及解析版本。')
        return self

class ChangeMapping(Strict):
    input_section_id:str=Field(min_length=1,max_length=300)
    chapter_id:str=Field(min_length=1,max_length=300)

class PreviewChange(Strict):
    mappings:list[ChangeMapping]=Field(max_length=300)

class AdoptChange(PreviewChange):
    expected_revision:int=Field(ge=1,le=2147483646)
    preview_sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
