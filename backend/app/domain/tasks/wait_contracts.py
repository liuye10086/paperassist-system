"""Safe waiting projections and explicit, versioned recovery input."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.tasks.contracts import InputVersion, UTCDateTime


class StrictInputVersion(InputVersion):
    model_config = ConfigDict(extra='forbid')
    setup_revision: int = Field(strict=True, ge=1, le=2_147_483_647)


class WaitView(BaseModel):
    id: str
    kind: Literal['budget_confirmation', 'submission_unknown', 'unsupported_input', 'unsupported_confirmation']
    status: Literal['open', 'resolved', 'superseded']
    task_revision: int
    input_version: InputVersion
    reason_code: str | None
    error_code: str | None
    created_at: UTCDateTime
    resolved_at: UTCDateTime | None


class ResumeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    operation: Literal['resume', 'retry']
    wait_id: str | None = Field(min_length=1, max_length=64, pattern=r'^\S+$')
    expected_task_revision: int = Field(strict=True, ge=1, lt=2_147_483_647)
    input_version: StrictInputVersion

    @model_validator(mode='after')
    def wait_matches_operation(self):
        if (self.wait_id is not None) != (self.operation == 'resume'):
            raise ValueError('A waiting generation is required only for resume.')
        return self
