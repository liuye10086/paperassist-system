"""Frozen pricing, protocol and conservative non-cache reservation."""
from app.domain.model_usage.contracts import ModelPolicy
MODEL = 'gpt-5.4-2026-03-05'
PRICE_VERSION = 'openai-standard-2026-10-21'
POLICY_VERSION = 'writing-live-consent-v2'
MAX_INPUT = 100000
MAX_OUTPUT = 12000
PROTOCOL_ALLOWANCE = 4096
MAX_POSTS = 6
MAX_CORRECTIONS = 2
TASK_CAP = 3000000
BATCH_CAP = 12000000

def policy():
    return ModelPolicy(model=MODEL, prompt_version='sci-writing-v2', max_output_tokens=MAX_OUTPUT,
        output_format='manuscript_writing_v2', price=dict(version=PRICE_VERSION,model=MODEL,
        input_micro_usd_per_million=2500000,cached_input_micro_usd_per_million=250000,
        output_micro_usd_per_million=15000000))

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
                batch_cap_micro_usd=models['batch_cap_micro_usd'] if models else BATCH_CAP,
                logical_task_cap_micro_usd=execution['task_limit_micro_usd'] if execution else TASK_CAP,publish_requires_review=True)
