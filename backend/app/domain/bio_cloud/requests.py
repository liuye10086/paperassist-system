"""Public requests contain project-owned identities, never cloud credentials."""
import base64
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PART_SIZE = 16 * 1024 * 1024
MAX_INPUT_BYTES = 119 * 1024**3


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')


class UploadRequest(StrictRequest):
    filename: str = Field(min_length=1, max_length=200, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]*\.(fastq|fq)\.gz$')
    size_bytes: int = Field(strict=True, ge=1, le=MAX_INPUT_BYTES)


class PartRequest(StrictRequest):
    checksum_sha256: str = Field(min_length=44, max_length=44)

    @model_validator(mode='after')
    def checksum(self):
        try:
            value = base64.b64decode(self.checksum_sha256, validate=True)
        except ValueError:
            raise ValueError('invalid_part_checksum') from None
        if len(value) != 32 or base64.b64encode(value).decode() != self.checksum_sha256:
            raise ValueError('invalid_part_checksum')
        return self


class FastqInput(StrictRequest):
    upload_id: str = Field(min_length=1, max_length=64)
    read: Literal['R1', 'R2']
    lane: str = Field(default='L001', pattern=r'^L[0-9]{3}$')
    chunk: int = Field(default=1, strict=True, ge=1, le=999)


class RunRequest(StrictRequest):
    profile_id: str = Field(min_length=1, max_length=100)
    sample_id: str = Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]*$')
    library_id: str = Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]*$')
    species: str = Field(min_length=1, max_length=100)
    chemistry: str = Field(min_length=1, max_length=100)
    donor_id: str = Field(default='', max_length=100)
    group: str = Field(default='', max_length=100)
    fastqs: list[FastqInput] = Field(min_length=2, max_length=100)
    external_processing_confirmed: Literal[True]
    budget_approved: Literal[True]
    budget_limit_usd: Decimal = Field(gt=0, le=100000, max_digits=10, decimal_places=2)

    @model_validator(mode='after')
    def pairs(self):
        ids = [f.upload_id for f in self.fastqs]
        identities = [(f.lane, f.chunk, f.read) for f in self.fastqs]
        if len(set(ids)) != len(ids) or len(set(identities)) != len(identities):
            raise ValueError('duplicate_fastq')
        if {(f.lane, f.chunk) for f in self.fastqs if f.read == 'R1'} != {(f.lane, f.chunk) for f in self.fastqs if f.read == 'R2'}:
            raise ValueError('paired_reads_required')
        return self


class CloudInputVersion(StrictRequest):
    kind: Literal['bio_cloud_run'] = 'bio_cloud_run'
    workflow_version: Literal['bio_cloud_run_v1'] = 'bio_cloud_run_v1'
    run_id: str
    profile_id: str
    sample_id: str
    input_sha256: str


class ReconcileRequest(StrictRequest):
    # Provider IDs are opaque. AWS HealthOmics uses decimal IDs today, while
    # other providers may return UUID-like or namespaced values.
    provider_run_id: str = Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$')


class EmptyRequest(StrictRequest):
    pass
