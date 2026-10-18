"""Bounded, deterministic fixed-tool correlations. No source, network or model code."""
from math import factorial
import warnings

import numpy as np
from scipy import stats

MAX_ROWS = 10_000
MAX_COLUMNS = 10
MONTE_CARLO_RESAMPLES = 9_999
DEFAULT_SEED = 1729


class CorrelationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _invalid(message='Correlation input is invalid.'):
    return CorrelationError('correlation_invalid_input', message)


def _matrix(rows, mode):
    if not isinstance(rows, list):
        raise _invalid()
    if len(rows) > MAX_ROWS:
        raise CorrelationError('correlation_input_limit', 'At most 10000 complete observations are supported.')
    if len(rows) < 3:
        raise CorrelationError('correlation_sample_size', 'At least three complete observations are required.')
    if not isinstance(rows[0], list):
        raise _invalid()
    width = len(rows[0])
    if width > MAX_COLUMNS:
        raise CorrelationError('correlation_input_limit', 'At most ten variables are supported.')
    if width < 2 or mode == 'pair' and width != 2:
        raise _invalid('Pair mode requires two variables; matrix mode requires two to ten.')
    for row in rows:
        if (not isinstance(row, list) or len(row) != width
                or any(type(value) not in (int, float) for value in row)):
            raise _invalid()
    try:
        array = np.asarray(rows, dtype=np.float64)
    except (ValueError, TypeError, OverflowError) as exc:
        raise _invalid() from exc
    if not np.isfinite(array).all():
        raise _invalid('Every selected value must be finite.')
    # Positive scaling preserves correlations while preventing overflow in centering.
    scales = np.max(np.abs(array), axis=0)
    if np.any(scales == 0):
        raise CorrelationError('correlation_constant', 'A selected variable is constant.')
    normalized = array / scales
    if np.any(np.max(normalized, axis=0) == np.min(normalized, axis=0)):
        raise CorrelationError('correlation_constant', 'A selected variable is constant.')
    mean = normalized.mean(axis=0)
    norm = np.linalg.norm(normalized - mean, axis=0)
    if np.any(norm < np.finfo(np.float64).eps ** .75 * np.abs(mean)):
        raise CorrelationError('correlation_near_constant', 'A selected variable is numerically near constant.')
    # Rank the original finite values: scaling can underflow distinct tiny values
    # in a variable that also contains a huge observation and create false ties.
    return array, normalized


def _empty_interval(reason):
    return dict(low=None, high=None, level=.95, method=None, reason=reason)


def _inference(method):
    return dict(alternative='two-sided', rank_method='average' if method == 'spearman' else None,
                permutation_type=None, n_resamples=None, seed=None, exact=None)


def _pearson(x, y, n):
    result = stats.pearsonr(x, y, alternative='two-sided')
    coefficient = float(result.statistic)
    p_value = dict(value=float(result.pvalue), method='pearson_beta_two_sided', reason=None)
    if n <= 3:
        interval = _empty_interval('insufficient_for_fisher_interval')
    elif abs(coefficient) >= 1 - 8 * np.finfo(np.float64).eps:
        interval = _empty_interval('degenerate_correlation')
    else:
        limits = result.confidence_interval(confidence_level=.95)
        if not np.isfinite([limits.low, limits.high]).all():
            interval = _empty_interval('degenerate_correlation')
        else:
            interval = dict(low=float(limits.low), high=float(limits.high), level=.95, method='fisher_z', reason=None)
    return coefficient, p_value, interval, _inference('pearson')


def _spearman(x, y, n, seed):
    rx, ry = stats.rankdata(x, method='average'), stats.rankdata(y, method='average')
    coefficient = float(stats.pearsonr(rx, ry).statistic)
    inference = _inference('spearman')
    if n > 500:
        p_value = dict(value=float(stats.spearmanr(x, y, alternative='two-sided').pvalue),
                       method='spearman_asymptotic', reason=None)
        inference['exact'] = False
    else:
        # Ranks are computed once. Permuting their row correspondence preserves ties.
        # Normalize once for bounded, vectorized dot products during permutations.
        rx = (rx - rx.mean()) / np.linalg.norm(rx - rx.mean())
        ry = (ry - ry.mean()) / np.linalg.norm(ry - ry.mean())

        def statistic(permuted, axis=-1):
            return np.sum(permuted * ry, axis=axis)

        exact = n <= 7
        count = factorial(n) if exact else MONTE_CARLO_RESAMPLES
        result = stats.permutation_test((rx,), statistic, permutation_type='pairings',
            vectorized=True, n_resamples=np.inf if exact else count, batch=128,
            alternative='two-sided', rng=np.random.default_rng(seed))
        p_value = dict(value=float(result.pvalue),
            method='spearman_pairings_exact' if exact else 'spearman_pairings_monte_carlo', reason=None)
        inference.update(permutation_type='pairings', n_resamples=count, seed=None if exact else seed, exact=exact)
    return coefficient, p_value, _empty_interval('spearman_interval_not_implemented'), inference


def compute_correlation(rows: list[list[float]], *, method: str, mode: str, seed: int = DEFAULT_SEED) -> dict:
    """Return finite result fields; callers must supply confirmed independent complete rows.

    Source exclusion/identity/assumption checks belong to the plan consumer, not here.
    Scale limits and fixed resampling count bound memory and statistical work.
    """
    if (method not in ('pearson', 'spearman') or mode not in ('pair', 'matrix')
            or type(seed) is not int or not 0 <= seed <= 2**32 - 1):
        raise _invalid('Unsupported method, mode or random seed.')
    array, normalized = _matrix(rows, mode)
    n = len(array)
    with warnings.catch_warnings():
        warnings.simplefilter('error', stats.ConstantInputWarning)
        warnings.simplefilter('error', stats.NearConstantInputWarning)
        try:
            if mode == 'matrix':
                values = stats.rankdata(array, method='average', axis=0) if method == 'spearman' else normalized
                coefficients = np.clip(np.corrcoef(values, rowvar=False), -1., 1.)
                np.fill_diagonal(coefficients, 1.)
                if not np.isfinite(coefficients).all():
                    raise _invalid('Matrix computation did not produce finite coefficients.')
                return dict(method=method, mode=mode, n=n, coefficient=None, matrix=coefficients.tolist(),
                    p_value=dict(value=None, method=None, reason='exploratory_matrix'),
                    confidence_interval=_empty_interval('exploratory_matrix'), inference=_inference(method),
                    warnings=['exploratory_matrix', 'correlation_not_causation'])
            output = (_pearson(normalized[:, 0], normalized[:, 1], n) if method == 'pearson'
                      else _spearman(array[:, 0], array[:, 1], n, seed))
        except (stats.ConstantInputWarning, stats.NearConstantInputWarning) as exc:
            code = 'correlation_near_constant' if isinstance(exc, stats.NearConstantInputWarning) else 'correlation_constant'
            raise CorrelationError(code, 'The selected values do not support a reliable correlation.') from exc
    coefficient, p_value, interval, inference = output
    if not np.isfinite(coefficient) or not np.isfinite(p_value['value']):
        raise _invalid('Computation did not produce finite statistics.')
    codes = ['correlation_not_causation']
    if n < 10:
        codes.append('small_sample')
    if inference['exact'] is False:
        codes.append('monte_carlo_p_value' if inference['seed'] is not None else 'asymptotic_p_value')
    return dict(method=method, mode=mode, n=n, coefficient=coefficient, matrix=None,
                p_value=p_value, confidence_interval=interval, inference=inference, warnings=codes)
