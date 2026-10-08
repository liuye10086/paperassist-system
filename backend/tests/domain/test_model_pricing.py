"""Integer-only internal estimates; no live prices or providers."""
import pytest
from pydantic import ValidationError


def price(**overrides):
    from app.domain.model_usage.contracts import PriceSnapshot
    return PriceSnapshot(version='test-v1', model='test-model',
        input_micro_usd_per_million=1_000_000, cached_input_micro_usd_per_million=100_000,
        output_micro_usd_per_million=2_000_000, **overrides)


def policy(**overrides):
    from app.domain.model_usage.contracts import ModelPolicy
    return ModelPolicy(model='test-model', prompt_version='v1', max_output_tokens=10,
                       price=price(), **overrides)


@pytest.mark.parametrize('value', [True, 1.1, '1', -1, 1_000_000_000_001])
def test_prices_reject_non_integer_or_unbounded_values(value):
    from app.domain.model_usage.contracts import PriceSnapshot
    with pytest.raises(ValidationError):
        PriceSnapshot(version='v1', model='test', input_micro_usd_per_million=value,
                      cached_input_micro_usd_per_million=1, output_micro_usd_per_million=1)


def test_contract_rejects_model_mismatch_and_bypassed_copies():
    from app.domain.model_usage.contracts import CallRequest, ModelPolicy
    with pytest.raises(ValidationError):
        ModelPolicy(model='other', prompt_version='v1', max_output_tokens=1, price=price())
    with pytest.raises(ValidationError):
        CallRequest(task_id='task', expected_task_revision=True, call_key='key',
                    input_digest='a' * 64, policy=policy(), input_token_allowance=1)


def test_reservation_rounds_up_and_uses_integer_micro_dollars():
    from app.domain.model_usage.pricing import reserve_micro_usd
    assert reserve_micro_usd(policy(), 100) == 120
    cheap = policy().model_copy(update={'price': price().model_copy(update={
        'input_micro_usd_per_million': 1, 'output_micro_usd_per_million': 1})})
    assert reserve_micro_usd(cheap, 1, 3) == 4


def test_cached_and_reasoning_tokens_are_not_counted_twice():
    from app.domain.model_usage.pricing import estimate_usage
    observed = {'input_tokens': 100, 'output_tokens': 10, 'total_tokens': 110,
                'input_tokens_details': {'cached_tokens': 20, 'cache_write_tokens': 0},
                'output_tokens_details': {'reasoning_tokens': 4}}
    result = estimate_usage(price(), observed)
    assert result['estimated_cost_micro_usd'] == 102
    assert result['usage_status'] == 'estimated'
    assert result['provider_usage'] == observed


def test_cache_writes_require_supported_price_and_are_retained():
    from app.domain.model_usage.pricing import estimate_usage
    observed = {'input_tokens': 10, 'output_tokens': 0,
                'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 4}}
    assert estimate_usage(price(), observed)['usage_status'] == 'pending'
    result = estimate_usage(price(cache_write_micro_usd_per_million=3_000_000), observed)
    assert result['estimated_cost_micro_usd'] == 18


@pytest.mark.parametrize('detail_fields', [{}, {'input_tokens_details': None},
    {'input_tokens_details': {}}, {'input_tokens_details': {'cached_tokens': 0}},
    {'input_tokens_details': {'cache_write_tokens': 0}}])
def test_positive_input_without_both_cache_details_remains_pending(detail_fields):
    from app.domain.model_usage.pricing import estimate_usage
    observed = {'input_tokens': 50, 'output_tokens': 5, **detail_fields}
    result = estimate_usage(price(), observed)
    assert result['usage_status'] == 'pending'
    assert result['reason_code'] == 'usage_missing'
    assert result['estimated_cost_micro_usd'] == 60


@pytest.mark.parametrize('detail_fields', [{}, {'input_tokens_details': None},
    {'input_tokens_details': {}}, {'input_tokens_details': {'cached_tokens': 0}},
    {'input_tokens_details': {'cache_write_tokens': 0}}])
def test_explicit_zero_input_does_not_require_cache_details(detail_fields):
    from app.domain.model_usage.pricing import estimate_usage
    result = estimate_usage(price(), {'input_tokens': 0, 'output_tokens': 5, **detail_fields})
    assert result['usage_status'] == 'estimated'
    assert result['estimated_cost_micro_usd'] == 10


def test_complete_priced_usage_does_not_require_total_or_reasoning_details():
    from app.domain.model_usage.pricing import estimate_usage
    result = estimate_usage(price(), {'input_tokens': 50, 'output_tokens': 5,
        'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0}})
    assert result['usage_status'] == 'estimated'
    assert result['estimated_cost_micro_usd'] == 60


@pytest.mark.parametrize('observed', [None, {}, {'input_tokens': 1},
    {'input_tokens': True, 'output_tokens': 0},
    {'input_tokens': 1, 'output_tokens': 0, 'new_billable_tokens': 9,
     'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0}}])
def test_missing_invalid_or_unknown_usage_never_becomes_free(observed):
    from app.domain.model_usage.pricing import estimate_usage
    assert estimate_usage(price(), observed)['usage_status'] == 'pending'


def test_tools_unknown_preserve_partial_estimate_and_explicit_zero_is_valid():
    from app.domain.model_usage.pricing import estimate_usage
    observed = {'input_tokens': 0, 'output_tokens': 0}
    result = estimate_usage(price(), observed, tools=['code_interpreter'])
    assert result['estimated_cost_micro_usd'] == 0 and result['usage_status'] == 'pending'
    assert estimate_usage(price(), observed)['usage_status'] == 'estimated'


def test_known_usage_above_configuration_cap_is_fully_estimated():
    from app.domain.model_usage.pricing import estimate_usage
    high = price().model_copy(update={'input_micro_usd_per_million': 1_000_000_000_000})
    result = estimate_usage(high, {'input_tokens': 2_000_000, 'output_tokens': 0,
        'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0}})
    assert result['estimated_cost_micro_usd'] == 2_000_000_000_000
    assert result['usage_status'] == 'estimated'


def test_missing_output_preserves_known_input_estimate_as_pending():
    from app.domain.model_usage.pricing import estimate_usage
    result = estimate_usage(price(), {'input_tokens': 200,
        'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0}})
    assert result['estimated_cost_micro_usd'] == 200
    assert result['usage_status'] == 'pending'


def test_actual_tool_estimate_is_not_limited_to_configuration_cap():
    from app.domain.model_usage.pricing import estimate_usage
    result = estimate_usage(price(), {'input_tokens': 0, 'output_tokens': 0},
                            tools=['code_interpreter'], tool_cost_micro_usd=2_000_000_000_000)
    assert result['estimated_cost_micro_usd'] == 2_000_000_000_000
    assert result['usage_status'] == 'estimated'
