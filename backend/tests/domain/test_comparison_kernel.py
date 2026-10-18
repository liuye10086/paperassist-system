"""Independent formulas/enumerations for the six approved comparison methods."""
from copy import deepcopy
from fractions import Fraction
from itertools import combinations, product
import math

import mpmath as mp
import pytest

from app.domain.comparison.kernel import ComparisonError, compute_comparison, holm_adjust, validate_comparison_inputs


@pytest.fixture(autouse=True)
def postgres_schema():
    # Pure fixed numerical functions never need a database or business fixtures.
    yield None


def mean_variance(values):
    values = [Fraction(x) for x in values]
    mean = sum(values) / len(values)
    return mean, sum((x - mean) ** 2 for x in values) / (len(values) - 1)


def t_tail(t, df):
    return float(mp.betainc(df / 2, .5, 0, df / (df + t * t), regularized=True))


def critical_t(df):
    low, high = 0., 100.
    for _ in range(100):
        mid = (low + high) / 2
        if t_tail(mid, df) > .05:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def ranks(values):
    ordered = sorted(values)
    return [sum(Fraction(i + 1) for i, y in enumerate(ordered) if y == x) / ordered.count(x) for x in values]


def test_welch_t_matches_independent_fraction_formula_and_interval():
    x, y = [1., 2., 4., 8.], [2., 5., 6., 7., 10.]
    result = compute_comparison([x, y], method='welch_t')
    mx, vx = mean_variance(x); my, vy = mean_variance(y)
    a, b = vx / len(x), vy / len(y)
    df = float((a + b) ** 2 / (a * a / (len(x) - 1) + b * b / (len(y) - 1)))
    delta, se = float(mx - my), math.sqrt(a + b)
    assert result['statistic']['value'] == pytest.approx(delta / se, rel=1e-13)
    assert result['statistic']['df_denominator'] == pytest.approx(df, rel=1e-13)
    assert result['p_value']['value'] == pytest.approx(t_tail(delta / se, df), rel=1e-13)
    assert result['estimate']['value'] == pytest.approx(delta)
    assert result['confidence_interval']['low'] == pytest.approx(delta - critical_t(df) * se, rel=1e-11)
    assert result['confidence_interval']['high'] == pytest.approx(delta + critical_t(df) * se, rel=1e-11)
    assert result['sample_sizes'] == [4, 5]


def test_paired_t_difference_direction_and_complete_pair_count():
    first, second = [4., 6., 8., 11.], [2., 5., 4., 5.]
    differences = [a - b for a, b in zip(first, second)]
    mean, variance = mean_variance(differences)
    result = compute_comparison([first, second], method='paired_t')
    expected = float(mean) / math.sqrt(variance / len(first))
    assert result['design'] == 'paired' and result['sample_sizes'] == [4, 4]
    assert result['estimate']['value'] == pytest.approx(float(mean))
    assert result['statistic']['value'] == pytest.approx(expected, rel=1e-13)
    assert result['p_value']['value'] == pytest.approx(t_tail(expected, 3), rel=1e-13)
    reversed_result = compute_comparison([second, first], method='paired_t')
    assert reversed_result['estimate']['value'] == -result['estimate']['value']
    assert reversed_result['p_value'] == result['p_value']


def test_paired_t_preserves_small_differences_on_large_shared_baseline():
    # The integer differences are exactly representable even with a large offset.
    # Scaling the original measurements first would corrupt those differences.
    first = [10_000_000_000. + v for v in (4, 6, 8, 11, 13, 15)]
    second = [10_000_000_000. + v for v in (2, 5, 4, 5, 12, 12)]
    mean, variance = mean_variance([2, 1, 4, 6, 1, 3])
    value = compute_comparison([first, second], method='paired_t')
    expected_t = float(mean) / math.sqrt(variance / 6)
    assert value['estimate']['value'] == pytest.approx(float(mean), rel=1e-14)
    assert value['statistic']['value'] == pytest.approx(expected_t, rel=1e-14)
    assert value['p_value']['value'] == pytest.approx(t_tail(expected_t, 5), rel=1e-13)


@pytest.mark.parametrize('method', ['welch_t', 'welch_anova'])
def test_mean_inference_is_translation_invariant_at_large_baseline(method):
    groups = [[1., 2., 4., 7., 9.], [2., 4., 5., 8., 12.], [5., 6., 8., 10., 15.]]
    if method == 'welch_t':
        groups = groups[:2]
    expected = compute_comparison(groups, method=method)
    actual = compute_comparison([[10_000_000_000. + x for x in group] for group in groups], method=method)
    assert actual['statistic']['value'] == pytest.approx(expected['statistic']['value'], rel=1e-13)
    assert actual['p_value']['value'] == pytest.approx(expected['p_value']['value'], rel=1e-13)
    if method == 'welch_t':
        assert actual['estimate']['value'] == pytest.approx(-1.6, rel=1e-13)


def test_mann_whitney_exact_matches_independent_label_enumeration():
    x, y = [1., 3., 5.], [2., 4., 6., 7.]
    result = compute_comparison([x, y], method='mann_whitney_u')
    observed = sum(a > b for a in x for b in y)
    pooled = x + y
    null = []
    for indexes in combinations(range(len(pooled)), len(x)):
        left = set(indexes)
        null.append(sum(pooled[i] > pooled[j] for i in left for j in range(len(pooled)) if j not in left))
    p = min(1., 2 * min(sum(u <= observed for u in null), sum(u >= observed for u in null)) / len(null))
    assert result['statistic']['value'] == observed
    assert result['p_value']['value'] == pytest.approx(p, rel=1e-14)
    assert result['estimate']['value'] == pytest.approx(2 * observed / (len(x) * len(y)) - 1)
    assert result['inference']['exact'] is True
    assert result['confidence_interval']['reason'] == 'rank_interval_not_implemented'


def test_mann_whitney_ties_use_corrected_asymptotic_distribution():
    x, y = [1., 2., 2., 4.], [2., 3., 5., 5.]
    pooled = x + y; rank = ranks(pooled); n1, n2 = len(x), len(y); n = n1 + n2
    u = float(sum(rank[:n1]) - Fraction(n1 * (n1 + 1), 2))
    tie_term = sum(pooled.count(v) ** 3 - pooled.count(v) for v in set(pooled))
    sigma = math.sqrt(n1 * n2 / 12 * (n + 1 - tie_term / (n * (n - 1))))
    z = (max(u, n1 * n2 - u) - n1 * n2 / 2 - .5) / sigma
    expected = min(1., math.erfc(z / math.sqrt(2)))
    result = compute_comparison([x, y], method='mann_whitney_u')
    assert result['statistic']['value'] == u
    assert result['p_value']['value'] == pytest.approx(expected, rel=1e-13)
    assert result['inference']['exact'] is False
    assert result['inference']['continuity_correction'] is True


def test_wilcoxon_tied_nonzero_ranks_and_zeros_match_exact_sign_enumeration():
    differences = [1., -2., 2., 0., 3., 3.]
    first, second = [10. + d for d in differences], [10.] * len(differences)
    nonzero = [d for d in differences if d]
    rank = ranks([abs(d) for d in nonzero])
    observed = sum(r for r, d in zip(rank, nonzero) if d > 0)
    null = [sum(r for r, sign in zip(rank, signs) if sign) for signs in product([0, 1], repeat=len(rank))]
    expected_p = min(1., 2 * min(sum(v <= observed for v in null), sum(v >= observed for v in null)) / len(null))
    result = compute_comparison([first, second], method='wilcoxon')
    assert result['statistic']['value'] == float(min(observed, sum(rank) - observed))
    assert result['p_value']['value'] == pytest.approx(expected_p, rel=1e-14)
    assert result['estimate']['value'] == pytest.approx(float((2 * observed - sum(rank)) / sum(rank)))
    assert result['inference']['zero_count'] == 1 and result['inference']['exact'] is True
    assert result['sample_sizes'] == [6, 6]


def test_wilcoxon_large_sample_is_explicit_asymptotic_and_not_random():
    first = [float(i * (-1 if i % 3 else 1)) for i in range(1, 19)]
    result = compute_comparison([first, [0.] * len(first)], method='wilcoxon')
    assert result['inference']['exact'] is False
    assert result['inference']['continuity_correction'] is True
    assert result == compute_comparison([first, [0.] * len(first)], method='wilcoxon')


def test_welch_anova_matches_manual_formula_and_has_no_fabricated_global_difference():
    groups = [[1., 2., 4., 7.], [3., 6., 7., 8., 12.], [2., 4., 10., 12.]]
    means, variances = zip(*(mean_variance(g) for g in groups))
    k = len(groups); weights = [len(g) / v for g, v in zip(groups, variances)]
    total = sum(weights); weighted_mean = sum(w * m for w, m in zip(weights, means)) / total
    term = sum((1 - w / total) ** 2 / (len(g) - 1) for w, g in zip(weights, groups))
    f = float(sum(w * (m - weighted_mean) ** 2 for w, m in zip(weights, means)) / (k - 1) / (1 + 2 * (k - 2) * term / (k * k - 1)))
    df2 = float((k * k - 1) / (3 * term))
    expected_p = float(mp.betainc(df2 / 2, (k - 1) / 2, 0, df2 / (df2 + (k - 1) * f), regularized=True))
    result = compute_comparison(groups, method='welch_anova')
    assert result['statistic']['value'] == pytest.approx(f, rel=1e-13)
    assert result['statistic']['df_denominator'] == pytest.approx(df2, rel=1e-13)
    assert result['p_value']['value'] == pytest.approx(expected_p, rel=1e-13)
    assert result['estimate']['value'] is None and result['estimate']['reason'] == 'omnibus_no_single_effect'
    assert result['confidence_interval']['reason'] == 'omnibus_no_interval'
    assert result['inference']['alternative'] == 'omnibus'


def test_kruskal_tie_corrected_statistic_against_manual_ranks():
    groups = [[1., 2., 2., 3., 4.], [2., 4., 5., 7., 9.], [5., 6., 6., 8., 10.]]
    pooled = sum(groups, []); ranked = ranks(pooled); n = len(pooled)
    sums = [sum(ranked[i * 5:i * 5 + 5]) for i in range(3)]
    h = Fraction(12, n * (n + 1)) * sum(r * r / 5 for r in sums) - 3 * (n + 1)
    correction = 1 - Fraction(sum(pooled.count(v) ** 3 - pooled.count(v) for v in set(pooled)), n ** 3 - n)
    expected = float(h / correction)
    result = compute_comparison(groups, method='kruskal_wallis')
    assert result['statistic']['value'] == pytest.approx(expected, rel=1e-13)
    assert result['p_value']['value'] == pytest.approx(math.exp(-expected / 2), rel=1e-13)


def test_holm_known_family_preserves_original_order_and_ties():
    assert holm_adjust([.03, .001, .04, .02]) == pytest.approx([.06, .004, .06, .06])
    assert holm_adjust([.01, .01, .9]) == pytest.approx([.03, .03, .9])
    assert holm_adjust([0., 1.]) == [0., 1.]


@pytest.mark.parametrize('method,paired_method', [('welch_anova', 'welch_t'), ('kruskal_wallis', 'mann_whitney_u')])
def test_all_pairs_exist_even_without_significant_omnibus(method, paired_method):
    groups = [[1., 2., 3., 4., 5.]] * 3
    original = deepcopy(groups)
    result = compute_comparison(groups, method=method, posthoc='all_pairs_holm')
    assert result['p_value']['value'] == 1.
    assert [(p['left_index'], p['right_index']) for p in result['pairwise']] == [(0, 1), (0, 2), (1, 2)]
    assert all(p['method'] == paired_method and p['adjustment'] == 'holm' and p['adjusted_p_value'] == 1. for p in result['pairwise'])
    assert result['family'] == {'policy': 'all_pairs_holm', 'size': 3, 'alpha': .05}
    assert all(p['confidence_interval']['simultaneous'] is False for p in result['pairwise'])
    assert groups == original


@pytest.mark.parametrize('groups,method,code', [
    ([[1., 2.], [1., 2., 3.]], 'welch_t', 'comparison_sample_size'),
    ([[1., 2., 3.]] * 3, 'kruskal_wallis', 'comparison_sample_size'),
    ([[1., 2., 3.], [2., 3., 4., 5.]], 'paired_t', 'comparison_invalid_input'),
    ([[1., 2., True], [2., 3., 4.]], 'welch_t', 'comparison_invalid_input'),
    ([[1., 2., float('nan')], [2., 3., 4.]], 'welch_t', 'comparison_invalid_input'),
    ([[1., 2., float('inf')], [2., 3., 4.]], 'welch_t', 'comparison_invalid_input'),
    ([[1., 1., 1.], [2., 3., 4.]], 'welch_t', 'comparison_constant'),
    ([[1., 2., 3.], [1., 2., 3.]], 'paired_t', 'comparison_constant'),
    ([[1., 2., 3.], [1., 2., 3.]], 'wilcoxon', 'comparison_constant'),
    ([[1., 1., 1.], [1., 1., 1.]], 'mann_whitney_u', 'comparison_constant'),
    ([[1., 2., 3.]] * 7, 'welch_anova', 'comparison_input_limit'),
    ([list(map(float, range(5001)))] * 2, 'welch_t', 'comparison_input_limit'),
    ([[1e14, 1e14 + 1, 1e14 + 2], [1., 2., 3.]], 'welch_t', 'comparison_near_constant'),
])
def test_invalid_inputs_are_explicit_and_leave_inputs_unchanged(groups, method, code):
    with pytest.raises(ComparisonError) as exc:
        compute_comparison(groups, method=method)
    assert exc.value.code == code and exc.value.message


def test_unknown_method_and_pairwise_policy_are_not_silently_substituted():
    for method, policy in [('student_t', 'none'), ('welch_t', 'all_pairs_holm'), ('welch_anova', 'bonferroni')]:
        with pytest.raises(ComparisonError) as exc:
            compute_comparison([[1., 2., 3.], [2., 3., 4.]], method=method, posthoc=policy)
        assert exc.value.code == 'comparison_invalid_input'


def test_public_validation_is_bounded_and_matches_execution_contract():
    assert validate_comparison_inputs([[1., 2., 3.], [2., 3., 5.]], method='welch_t') is None
    with pytest.raises(ComparisonError):
        validate_comparison_inputs([[1., 2.], [2., 3.]], method='welch_t')


def test_degenerate_pair_in_full_family_is_blocked_before_plan_publication():
    groups = [[1.] * 5, [1.] * 5, [1., 2., 3., 4., 5.]]
    # The omnibus can be computed, but the requested all-pairs family includes
    # two identical constant samples. Validate that exact family at plan time.
    validate_comparison_inputs(groups, method='kruskal_wallis')
    for operation in (validate_comparison_inputs, compute_comparison):
        with pytest.raises(ComparisonError) as exc:
            operation(groups, method='kruskal_wallis', posthoc='all_pairs_holm')
        assert exc.value.code == 'comparison_constant'


@pytest.mark.parametrize('values', [[], [True], [float('nan')], [-.1], [1.1], [.01] * 16])
def test_holm_refuses_missing_invalid_or_unbounded_families(values):
    with pytest.raises(ComparisonError):
        holm_adjust(values)


@pytest.mark.parametrize('method', ['welch_t', 'paired_t'])
def test_common_positive_scale_keeps_inference_and_restores_estimate_units(method):
    groups = [[1., 2., 4., 8.], [2., 3., 5., 9.5]]
    normal = compute_comparison(groups, method=method)
    scaled = compute_comparison([[value * 1e120 for value in g] for g in groups], method=method)
    assert scaled['statistic']['value'] == pytest.approx(normal['statistic']['value'], rel=1e-13)
    assert scaled['p_value']['value'] == pytest.approx(normal['p_value']['value'], rel=1e-13)
    assert scaled['estimate']['value'] == pytest.approx(normal['estimate']['value'] * 1e120, rel=1e-13)


def test_rank_inputs_are_not_rescaled_into_false_ties():
    groups = [[1e-300, 2e-300, 1e300], [3e-300, 4e-300, 2e300]]
    actual = compute_comparison(groups, method='mann_whitney_u')
    expected = compute_comparison([[1., 2., 5.], [3., 4., 6.]], method='mann_whitney_u')
    assert actual['statistic'] == expected['statistic']
    assert actual['p_value'] == expected['p_value']
