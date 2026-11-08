"""Offline, server-owned workflow configuration."""
import re
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .provider import ProviderError

MAX_INPUT_BYTES = 119 * 1024**3


def object_key(value: str) -> str:
    if not isinstance(value, str) or not value or value.startswith('/') or '\\' in value or any(p in ('', '.', '..') for p in value.split('/')) or any(ord(c) < 32 for c in value):
        raise ProviderError('invalid_object_key')
    return value


class WorkflowProfile(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    workflow_type: str = 'READY2RUN'
    workflow_version: str | None = None
    engine: str = 'starsolo'
    species: str = Field(min_length=1)
    chemistries: list[str] = Field(min_length=1)
    reference_id: str = Field(min_length=1)
    parameters: dict[str, str]
    outputs: dict[str, str]
    account_verified: bool = False
    estimated_run_cost_usd: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    max_input_bytes: int = Field(default=MAX_INPUT_BYTES, gt=0, le=MAX_INPUT_BYTES)

    @field_validator('workflow_type')
    @classmethod
    def workflow_kind(cls, value):
        if value not in ('READY2RUN', 'PRIVATE'):
            raise ValueError('invalid_workflow_type')
        return value

    @field_validator('outputs')
    @classmethod
    def output_paths(cls, value):
        if not {'matrix', 'features', 'barcodes', 'qc', 'log'} <= value.keys():
            raise ValueError('missing_output_roles')
        if len(set(value.values())) != len(value):
            raise ValueError('duplicate_output_path')
        for path in value.values():
            object_key(path)
        return value

    @field_validator('parameters')
    @classmethod
    def parameter_templates(cls, value):
        allowed = {'samplesheet_uri', 'fastq_r1', 'fastq_r2', 'sample_id'}
        for key, template in value.items():
            normalized = re.sub(r'[^a-z0-9]', '', key.lower())
            if any(word in normalized for word in ('secret', 'password', 'credential', 'accesskey', 'sessiontoken')):
                raise ValueError('credentials_forbidden')
            if not key or any(x not in allowed for x in re.findall(r'\{([^{}]*)\}', template)) or '{' in re.sub(r'\{[^{}]*\}', '', template) or '}' in re.sub(r'\{[^{}]*\}', '', template):
                raise ValueError('invalid_parameter_template')
        return value


def build_parameters(profile, *, samplesheet_uri, fastq_r1, fastq_r2, sample_id):
    values = dict(samplesheet_uri=samplesheet_uri, fastq_r1=fastq_r1, fastq_r2=fastq_r2, sample_id=sample_id)
    return {key: re.sub(r'\{([^{}]*)\}', lambda m: values[m[1]], template) for key, template in profile.parameters.items()}
