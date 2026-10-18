from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class EvidenceRequest(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid')
    file_id: str=Field(min_length=1,max_length=64)
    source_kind: Literal['original','document_version','ocr_review_version']
    document_version_id: str | None=Field(default=None,min_length=1,max_length=64)
    ocr_review_version_id: str | None=Field(default=None,min_length=1,max_length=64)
    item_ids: list[str]=Field(default_factory=list,max_length=20)
    title: str=Field(min_length=1,max_length=200)
    source_description: str=Field(default='',max_length=2000)
    intended_use: Literal['reference','background','request_reanalysis']
    original_data: Literal['available','unavailable','unknown']
    user_note: str=Field(default='',max_length=2000)
    limitations: str=Field(default='',max_length=2000)
    previous_version_id: str | None=Field(default=None,min_length=1,max_length=64)

    @model_validator(mode='after')
    def coherent(self):
        if not self.title.strip() or len(set(self.item_ids))!=len(self.item_ids) or any(not i or len(i)>200 for i in self.item_ids):
            raise ValueError('Invalid evidence identity or title')
        expected={'original':(False,False),'document_version':(True,False),'ocr_review_version':(False,True)}[self.source_kind]
        if (bool(self.document_version_id),bool(self.ocr_review_version_id))!=expected or self.source_kind=='original' and self.item_ids:
            raise ValueError('Evidence source and selected fragments differ')
        return self
