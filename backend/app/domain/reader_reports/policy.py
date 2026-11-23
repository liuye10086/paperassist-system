"""Deployment-selected reader policy and prices."""
import json

from app.core.config import local_config
from app.core.exceptions import StorageError
from app.domain.explanation_policy import _small_text
from app.domain.model_usage.contracts import ModelPolicy, MAX_MICRO_USD
from app.domain.model_usage.gateway import input_digest
from app.domain.model_usage.pricing import reserve_micro_usd
from .content import STANDARD_VERSION, binding_digest, input_text_bytes, instructions


def real_calls_enabled():
    return str(local_config().get('PAPERASSIST_READER_REPORT_MODEL_ENABLED', '0')).strip() == '1'


def configuration():
    try:
        settings = local_config()
        path = settings.get('PAPERASSIST_READER_REPORT_POLICY_FILE') or settings.get('PAPERASSIST_EXPLANATION_POLICY_FILE')
        value = json.loads(_small_text(path, 65536))
        raw = dict(value['policy'])
        if raw.get('tools'):
            raise ValueError('Reader prose may not execute tools')
        raw.update(prompt_version=STANDARD_VERSION, output_format='reader_report_v1')
        parsed = ModelPolicy.model_validate(raw)
        allowance = value['input_token_allowance']
        if type(allowance) is not int or not 1 <= allowance <= MAX_MICRO_USD:
            raise ValueError('Invalid reader input allowance')
        return {'policy': parsed.model_dump(mode='json'), 'input_token_allowance': allowance}
    except (OSError, ValueError, KeyError, TypeError):
        raise StorageError('reader_report_not_configured', '详细报告的模型策略或输入上限尚未配置，请联系管理员。', 503) from None


def policy():
    return ModelPolicy.model_validate(configuration()['policy'])


def bundle(material):
    config = configuration()
    prompt = instructions(material['language'])
    # The byte estimate and image margin reject oversized requests before transmission.
    minimum = len(prompt.encode('utf-8')) + input_text_bytes(material) + 8192 * len(material['figures']) + 4096
    if minimum > config['input_token_allowance']:
        raise StorageError('reader_report_input_limit', '选定结果与图片超出详细报告的输入额度，请减少选择或由管理员调整配置。', 422)
    parsed = ModelPolicy.model_validate(config['policy'])
    reserved = reserve_micro_usd(parsed, config['input_token_allowance'], 0)
    value = {**config, 'schema_version': 1, 'instructions': prompt, 'material': material,
             'input_digest': input_digest(instructions=prompt, payload=material),
             'reserved_micro_usd': reserved, 'real_calls_enabled': real_calls_enabled()}
    return {**value, 'bundle_sha256': binding_digest({key: item for key, item in value.items() if key != 'real_calls_enabled'})}
