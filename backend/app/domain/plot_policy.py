"""Explicit frozen Code Interpreter admission policy; no built-in prices or limits."""
import json
from pathlib import Path
from typing import Annotated

from pydantic import Field, ValidationError, model_validator

from app.adapters.models.openai_responses import canonical_payload
from app.adapters.openai_plot import INSTRUCTIONS, PROMPT_VERSION
from app.core.config import local_config
from app.core.exceptions import StorageError
from app.core.paths import BACKEND_ROOT
from app.domain.model_usage.contracts import MAX_MICRO_USD, ModelPolicy, Money, StrictContract, Version


class PlotExecutionPolicy(StrictContract):
    policy: ModelPolicy
    input_token_allowance: Annotated[int, Field(strict=True, ge=1, le=MAX_MICRO_USD)]
    task_limit_micro_usd: Money
    tool_reserve_micro_usd: Annotated[int, Field(strict=True, ge=1, le=MAX_MICRO_USD)]
    tool_reserve_version: Version

    @model_validator(mode='after')
    def fixed_plot_contract(self):
        if (self.policy.prompt_version not in (PROMPT_VERSION, 'openai_analysis_plot_v2', 'openai_comparison_plot_v3', 'openai_modeling_plot_v4') or self.policy.tools != ['code_interpreter']
                or self.policy.output_format != 'text'):
            raise ValueError('The configured policy must use the current plot contract.')
        return self


def _not_configured():
    return StorageError('plot_not_configured', '图表的模型策略、工具预留、预算或密钥尚未正确配置，请联系管理员。', 503)


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


def plot_api_key():
    try:
        config = local_config()
        key = (_small_text(config['OPENAI_API_KEY_FILE'], 8192) if config.get('OPENAI_API_KEY_FILE')
               else config.get('OPENAI_API_KEY') or '').strip()
        if not key or len(key.encode('utf-8')) > 8192 or any(char.isspace() for char in key):
            raise ValueError('Missing or invalid API key.')
        return key
    except (OSError, TypeError, ValueError):
        raise _not_configured() from None


def validate_execution_policy(value, payload=None, *, result=None):
    """Workers consume only the frozen policy; local configuration is not reread."""
    try:
        parsed = PlotExecutionPolicy.model_validate(value)
    except (ValidationError, TypeError, ValueError):
        raise _not_configured() from None
    if result is not None:
        from app.domain.artifact_contracts import figure_renderer
        if parsed.policy.prompt_version != figure_renderer(result):
            raise _not_configured()
    if payload is not None:
        try:
            expected_version = {2:'openai_analysis_plot_v2',3:'openai_comparison_plot_v3',4:'openai_modeling_plot_v4'}.get(payload.get('schema_version'),PROMPT_VERSION)
            if parsed.policy.prompt_version != expected_version:
                raise ValueError('Frozen plot policy does not match material.')
            instructions=INSTRUCTIONS
            if payload.get('schema_version')==4:
                from app.domain.modeling_prompts import PLOT_INSTRUCTIONS
                instructions=PLOT_INSTRUCTIONS
            elif payload.get('schema_version')==3:
                from app.domain.comparison_prompts import PLOT_INSTRUCTIONS
                instructions=PLOT_INSTRUCTIONS
            elif payload.get('schema_version')==2:
                from app.domain.artifact_prompts import PLOT_INSTRUCTIONS
                instructions=PLOT_INSTRUCTIONS
            minimum = len(instructions.encode('utf-8')) + len(canonical_payload(payload).encode('utf-8')) + 4096
        except (TypeError, ValueError, RecursionError):
            raise StorageError('plot_input_limit', '图表输入材料无效或超出已配置的预算估算范围。', 422) from None
        if minimum > parsed.input_token_allowance:
            raise StorageError('plot_input_limit', '图表输入材料超出已配置的预算估算范围。', 422)
    # The byte allowance supports admission estimates, not a provider hard token cap.
    return parsed.model_dump(mode='json')


def derive_execution_policy(value, payload=None):
    from copy import deepcopy
    value = deepcopy(value)
    if payload and payload.get('schema_version') in (2,3,4):
        # Validate the public configured baseline before deriving a fixed version.
        validate_execution_policy(value)
        value['policy']['prompt_version'] = 'openai_modeling_plot_v4' if payload['schema_version']==4 else 'openai_comparison_plot_v3' if payload['schema_version']==3 else 'openai_analysis_plot_v2'
    return validate_execution_policy(value,payload)


def get_execution_policy(payload=None, *, result=None):
    try:
        value = json.loads(_small_text(local_config().get('PAPERASSIST_PLOT_POLICY_FILE'), 64 * 1024))
    except (OSError, TypeError, ValueError, RecursionError):
        raise _not_configured() from None
    if result is not None:
        from app.domain.artifact_contracts import figure_renderer
        validate_execution_policy(value)
        value['policy']['prompt_version'] = figure_renderer(result)
        frozen = validate_execution_policy(value,payload,result=result)
    else:
        frozen = derive_execution_policy(value, payload)
    plot_api_key()
    return frozen


def configuration():
    try:
        frozen = get_execution_policy()
    except StorageError:
        error = _not_configured()
        return dict(configured=False, model=None, message=error.message,
                    message_code=error.code, message_params={})
    return dict(configured=True, model=frozen['policy']['model'], message='', message_code=None, message_params={})
