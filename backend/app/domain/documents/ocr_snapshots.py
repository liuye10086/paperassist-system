"""Frozen OCR inputs, independent of legacy Word/PDF snapshot inheritance."""
from copy import deepcopy
from typing import Literal

from pydantic import Field, field_validator, model_validator
from app.domain.file_parsing import StrictModel, ParseProject
from app.domain.documents.ocr_contracts import OCR_SETTINGS, PARSER_VERSION


class OcrFile(StrictModel):
    id: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    size_bytes: int = Field(ge=1, le=10485760)
    file_type: Literal['pdf','png','jpeg']
    storage_backend: Literal['local']
    object_key: str = Field(min_length=1)


class OcrFileSnapshot(StrictModel):
    schema_version: Literal[1]
    kind: Literal['ocr_document']
    project: ParseProject
    file: OcrFile
    parse_id: str = Field(min_length=1)
    parse_version: int = Field(ge=1)
    parser_version: Literal['rapidocr-3.10.0-ppocrv6-small-v1']
    page_numbers: list[int] = Field(min_length=1,max_length=10)
    settings: dict

    @field_validator('schema_version',mode='before')
    @classmethod
    def integer_schema(cls,value):
        if type(value) is not int: raise ValueError('Integer schema required')
        return value

    @field_validator('settings',mode='before')
    @classmethod
    def frozen_settings(cls,value):
        # Equality alone accepts True==1; reject coercions recursively.
        def exact(actual,expected):
            if type(actual) is not type(expected): return False
            if isinstance(expected,dict):
                return actual.keys()==expected.keys() and all(exact(actual[k],v) for k,v in expected.items())
            if isinstance(expected,list):
                return len(actual)==len(expected) and all(exact(a,b) for a,b in zip(actual,expected))
            return actual==expected
        if not exact(value,OCR_SETTINGS): raise ValueError('Exact frozen OCR settings required')
        return value

    @model_validator(mode='after')
    def selected_pages(self):
        if self.page_numbers!=sorted(set(self.page_numbers)) or any(not 1<=p<=100 for p in self.page_numbers):
            raise ValueError('Sorted unique physical pages required')
        if self.file.file_type!='pdf' and self.page_numbers!=[1]:
            raise ValueError('Images have one physical page')
        return self


def ocr_snapshot(project_id,file,parse_id,version,page_numbers):
    return OcrFileSnapshot.model_validate(dict(schema_version=1,kind='ocr_document',
        project={'id':project_id},file=file,parse_id=parse_id,parse_version=version,
        parser_version=PARSER_VERSION,page_numbers=sorted(page_numbers),settings=deepcopy(OCR_SETTINGS))).model_dump()
