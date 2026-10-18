"""Bounded fixed comparisons over already approved observations; no I/O or code execution."""
from itertools import combinations
import math
import warnings

import numpy as np
from scipy import stats

MAX_ROWS = 10_000
MAX_GROUPS = 6
METHOD_DESIGNS = {'welch_t': 'independent', 'mann_whitney_u': 'independent',
    'paired_t': 'paired', 'wilcoxon': 'paired', 'welch_anova': 'multiple', 'kruskal_wallis': 'multiple'}


class ComparisonError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def _invalid(message='Comparison input or parameters are invalid.'):
    return ComparisonError('comparison_invalid_input', message)


def _variance_check(values):
    scale = float(np.max(np.abs(values)))
    if scale == 0 or np.min(values) == np.max(values):
        raise ComparisonError('comparison_constant', 'The required variation is zero.')
    normalized = values / scale
    mean = normalized.mean()
    if np.linalg.norm(normalized - mean) < np.finfo(float).eps ** .75 * abs(mean):
        raise ComparisonError('comparison_near_constant', 'Variation is too small relative to the values for reliable inference.')


def _inputs(groups, method, posthoc):
    if (not isinstance(method, str) or method not in METHOD_DESIGNS or posthoc not in ('none', 'all_pairs_holm')
            or posthoc != 'none' and METHOD_DESIGNS[method] != 'multiple'):
        raise _invalid('Unsupported method or comparison family; no fallback is applied.')
    if not isinstance(groups, list) or any(not isinstance(group, list) for group in groups):
        raise _invalid()
    if len(groups) > MAX_GROUPS:
        raise ComparisonError('comparison_input_limit', 'At most six groups are supported.')
    design = METHOD_DESIGNS[method]
    if len(groups) < 2 or design == 'multiple' and len(groups) < 3 or design != 'multiple' and len(groups) != 2:
        raise _invalid('The number of groups does not match the declared design.')
    if design == 'paired' and len(groups[0]) != len(groups[1]):
        raise _invalid('Paired observations must have identical lengths and confirmed correspondence.')
    count = len(groups[0]) if design == 'paired' else sum(map(len, groups))
    if count > MAX_ROWS:
        raise ComparisonError('comparison_input_limit', 'At most 10000 observations or complete pairs are supported.')
    minimum = 5 if method == 'kruskal_wallis' else 3
    if any(len(group) < minimum for group in groups):
        raise ComparisonError('comparison_sample_size', f'At least {minimum} observations per group or complete pairs are required.')
    if any(type(value) not in (int, float) for group in groups for value in group):
        raise _invalid('Only finite numeric observations are accepted.')
    try:
        arrays = [np.asarray(group, dtype=np.float64) for group in groups]
    except (ValueError, TypeError, OverflowError) as exc:
        raise _invalid() from exc
    if any(not np.isfinite(group).all() for group in arrays):
        raise _invalid('Every observation must be finite.')
    if method in ('welch_t', 'welch_anova'):
        for array in arrays:
            _variance_check(array)
    elif method in ('paired_t', 'wilcoxon'):
        with np.errstate(over='ignore', invalid='ignore'):
            differences = arrays[0] - arrays[1]
        if not np.isfinite(differences).all():
            raise _invalid('Paired differences exceed the finite numeric range.')
        if not np.any(differences):
            raise ComparisonError('comparison_constant', 'All paired differences are zero.')
        if method == 'paired_t':
            _variance_check(differences)
    elif min(float(np.min(a)) for a in arrays) == max(float(np.max(a)) for a in arrays):
        raise ComparisonError('comparison_constant', 'All ranked observations are identical.')
    if method == 'kruskal_wallis' and posthoc == 'all_pairs_holm':
        for left, right in combinations(arrays, 2):
            if min(float(np.min(left)), float(np.min(right))) == max(float(np.max(left)), float(np.max(right))):
                raise ComparisonError('comparison_constant', 'A requested rank-comparison pair contains only one constant value.')
    return arrays, design


def validate_comparison_inputs(groups, *, method, posthoc='none'):
    """Validate source-independent method bounds without computing inferential P values."""
    _inputs(groups, method, posthoc)


def holm_adjust(values):
    """Strong family-wise step-down adjustment, retaining the predeclared order."""
    if (not isinstance(values, list) or not values or len(values) > 15
            or any(type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1 for value in values)):
        raise _invalid('Holm requires a finite, nonempty complete family of at most fifteen P values.')
    adjusted = [0.] * len(values)
    bound = 0.
    for position, index in enumerate(sorted(range(len(values)), key=lambda i: values[i])):
        bound = max(bound, min(1., (len(values) - position) * values[index]))
        adjusted[index] = float(bound)
    return adjusted


def _interval(reason):
    return dict(low=None, high=None, level=.95, method=None, reason=reason, simultaneous=False)


def _test_result(name, value, p, p_method, *, df1=None, df2=None, estimate=None,
                 interval=None, inference=None):
    return dict(statistic=dict(name=name, value=float(value), df_numerator=df1, df_denominator=df2),
        estimate=estimate or dict(name=None, value=None, unit=None, reason='omnibus_no_single_effect'),
        p_value=dict(value=float(p), method=p_method), confidence_interval=interval or _interval('omnibus_no_interval'),
        inference=inference or dict(alternative='two-sided', rank_method=None, zero_method=None,
            continuity_correction=False, exact=False, zero_count=0))


def _centered_scale(arrays):
    # A shared translation preserves group differences, but avoids subtracting
    # two rounded scaled means when observations share a large baseline.
    low = min(float(np.min(a)) for a in arrays)
    high = max(float(np.max(a)) for a in arrays)
    midpoint = low / 2 + high / 2
    centered = [array - midpoint for array in arrays]
    scale = max(float(np.max(np.abs(array))) for array in centered)
    return [array / scale for array in centered], scale


def _mean_test(arrays, method):
    # A common positive scale keeps t/F calculations safe while preserving units
    # on estimates and intervals. Scaling is never used to rank input values.
    if method == 'paired_t':
        # Subtract first: scaling two large shared baselines before subtraction
        # would lose differences that the original input represents exactly.
        differences = arrays[0] - arrays[1]
        scale = float(np.max(np.abs(differences)))
        normalized = differences / scale
        result = stats.ttest_1samp(normalized, 0., alternative='two-sided', nan_policy='raise')
        delta = float(np.mean(normalized))
    else:
        normalized, scale = _centered_scale(arrays)
        if any(np.var(a, ddof=1) == 0 for a in normalized):
            raise _invalid('Scaling cannot preserve the required group variation.')
        result = stats.ttest_ind(*normalized, equal_var=False, alternative='two-sided', nan_policy='raise')
        delta = float(np.mean(normalized[0])) - float(np.mean(normalized[1]))
    limits = result.confidence_interval(confidence_level=.95)
    return _test_result('t', result.statistic, result.pvalue, method+'_two_sided', df2=float(result.df),
        estimate=dict(name='mean_difference', value=delta * scale, unit='outcome', reason=None),
        interval=dict(low=float(limits.low) * scale, high=float(limits.high) * scale, level=.95,
            method=method, reason=None, simultaneous=False))


def _mann_whitney(arrays):
    x, y = arrays
    pooled = np.concatenate(arrays)
    exact = np.unique(pooled).size == pooled.size and min(len(x), len(y)) <= 8 and max(len(x), len(y)) <= 50
    result = stats.mannwhitneyu(x, y, alternative='two-sided', method='exact' if exact else 'asymptotic',
        use_continuity=not exact, nan_policy='raise')
    return _test_result('U', result.statistic, result.pvalue,
        'mann_whitney_exact_two_sided' if exact else 'mann_whitney_asymptotic_two_sided',
        estimate=dict(name='rank_biserial', value=float(2 * result.statistic / (len(x) * len(y)) - 1), unit='dimensionless', reason=None),
        interval=_interval('rank_interval_not_implemented'),
        inference=dict(alternative='two-sided', rank_method='average', zero_method=None,
            continuity_correction=not exact, exact=bool(exact), zero_count=0))


def _wilcoxon(arrays):
    differences = arrays[0] - arrays[1]
    nonzero = differences[differences != 0]
    ranked = stats.rankdata(np.abs(nonzero), method='average')
    positive = float(np.sum(ranked[nonzero > 0])); total = float(np.sum(ranked))
    exact = len(nonzero) <= 15
    statistic = min(positive, total - positive)
    if exact:
        # Average ranks are multiples of 1/2. Integer dynamic enumeration counts
        # all 2**n sign assignments, including multiplicities of tied ranks.
        weights = [int(round(2 * rank)) for rank in ranked]
        distribution = [1]
        for weight in weights:
            expanded = distribution + [0] * weight
            for i, count in enumerate(distribution):
                expanded[i + weight] += count
            distribution = expanded
        observed = int(round(2 * positive))
        p = min(1., 2 * min(sum(distribution[:observed + 1]), sum(distribution[observed:])) / (2 ** len(weights)))
    else:
        p = float(stats.wilcoxon(differences, zero_method='wilcox', correction=True,
            alternative='two-sided', method='asymptotic', nan_policy='raise').pvalue)
    return _test_result('W', statistic, p,
        'wilcoxon_sign_exact_two_sided' if exact else 'wilcoxon_asymptotic_two_sided',
        estimate=dict(name='rank_biserial', value=(2 * positive - total) / total, unit='dimensionless', reason=None),
        interval=_interval('rank_interval_not_implemented'),
        inference=dict(alternative='two-sided', rank_method='average', zero_method='wilcox',
            continuity_correction=not exact, exact=exact, zero_count=int(len(differences) - len(nonzero))))


def _omnibus(arrays, method):
    k = len(arrays)
    if method == 'welch_anova':
        normalized, _ = _centered_scale(arrays)
        variances = np.asarray([np.var(a, ddof=1) for a in normalized])
        if np.any(variances <= 0):
            raise _invalid('Scaling cannot preserve the required group variation.')
        weights = np.asarray([len(a) for a in arrays]) / variances
        term = sum((1 - w / weights.sum()) ** 2 / (len(a) - 1) for w, a in zip(weights, arrays))
        result = stats.f_oneway(*normalized, equal_var=False, nan_policy='raise')
        value = _test_result('F', result.statistic, result.pvalue, 'welch_anova_f',
            df1=float(k - 1), df2=float((k * k - 1) / (3 * term)))
    else:
        result = stats.kruskal(*arrays, nan_policy='raise')
        value = _test_result('H', result.statistic, result.pvalue, 'kruskal_chi_square', df1=float(k - 1))
        value['inference']['rank_method'] = 'average'
    value['inference']['alternative'] = 'omnibus'
    return value


def _single(arrays, method):
    if method in ('welch_t', 'paired_t'):
        return _mean_test(arrays, method)
    if method == 'mann_whitney_u':
        return _mann_whitney(arrays)
    if method == 'wilcoxon':
        return _wilcoxon(arrays)
    return _omnibus(arrays, method)


def _finite_output(value):
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_finite_output(v) for v in value.values())
    if isinstance(value, list):
        return all(_finite_output(v) for v in value)
    return True


def compute_comparison(groups, *, method, posthoc='none'):
    """Compute only the approved fixed method and the frozen complete comparison family."""
    arrays, design = _inputs(groups, method, posthoc)
    try:
        with warnings.catch_warnings(), np.errstate(over='raise', divide='raise', invalid='raise'):
            warnings.simplefilter('error', RuntimeWarning)
            result = _single(arrays, method)
            pairs = []
            if posthoc == 'all_pairs_holm':
                pair_method = 'welch_t' if method == 'welch_anova' else 'mann_whitney_u'
                for left, right in combinations(range(len(arrays)), 2):
                    pair = _single([arrays[left], arrays[right]], pair_method)
                    pairs.append(dict(left_index=left, right_index=right, method=pair_method, **pair))
                adjusted = holm_adjust([pair['p_value']['value'] for pair in pairs])
                for pair, p in zip(pairs, adjusted):
                    pair.update(adjusted_p_value=p, adjustment='holm')
    except (FloatingPointError, OverflowError, RuntimeWarning, ZeroDivisionError) as exc:
        raise _invalid('The requested inference exceeds a reliable finite numeric range.') from exc
    codes = ['observational_not_causal']
    if min(map(len, arrays)) < 10:
        codes.append('small_sample')
    tests = [result] + pairs
    if method in ('mann_whitney_u', 'wilcoxon', 'kruskal_wallis') and any(not item['inference']['exact'] for item in tests):
        codes.append('asymptotic_p_value')
    if method in ('mann_whitney_u', 'wilcoxon', 'kruskal_wallis'):
        codes.append('rank_interval_unavailable')
    if pairs and method == 'welch_anova':
        codes.append('pairwise_intervals_unadjusted')
    if result['inference']['zero_count']:
        codes.append('zero_differences_excluded')
    output = dict(method=method, design=design, sample_sizes=[len(a) for a in arrays], **result,
        family=dict(policy=posthoc, size=len(pairs), alpha=.05), pairwise=pairs, warnings=codes)
    if not _finite_output(output) or not 0 <= output['p_value']['value'] <= 1:
        raise _invalid('Computation did not produce finite, valid statistical output.')
    return output
