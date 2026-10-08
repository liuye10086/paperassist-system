"""Explicit local explanation policy; no built-in model prices or budgets."""
import json
from pathlib import Path
from typing import Annotated

from pydantic import Field, ValidationError, model_validator

from app.adapters.models.openai_responses import canonical_payload
from app.adapters.openai_explanation import INSTRUCTIONS
from app.core.config import local_config
from app.core.exceptions import StorageError
from app.core.paths import BACKEND_ROOT
from app.domain.explanation_content import VERSION
from app.domain.model_usage.contracts import MAX_MICRO_USD, ModelPolicy, Money, StrictContract


class ExplanationExecutionPolicy(StrictContract):
    policy: ModelPolicy
    input_token_allowance: Annotated[int, Field(strict=True, ge=1, le=MAX_MICRO_USD)]
    task_limit_micro_usd: Money

    @model_validator(mode='after')
    def fixed_explanation_contract(self):
        if (self.policy.prompt_version != VERSION or self.policy.tools
                or self.policy.output_format != 'analysis_explanation_v1'):
            raise ValueError('The configured policy must use the current explanation contract.')
        return self


def _not_configured():
    return StorageError('explanation_not_configured', '分析解释的模型策略、预算或密钥尚未正确配置，请联系管理员。', 503)


def _small_text(path, limit):
    if not isinstance(path, str) or not path.strip():
        raise ValueError('Missing file configuration.')
    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        resolved = BACKEND_ROOT / resolved
    with resolved.open('rb') as stream:
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise ValueError('Configuration file is too large.')
    return content.decode('utf-8-sig')


def explanation_api_key():
    try:
        config = local_config()
        if config.get('OPENAI_API_KEY_FILE'):
            key = _small_text(config['OPENAI_API_KEY_FILE'], 8192).strip()
        else:
            key = (config.get('OPENAI_API_KEY') or '').strip()
        if not key or len(key.encode('utf-8')) > 8192 or any(char.isspace() for char in key):
            raise ValueError('Missing or invalid API key.')
        return key
    except (OSError, TypeError, ValueError):
        raise _not_configured() from None


def validate_execution_policy(value, payload=None):
    """Validate a frozen worker snapshot without reading secrets or local files."""
    try:
        parsed = ExplanationExecutionPolicy.model_validate(value)
    except (ValidationError, TypeError, ValueError):
        raise _not_configured() from None
    if payload is not None:
        try:
            minimum = len(INSTRUCTIONS.encode('utf-8')) + len(canonical_payload(payload).encode('utf-8')) + 4096
        except (TypeError, ValueError, RecursionError):
            raise StorageError('explanation_input_limit', '分析解释的输入材料无效或超出已配置的预算估算范围。', 422) from None
        if minimum > parsed.input_token_allowance:
            raise StorageError('explanation_input_limit', '分析解释的输入材料超出已配置的预算估算范围。', 422)
    # This conservative byte allowance is admission accounting, not a provider token limit.
    return parsed.model_dump(mode='json')


def get_execution_policy(payload):
    try:
        config = local_config()
        value = json.loads(_small_text(config.get('PAPERASSIST_EXPLANATION_POLICY_FILE'), 64 * 1024))
    except (OSError, TypeError, ValueError, RecursionError):
        raise _not_configured() from None
    frozen = validate_execution_policy(value, payload)
    explanation_api_key()
    return frozen


def configuration():
    try:
        frozen = get_execution_policy({})
    except StorageError:
        error = _not_configured()
        return {'configured': False, 'model': None, 'message': error.message,
                'message_code': error.code, 'message_params': {}}
    return {'configured': True, 'model': frozen['policy']['model'], 'message': '',
            'message_code': None, 'message_params': {}}
