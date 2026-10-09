"""Local administrator evidence, never a public HTTP write contract."""
import re
import unicodedata
from typing import Annotated, Literal

from pydantic import Field, field_validator

from app.domain.model_usage.contracts import MAX_ACCOUNTED_MICRO_USD, StrictContract


class ReconciliationRequest(StrictContract):
    event_key: Annotated[str, Field(strict=True, min_length=1, max_length=128, pattern=r'^[\x21-\x7e]+$')]
    expected_revision: Annotated[int, Field(strict=True, ge=0, lt=2_147_483_647)]
    component: Literal['token', 'tool']
    amount_micro_usd: Annotated[int, Field(strict=True, ge=0, le=MAX_ACCOUNTED_MICRO_USD)]
    evidence_kind: Literal['provider_statement', 'provider_support']
    evidence_reference: Annotated[str, Field(strict=True, min_length=1, max_length=256)]
    evidence_sha256: Annotated[str, Field(strict=True, pattern=r'^[0-9a-f]{64}$')]
    provider_object_id: Annotated[str, Field(strict=True, min_length=1, max_length=256)]
    operator: Annotated[str, Field(strict=True, min_length=1, max_length=128)]

    @field_validator('event_key', 'evidence_reference', 'provider_object_id', 'operator')
    @classmethod
    def safe_text(cls, value):
        if not value.strip() or any(unicodedata.category(char).startswith('C') for char in value):
            raise ValueError('Text contains control or format characters.')
        return value

    @field_validator('evidence_reference')
    @classmethod
    def restricted_reference(cls, value):
        if value.startswith(('/', '\\')) or re.match(r'^[a-zA-Z]:[\\/]', value) or value.lower().startswith('file:'):
            raise ValueError('Evidence references must not be absolute paths.')
        return value
