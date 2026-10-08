"""Frozen-price integer estimates, preserving uncertainty rather than zeroing it."""
from app.domain.model_usage.contracts import MAX_ACCOUNTED_MICRO_USD, MAX_MICRO_USD

MILLION = 1_000_000


def _ceil_micro(numerator):
    return (numerator + MILLION - 1) // MILLION


def reserve_micro_usd(policy, input_token_allowance, tool_reserve_micro_usd=0):
    # An allowance is an upper bound, so use the largest supported input rate.
    rates = [policy.price.input_micro_usd_per_million,
             policy.price.cached_input_micro_usd_per_million]
    if policy.price.cache_write_micro_usd_per_million is not None:
        rates.append(policy.price.cache_write_micro_usd_per_million)
    amount = _ceil_micro(input_token_allowance * max(rates)
                         + policy.max_output_tokens * policy.price.output_micro_usd_per_million)
    amount += tool_reserve_micro_usd
    if amount > MAX_MICRO_USD:
        raise ValueError('Reservation exceeds the supported monetary range.')
    return amount


def estimate_usage(price, usage, *, tools=None, tool_cost_micro_usd=None):
    result = {'provider_usage': None, 'estimated_cost_micro_usd': None,
              'usage_status': 'pending', 'reason_code': 'usage_missing'}
    if not isinstance(usage, dict):
        return result
    allowed = {'input_tokens', 'output_tokens', 'total_tokens',
               'input_tokens_details', 'output_tokens_details'}
    detail_fields = {'input_tokens_details': {'cached_tokens', 'cache_write_tokens'},
                     'output_tokens_details': {'reasoning_tokens'}}
    clean, unsupported, invalid = {}, bool(set(usage) - allowed), False
    for name, value in usage.items():
        if name not in allowed:
            continue
        if name in detail_fields:
            if value is None:
                continue
            if not isinstance(value, dict):
                invalid = True
                continue
            unsupported |= bool(set(value) - detail_fields[name])
            clean[name] = {}
            for key, count in value.items():
                if key not in detail_fields[name]:
                    continue
                if type(count) is not int or not 0 <= count <= MAX_MICRO_USD:
                    invalid = True
                else:
                    clean[name][key] = count
        elif type(value) is not int or not 0 <= value <= MAX_MICRO_USD:
            invalid = True
        else:
            clean[name] = value
    result['provider_usage'] = clean
    if invalid:
        result['reason_code'] = 'usage_invalid'
        return result
    complete = 'input_tokens' in clean and 'output_tokens' in clean
    if 'input_tokens' not in clean and 'output_tokens' not in clean:
        return result
    inputs, outputs = clean.get('input_tokens', 0), clean.get('output_tokens', 0)
    details = clean.get('input_tokens_details', {})
    cached, written = details.get('cached_tokens', 0), details.get('cache_write_tokens', 0)
    reasoning = clean.get('output_tokens_details', {}).get('reasoning_tokens', 0)
    if (cached + written > inputs or reasoning > outputs
            or (complete and 'total_tokens' in clean and clean['total_tokens'] != inputs + outputs)):
        result['reason_code'] = 'usage_invalid'
        return result
    if written and price.cache_write_micro_usd_per_million is None:
        result['reason_code'] = 'price_unsupported'
        return result
    # Missing billable cache categories are not evidence that their counts are zero.
    complete = complete and (inputs == 0 or {'cached_tokens', 'cache_write_tokens'} <= details.keys())
    amount = _ceil_micro((inputs - cached - written) * price.input_micro_usd_per_million
        + cached * price.cached_input_micro_usd_per_million
        + written * (price.cache_write_micro_usd_per_million or 0)
        + outputs * price.output_micro_usd_per_million)
    if tool_cost_micro_usd is not None:
        if type(tool_cost_micro_usd) is not int or not 0 <= tool_cost_micro_usd <= MAX_ACCOUNTED_MICRO_USD:
            result['reason_code'] = 'tool_cost_invalid'
            return result
        amount += tool_cost_micro_usd
    if amount > MAX_ACCOUNTED_MICRO_USD:
        result['reason_code'] = 'amount_out_of_range'
        return result
    result['estimated_cost_micro_usd'] = amount
    if not complete:
        result['reason_code'] = 'usage_missing'
    elif unsupported:
        result['reason_code'] = 'usage_unsupported'
    elif tools and tool_cost_micro_usd is None:
        result['reason_code'] = 'tool_cost_unknown'
    else:
        result.update(usage_status='estimated', reason_code=None)
    return result
