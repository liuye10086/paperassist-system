"""Independent numerical oracles for the approved correlation methods."""
from fractions import Fraction
from itertools import permutations
import math
from statistics import NormalDist

import pytest

from app.domain.correlation.kernel import CorrelationError, compute_correlation


@pytest.fixture(autouse=True)
def postgres_schema():
    # This numerical module has no persistence. Do not create 28 unused schemas.
    yield None


def manual_r(x, y):
    mx, my = sum(x) / len(x), sum(y) / len(y)
    numerator = sum((a - mx) * (b - my) for a, b in zip(x, y))
    return numerator / math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))


def manual_ranks(values):
    ordered = sorted(values)
    return [sum(Fraction(i + 1) for i, v in enumerate(ordered) if v == x) / ordered.count(x) for x in values]


def exhaustive_spearman_p(x, y):
    rx, ry = manual_ranks(x), manual_ranks(y)
    observed = manual_r(rx, ry)
    null = [manual_r(p, ry) for p in permutations(rx)]
    left = sum(v <= observed + 1e-12 for v in null) / len(null)
    right = sum(v >= observed - 1e-12 for v in null) / len(null)
    return min(1., 2 * min(left, right))


def test_pearson_closed_form_and_fisher_interval_without_scipy_oracle():
    rows = [[1., 2.], [2., 1.], [3., 4.], [4., 3.], [5., 5.]]
    result = compute_correlation(rows, method='pearson', mode='pair')
    assert result['n'] == 5
    assert result['coefficient'] == pytest.approx(.8, abs=1e-14)
    # For n=5 the exact beta density integrates to this elementary expression.
    expected_p = 2 / math.pi * (math.acos(.8) - .8 * math.sqrt(1 - .8**2))
    assert result['p_value']['value'] == pytest.approx(expected_p, abs=1e-14)
    assert result['p_value']['method'] == 'pearson_beta_two_sided'
    delta = NormalDist().inv_cdf(.975) / math.sqrt(2)
    interval = result['confidence_interval']
    assert interval['low'] == pytest.approx(math.tanh(math.atanh(.8) - delta), abs=1e-14)
    assert interval['high'] == pytest.approx(math.tanh(math.atanh(.8) + delta), abs=1e-14)
    assert interval['method'] == 'fisher_z'
    assert interval['reason'] is None
    assert result['matrix'] is None


@pytest.mark.parametrize('method', ['pearson', 'spearman'])
@pytest.mark.parametrize('sign', [-1, 1])
def test_perfect_relationship_and_interval_is_not_fabricated(method, sign):
    result = compute_correlation([[float(i), float(sign * i)] for i in range(1, 6)], method=method, mode='pair')
    assert result['coefficient'] == pytest.approx(sign)
    assert result['confidence_interval']['low'] is None
    assert result['confidence_interval']['high'] is None
    if method == 'pearson':
        assert result['p_value']['value'] == pytest.approx(0, abs=1e-15)
        assert result['confidence_interval']['reason'] == 'degenerate_correlation'
    else:
        assert result['p_value']['value'] == pytest.approx(2 / math.factorial(5))
        assert result['confidence_interval']['reason'] == 'spearman_interval_not_implemented'


def test_zero_pearson_with_exact_uniform_null():
    result = compute_correlation([[-3., 1.], [-1., -1.], [1., -1.], [3., 1.]], method='pearson', mode='pair')
    assert result['coefficient'] == pytest.approx(0, abs=1e-14)
    assert result['p_value']['value'] == pytest.approx(1)


def test_tied_spearman_uses_average_ranks_and_independent_exhaustive_p():
    x, y = [1., 2., 2., 4.], [1., 2., 3., 4.]
    result = compute_correlation(list(map(list, zip(x, y))), method='spearman', mode='pair')
    assert result['coefficient'] == pytest.approx(3 / math.sqrt(10))
    assert result['p_value']['value'] == pytest.approx(exhaustive_spearman_p(x, y))
    assert result['inference'] == dict(alternative='two-sided', rank_method='average', permutation_type='pairings',
        n_resamples=24, seed=None, exact=True)


def test_three_rows_have_p_but_no_informative_fisher_interval():
    result = compute_correlation([[1., 2.], [2., 1.], [3., 3.]], method='pearson', mode='pair')
    assert result['n'] == 3
    assert result['p_value']['value'] is not None
    assert result['confidence_interval']['low'] is None
    assert result['confidence_interval']['reason'] == 'insufficient_for_fisher_interval'


@pytest.mark.parametrize('method', ['pearson', 'spearman'])
def test_matrix_is_exploratory_symmetric_and_does_not_mutate_input(method):
    rows = [[float(i), float(6-i), float(j)] for i, j in zip(range(1, 6), [2, 1, 4, 3, 5])]
    original = [r[:] for r in rows]
    result = compute_correlation(rows, method=method, mode='matrix')
    assert rows == original
    assert result['n'] == 5 and result['coefficient'] is None
    assert result['matrix'][0] == pytest.approx([1, -1, .8])
    assert result['matrix'][1] == pytest.approx([-1, 1, -.8])
    assert result['matrix'][2] == pytest.approx([.8, -.8, 1])
    assert result['p_value'] == dict(value=None, method=None, reason='exploratory_matrix')
    assert result['confidence_interval'] == dict(low=None, high=None, level=.95, method=None, reason='exploratory_matrix')
    assert result['inference']['n_resamples'] is None


def test_monte_carlo_reproducibility_and_recorded_parameters():
    rows = [[float(i), float(j)] for i, j in enumerate([2, 1, 4, 3, 8, 5, 7, 6], start=1)]
    first = compute_correlation(rows, method='spearman', mode='pair')
    again = compute_correlation(rows, method='spearman', mode='pair')
    assert first == again
    assert first['coefficient'] == pytest.approx(manual_r(*zip(*rows)))
    assert 0 < first['p_value']['value'] <= 1
    assert first['p_value']['method'] == 'spearman_pairings_monte_carlo'
    assert first['inference']['n_resamples'] == 9999
    assert first['inference']['seed'] == 1729
    assert first['inference']['exact'] is False


def test_large_spearman_records_asymptotic_method():
    result = compute_correlation([[float(i), float(-i)] for i in range(501)], method='spearman', mode='pair')
    assert result['coefficient'] == pytest.approx(-1)
    assert result['p_value']['method'] == 'spearman_asymptotic'
    assert result['inference']['n_resamples'] is None
    assert result['inference']['exact'] is False


@pytest.mark.parametrize('rows,mode,code', [
    ([], 'pair', 'correlation_sample_size'),
    ([[1., 1.], [2., 2.]], 'pair', 'correlation_sample_size'),
    ([[1., 1.]] * 10001, 'pair', 'correlation_input_limit'),
    ([[1., 2.], [2., 3., 4.], [3., 4.]], 'pair', 'correlation_invalid_input'),
    ([[1.], [2.], [3.]], 'pair', 'correlation_invalid_input'),
    ([[1.] * 11] * 3, 'matrix', 'correlation_input_limit'),
    ([[True, 1.], [2., 2.], [3., 3.]], 'pair', 'correlation_invalid_input'),
    ([[None, 1.], [2., 2.], [3., 3.]], 'pair', 'correlation_invalid_input'),
    ([[float('nan'), 1.], [2., 2.], [3., 3.]], 'pair', 'correlation_invalid_input'),
    ([[float('inf'), 1.], [2., 2.], [3., 3.]], 'pair', 'correlation_invalid_input'),
    ([[1., 1.], [1., 2.], [1., 3.]], 'pair', 'correlation_constant'),
    ([[1e12, 1.], [1e12+.001, 2.], [1e12+.002, 3.]], 'pair', 'correlation_near_constant'),
])
def test_invalid_input_fails_before_any_statistic_is_claimed(rows, mode, code):
    with pytest.raises(CorrelationError) as caught:
        compute_correlation(rows, method='pearson', mode=mode)
    assert caught.value.code == code


@pytest.mark.parametrize('method,mode,seed', [('kendall','pair',1729), ('pearson','unknown',1729), ('spearman','pair',True)])
def test_unapproved_method_and_invalid_parameters_are_rejected(method, mode, seed):
    with pytest.raises(CorrelationError) as caught:
        compute_correlation([[1., 1.], [2., 3.], [3., 2.]], method=method, mode=mode, seed=seed)
    assert caught.value.code == 'correlation_invalid_input'


def test_extreme_finite_values_are_scaled_without_overflow():
    result = compute_correlation([[-1e308, -2.], [0., 0.], [1e308, 2.]], method='pearson', mode='pair')
    assert result['coefficient'] == pytest.approx(1)
    # At n=3, the exact null CDF has a square-root boundary at |r|=1:
    # binary64 rounding of r can legitimately produce a P around 1e-8.
    expected = 2 / math.pi * math.acos(abs(result['coefficient']))
    assert result['p_value']['value'] == pytest.approx(expected, abs=1e-14)
    assert result['p_value']['value'] < 2e-8


@pytest.mark.parametrize('mode', ['pair', 'matrix'])
def test_spearman_ranks_survive_mixed_extreme_magnitudes(mode):
    rows = [[1e-300, 1.], [2e-300, 2.], [3e-300, 3.], [1e308, 4.]]
    result = compute_correlation(rows, method='spearman', mode=mode)
    value = result['coefficient'] if mode == 'pair' else result['matrix'][0][1]
    assert value == pytest.approx(1, abs=1e-14)
