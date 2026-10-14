"""Public lifecycle inputs and stable canonical assessment hashing."""
import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

POLICY_VERSION = 'internal_testing_keep_v1'
Action = Literal['delete', 'reparse']
AssessmentRevision = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
ACTIVE = frozenset(('queued', 'running', 'waiting_input', 'waiting_confirmation'))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, default=str).encode()).hexdigest()


class DeletionRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    expected_assessment_revision: AssessmentRevision
    reason: str = Field(min_length=1, max_length=500)

    @field_validator('reason', mode='before')
    @classmethod
    def trim_reason(cls, value):
        return value.strip() if isinstance(value, str) else value
