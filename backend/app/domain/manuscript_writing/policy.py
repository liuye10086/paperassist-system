"""Frozen pricing, protocol and writing authorization settings."""
from app.domain.model_usage.contracts import ModelPolicy
MODEL = 'gpt-6.1-sol'
PRICE_VERSION = 'openai-standard-short-2026-11-06-gpt-6.1-sol'
POLICY_VERSION = 'writing-live-consent-v2'
MAX_INPUT = 100000
MAX_OUTPUT = 12000
PROTOCOL_ALLOWANCE = 4096
MAX_POSTS = 6
MAX_CORRECTIONS = 2
# One source for the consent manifest and the preview disclosure.
ENDPOINT = 'https://api.openai.com/v1/responses'
EXTERNAL_STORAGE_NOTICE = 'OpenAI stores background responses; selected material is transmitted externally.'

def policy():
    return ModelPolicy(model=MODEL, prompt_version='sci-writing-v2', max_output_tokens=MAX_OUTPUT,
        output_format='manuscript_writing_v2', price=dict(version=PRICE_VERSION,model=MODEL,
        input_micro_usd_per_million=2000000,cached_input_micro_usd_per_million=100000,
        output_micro_usd_per_million=10000000,cache_write_micro_usd_per_million=2500000))

def installed_policy():
    return policy()


def capabilities(version=None):
    from app.core.config import local_config
    config=local_config()
    configured=bool(config.get('OPENAI_API_KEY_FILE') or config.get('OPENAI_API_KEY'))
    execution=version['bundle']['models']['writing']['execution'] if version else None
    models=version['bundle']['models'] if version else None
    return dict(real_calls_enabled=config.get('PAPERASSIST_ENV')!='test' and config.get('PAPERASSIST_WRITING_LIVE_ENABLED')=='1' and configured and (models is None or models['real_calls_enabled']),
                credential_status='configured_unverified' if configured else 'missing',
                model=execution['policy']['model'] if execution else MODEL,
                price_version=execution['policy']['price']['version'] if execution else PRICE_VERSION,
                max_input_tokens=execution['input_token_allowance'] if execution else MAX_INPUT,
                max_output_tokens=execution['policy']['max_output_tokens'] if execution else MAX_OUTPUT,
                batch_max_posts=models['batch_max_posts'] if models else MAX_POSTS,
                publish_requires_review=True,
                provider=ENDPOINT,storage_scope=EXTERNAL_STORAGE_NOTICE)
