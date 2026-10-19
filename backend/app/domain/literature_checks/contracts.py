"""Strict transport inputs and frozen check results; response bodies are excluded."""
from typing import Literal
from pydantic import Field,model_validator
from app.domain.literature.contracts import StrictModel

CheckKind=Literal['saved_record','doi_resolution']
CheckStatus=Literal['matched','synthetic_match','source_conflict','needs_review','not_checked',
    'not_applicable','invalid_doi','resolved','not_found','rate_limited','timeout','error']


class CheckRequest(StrictModel):
    kind: CheckKind
    search_id: str=Field(min_length=1,max_length=128)


class CheckSource(StrictModel):
    search_id: str=Field(min_length=1,max_length=128)
    receipt_id: str=Field(min_length=1,max_length=128)
    source_kind: Literal['ncbi_eutilities','synthetic_fixture']
    sha256: str|None=Field(pattern=r'^[0-9a-f]{64}$')
    record_sha256: str|None=Field(pattern=r'^[0-9a-f]{64}$')
    pmid: str=Field(pattern=r'^[1-9][0-9]{0,11}$')


class CheckResult(StrictModel):
    status: CheckStatus
    network_attempted: bool
    execution_kind: Literal['local','disabled','synthetic_fixture','doi_org']
    error_code: Literal['literature_source_conflict','doi_invalid','doi_not_found','doi_rate_limited',
        'doi_unavailable','doi_response_invalid','doi_timeout']|None
    doi: str|None
    http_status: int|None=Field(ge=100,le=599)
    resolution_target: str|None=Field(max_length=4096)
    source: CheckSource

    @model_validator(mode='after')
    def bounded_meaning(self):
        if self.network_attempted!=(self.execution_kind=='doi_org'):
            raise ValueError('Wrong network attribution')
        if self.execution_kind in ('local','disabled') and (self.http_status is not None or self.resolution_target is not None):
            raise ValueError('Unattempted check cannot have HTTP response')
        if self.status=='resolved':
            if (self.execution_kind not in ('synthetic_fixture','doi_org') or self.http_status not in (301,302,303,307,308)
                or not self.resolution_target or self.error_code is not None):
                raise ValueError('Resolution requires redirect headers')
        elif self.resolution_target is not None:
            raise ValueError('Only redirects have a resolution target')
        if self.status in ('not_checked','not_applicable','invalid_doi') and self.execution_kind!='disabled':
            raise ValueError('No HTTP execution allowed for unattempted status')
        return self


class CheckSnapshot(StrictModel):
    output_language: Literal['zh-CN','en']
    result: CheckResult
