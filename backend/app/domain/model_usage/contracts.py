"""Strict backend-owned policy and request contracts; amounts are micro USD."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_MICRO_USD = 1_000_000_000_000
MAX_ACCOUNTED_MICRO_USD = 2**63 - 1
Money = Annotated[int, Field(strict=True, ge=0, le=MAX_MICRO_USD)]
TokenCount = Annotated[int, Field(strict=True, ge=0, le=MAX_MICRO_USD)]
Identifier = Annotated[str, Field(strict=True, min_length=1, max_length=128, pattern=r'^\S+$')]
Version = Annotated[str, Field(strict=True, min_length=1, max_length=128, pattern=r'^\S+$')]


class StrictContract(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', frozen=True)


class PriceSnapshot(StrictContract):
    version: Version
    currency: Literal['USD'] = 'USD'
    model: Identifier
    input_micro_usd_per_million: Money
    cached_input_micro_usd_per_million: Money
    output_micro_usd_per_million: Money
    cache_write_micro_usd_per_million: Money | None = None


class ModelPolicy(StrictContract):
    model: Identifier
    prompt_version: Version
    max_output_tokens: Annotated[int, Field(strict=True, ge=1, le=MAX_MICRO_USD)]
    timeout_seconds: Annotated[int, Field(strict=True, ge=1, le=3600)] = 45
    tools: list[Literal['code_interpreter']] = Field(default_factory=list, max_length=1)
    output_format: Literal['text', 'analysis_explanation_v1'] = 'text'
    price: PriceSnapshot

    @model_validator(mode='after')
    def matching_model(self):
        if self.model != self.price.model:
            raise ValueError('Policy and price must describe the same model.')
        return self


class CallRequest(StrictContract):
    task_id: Annotated[str, Field(strict=True, min_length=1, max_length=64, pattern=r'^\S+$')]
    expected_task_revision: Annotated[int, Field(strict=True, ge=1, le=2_147_483_647)]
    call_key: Annotated[str, Field(strict=True, min_length=1, max_length=128, pattern=r'^[\x21-\x7e]+$')]
    input_digest: Annotated[str, Field(strict=True, pattern=r'^[0-9a-f]{64}$')]
    policy: ModelPolicy
    input_token_allowance: TokenCount
    tool_reserve_micro_usd: Money = 0
    tool_reserve_version: Version | None = None
